"""
ComfyUI API Client — sends video generation prompts to ComfyUI and retrieves results.

Integrates with the LTX 2.3 text-to-video workflow.
Uses WebSocket for real-time progress tracking and HTTP for prompt queueing.

Node Mapping (from workflow_api.json):
  267:266 → Positive prompt (PrimitiveStringMultiline)
  267:247 → Negative prompt (CLIPTextEncode)
  267:225 → Frame count / Length (PrimitiveInt)
  267:237 → Random seed (RandomNoise)
  267:257 → Width (PrimitiveInt, default 1280)
  267:258 → Height (PrimitiveInt, default 720)
  267:201 → Text2Video switch (PrimitiveBoolean, true)
"""

import json
import os
import time
import uuid
import logging
import copy
import random
import httpx

logger = logging.getLogger(__name__)

# Path to the workflow template
WORKFLOW_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "video_ltx2_3_t2v-2.json"
)

# Node IDs in the workflow
NODES = {
    "prompt": "267:266",          # PrimitiveStringMultiline — positive prompt
    "negative_prompt": "267:247", # CLIPTextEncode — negative prompt text
    "frame_count": "267:225",     # PrimitiveInt — number of frames (length)
    "seed": "267:237",            # RandomNoise — noise_seed
    "width": "267:257",           # PrimitiveInt — video width
    "height": "267:258",          # PrimitiveInt — video height
    "t2v_switch": "267:201",      # PrimitiveBoolean — text2video mode
    "frame_rate": "267:260",      # PrimitiveInt — FPS (default 25)
    "save_video": "75",           # SaveVideo — output node
}

# Default video settings
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 25
MAX_FRAMES = 121  # LTX 2.3 max


class ComfyUIClient:
    """Client for interacting with the ComfyUI REST API."""

    def __init__(self, base_url: str, timeout: float = 600):
        """Initialize the ComfyUI client.

        Args:
            base_url: ComfyUI server URL (e.g., http://vast-ai-ip:8188)
            timeout: Max wait time for video generation in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())
        self._workflow_template = None
        logger.info(f"ComfyUI client initialized: {self.base_url}")

    def _load_workflow_template(self) -> dict:
        """Load the LTX 2.3 workflow JSON template."""
        if self._workflow_template is None:
            with open(WORKFLOW_TEMPLATE_PATH, "r") as f:
                self._workflow_template = json.load(f)
            logger.info(f"Loaded workflow template from {WORKFLOW_TEMPLATE_PATH}")
        return self._workflow_template

    def _build_workflow(
        self,
        prompt: str,
        negative_prompt: str = "pc game, console game, video game, cartoon, childish, ugly",
        duration_seconds: float = 5,
        seed: int | None = None,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
    ) -> dict:
        """Build a workflow by injecting parameters into the template.

        Args:
            prompt: Positive prompt for video generation
            negative_prompt: What to avoid in generation
            duration_seconds: Video duration in seconds
            seed: Random seed (None = random)
            width: Video width
            height: Video height

        Returns:
            Modified workflow dict ready for ComfyUI API
        """
        workflow = copy.deepcopy(self._load_workflow_template())

        # Calculate frame count: fps × duration, capped at MAX_FRAMES
        frame_count = min(int(DEFAULT_FPS * duration_seconds), MAX_FRAMES)
        # Must be odd for LTX (frame_count should be 8n+1)
        frame_count = (frame_count // 8) * 8 + 1

        if seed is None:
            seed = random.randint(0, 2**53)

        # Inject positive prompt
        workflow[NODES["prompt"]]["inputs"]["value"] = prompt

        # Inject negative prompt
        workflow[NODES["negative_prompt"]]["inputs"]["text"] = negative_prompt

        # Set frame count
        workflow[NODES["frame_count"]]["inputs"]["value"] = frame_count

        # Set seed
        workflow[NODES["seed"]]["inputs"]["noise_seed"] = seed

        # Set dimensions
        workflow[NODES["width"]]["inputs"]["value"] = width
        workflow[NODES["height"]]["inputs"]["value"] = height

        # Ensure text-to-video mode
        workflow[NODES["t2v_switch"]]["inputs"]["value"] = True

        logger.info(
            f"Built workflow: prompt={prompt[:80]}..., "
            f"frames={frame_count}, seed={seed}, {width}x{height}"
        )
        return workflow

    async def check_health(self) -> bool:
        """Check if ComfyUI server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/system_stats")
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"ComfyUI health check failed: {e}")
            return False

    async def queue_prompt(self, workflow: dict) -> str:
        """Queue a workflow for execution.

        Args:
            workflow: The workflow dict to execute

        Returns:
            prompt_id for tracking
        """
        payload = {
            "prompt": workflow,
            "client_id": self.client_id,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/prompt",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            prompt_id = data["prompt_id"]
            logger.info(f"Queued prompt: {prompt_id}")
            return prompt_id

    async def wait_for_completion(self, prompt_id: str) -> dict:
        """Poll /history until the prompt completes.

        Args:
            prompt_id: The prompt ID to wait for

        Returns:
            History dict with output information
        """
        start_time = time.time()
        poll_interval = 3  # seconds

        logger.info(f"Waiting for prompt {prompt_id} to complete...")

        while time.time() - start_time < self.timeout:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(f"{self.base_url}/history/{prompt_id}")
                    if resp.status_code == 200:
                        history = resp.json()
                        if prompt_id in history:
                            status = history[prompt_id].get("status", {})
                            if status.get("completed", False) or status.get("status_str") == "success":
                                elapsed = time.time() - start_time
                                logger.info(
                                    f"Prompt {prompt_id} completed in {elapsed:.1f}s"
                                )
                                return history[prompt_id]
                            # Check for errors
                            if status.get("status_str") == "error":
                                error_msg = status.get("messages", "Unknown error")
                                raise RuntimeError(
                                    f"ComfyUI execution failed: {error_msg}"
                                )
            except httpx.HTTPError as e:
                logger.warning(f"Poll error (will retry): {e}")

            await _async_sleep(poll_interval)

        raise TimeoutError(
            f"ComfyUI prompt {prompt_id} did not complete within {self.timeout}s"
        )

    async def get_video_url(self, history: dict) -> str | None:
        """Extract the video output URL from the history response.

        Args:
            history: The history dict for a completed prompt

        Returns:
            URL to download the video, or None if not found
        """
        outputs = history.get("outputs", {})
        for node_id, node_output in outputs.items():
            # Check for video outputs (gifs/videos)
            if "gifs" in node_output:
                for video in node_output["gifs"]:
                    filename = video.get("filename", "")
                    subfolder = video.get("subfolder", "")
                    vid_type = video.get("type", "output")
                    url = (
                        f"{self.base_url}/view?"
                        f"filename={filename}"
                        f"&subfolder={subfolder}"
                        f"&type={vid_type}"
                    )
                    logger.info(f"Found video output: {filename}")
                    return url

            # Check for video in videos key
            if "videos" in node_output:
                for video in node_output["videos"]:
                    filename = video.get("filename", "")
                    subfolder = video.get("subfolder", "")
                    vid_type = video.get("type", "output")
                    url = (
                        f"{self.base_url}/view?"
                        f"filename={filename}"
                        f"&subfolder={subfolder}"
                        f"&type={vid_type}"
                    )
                    logger.info(f"Found video output: {filename}")
                    return url

        logger.warning("No video output found in history")
        return None

    async def download_video(self, video_url: str, save_path: str) -> str:
        """Download a generated video to local storage.

        Args:
            video_url: URL from get_video_url()
            save_path: Local file path to save the video

        Returns:
            The saved file path
        """
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            with open(save_path, "wb") as f:
                f.write(resp.content)

        file_size = os.path.getsize(save_path)
        logger.info(f"Downloaded video: {save_path} ({file_size / 1024 / 1024:.1f} MB)")
        return save_path

    async def generate_scene_video(
        self,
        prompt: str,
        negative_prompt: str,
        duration_seconds: float,
        job_id: str,
        scene_number: int,
        seed: int | None = None,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
    ) -> dict:
        """Full pipeline: build workflow → queue → wait → download.

        Args:
            prompt: Video prompt for this scene
            negative_prompt: Negative prompt
            duration_seconds: Scene duration
            job_id: Job ID for file organization
            scene_number: Scene number for naming
            seed: Random seed (None = random)
            width: Video width
            height: Video height

        Returns:
            dict with video_url, local_path, prompt_id
        """
        logger.info(
            f"Generating video for scene {scene_number}: "
            f"'{prompt[:60]}...' ({duration_seconds}s)"
        )

        # Build workflow with injected parameters
        workflow = self._build_workflow(
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration_seconds=duration_seconds,
            seed=seed,
            width=width,
            height=height,
        )

        # Queue the prompt
        prompt_id = await self.queue_prompt(workflow)

        # Wait for completion
        history = await self.wait_for_completion(prompt_id)

        # Get video URL
        video_url = await self.get_video_url(history)

        result = {
            "prompt_id": prompt_id,
            "video_url": video_url,
            "local_path": None,
        }

        # Download video to local storage
        if video_url:
            output_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "output", job_id,
            )
            save_path = os.path.join(output_dir, f"scene_{scene_number:02d}.mp4")
            try:
                local_path = await self.download_video(video_url, save_path)
                result["local_path"] = local_path
            except Exception as e:
                logger.error(f"Failed to download video: {e}")

        return result


async def _async_sleep(seconds: float):
    """Async sleep helper."""
    import asyncio
    await asyncio.sleep(seconds)
