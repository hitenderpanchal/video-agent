"""
ComfyUI API Client — sends video generation prompts to ComfyUI.

Supports two modes:
1. Direct ComfyUI API (POST /prompt) — standard ComfyUI
2. API Wrapper (POST /generate/sync?token=) — Vast.ai wrapper

Node Mapping (from LTX 2.3 workflow_api.json):
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
import asyncio

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
    """Client for interacting with ComfyUI.

    Tries two approaches:
    1. API Wrapper (/generate/sync with token) — if api_wrapper_url is set
    2. Direct ComfyUI API (/prompt) — standard ComfyUI REST API
    """

    def __init__(
        self,
        comfyui_url: str,
        api_wrapper_url: str | None = None,
        token: str | None = None,
        timeout: float = 600,
    ):
        self.comfyui_url = comfyui_url.rstrip("/")
        self.api_wrapper_url = api_wrapper_url.rstrip("/") if api_wrapper_url else None
        self.token = token
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())
        self._workflow_template = None
        logger.info(
            f"ComfyUI client initialized: comfyui={self.comfyui_url}, "
            f"wrapper={self.api_wrapper_url}, token={'set' if self.token else 'none'}"
        )

    def _auth_params(self, extra: dict | None = None) -> dict:
        """Build query params with authentication token."""
        params = {}
        if self.token:
            params["token"] = self.token
        if extra:
            params.update(extra)
        return params

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
        """Build a workflow by injecting parameters into the template."""
        workflow = copy.deepcopy(self._load_workflow_template())

        # Calculate frame count: fps × duration, capped at MAX_FRAMES
        frame_count = min(int(DEFAULT_FPS * duration_seconds), MAX_FRAMES)
        # Must be 8n+1 for LTX
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

    # ================================================================
    # Health Check
    # ================================================================

    async def check_health(self) -> bool:
        """Check if ComfyUI is reachable."""
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    f"{self.comfyui_url}/system_stats",
                    params=self._auth_params(),
                )
                is_ok = resp.status_code < 400
                logger.info(f"ComfyUI health check ({self.comfyui_url}): {resp.status_code} → {'OK' if is_ok else 'FAIL'}")
                return is_ok
        except Exception as e:
            logger.warning(f"ComfyUI health check failed: {e}")
            return False

    # ================================================================
    # Method 1: Direct ComfyUI API (POST /prompt → poll /history)
    # ================================================================

    async def _queue_prompt_direct(self, workflow: dict) -> str:
        """Queue a prompt via standard ComfyUI API."""
        payload = {
            "prompt": workflow,
            "client_id": self.client_id,
        }

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.post(
                f"{self.comfyui_url}/prompt",
                params=self._auth_params(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            prompt_id = data["prompt_id"]
            logger.info(f"Queued prompt via direct API: {prompt_id}")
            return prompt_id

    async def _wait_for_completion(self, prompt_id: str) -> dict:
        """Poll /history until the prompt completes."""
        start_time = time.time()
        poll_interval = 5  # seconds

        logger.info(f"Waiting for prompt {prompt_id} to complete (timeout: {self.timeout}s)...")

        while time.time() - start_time < self.timeout:
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    resp = await client.get(
                        f"{self.comfyui_url}/history/{prompt_id}",
                        params=self._auth_params(),
                    )
                    if resp.status_code == 200:
                        history = resp.json()
                        if prompt_id in history:
                            prompt_data = history[prompt_id]
                            status = prompt_data.get("status", {})

                            # Check completion
                            if status.get("completed", False) or status.get("status_str") == "success":
                                elapsed = time.time() - start_time
                                logger.info(f"Prompt {prompt_id} completed in {elapsed:.1f}s")
                                return prompt_data

                            # Check for errors
                            if status.get("status_str") == "error":
                                error_msg = str(status.get("messages", "Unknown error"))
                                raise RuntimeError(f"ComfyUI execution failed: {error_msg}")

                            # If outputs exist, it's done even without status field
                            outputs = prompt_data.get("outputs", {})
                            if outputs:
                                elapsed = time.time() - start_time
                                logger.info(f"Prompt {prompt_id} completed (outputs found) in {elapsed:.1f}s")
                                return prompt_data

            except httpx.HTTPError as e:
                logger.warning(f"Poll error (will retry): {e}")

            await asyncio.sleep(poll_interval)

        raise TimeoutError(f"ComfyUI prompt {prompt_id} did not complete within {self.timeout}s")

    # ================================================================
    # Method 2: API Wrapper (/generate/sync)
    # ================================================================

    async def _generate_via_wrapper(self, workflow: dict, request_id: str) -> dict:
        """Send a workflow via the API wrapper for synchronous generation."""
        if not self.api_wrapper_url or not self.token:
            raise ValueError("API wrapper URL and token are required for wrapper mode")

        payload = {
            "input": {
                "request_id": request_id,
                "workflow_json": workflow,
                "s3": {
                    "access_key_id": "",
                    "secret_access_key": "",
                    "endpoint_url": "",
                    "bucket_name": "",
                    "region": "",
                },
                "webhook": {
                    "url": "",
                    "extra_params": {},
                },
            }
        }

        logger.info(f"Sending sync generation request via wrapper: {request_id}")

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.post(
                f"{self.api_wrapper_url}/generate/sync",
                params={"token": self.token},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    # ================================================================
    # Unified Generate
    # ================================================================

    async def generate(self, workflow: dict, request_id: str) -> dict:
        """Generate video — tries direct ComfyUI API first, then wrapper.

        Returns:
            dict with output information
        """
        # Try direct ComfyUI API first (POST /prompt → poll /history)
        try:
            logger.info("Trying direct ComfyUI API (POST /prompt)...")
            prompt_id = await self._queue_prompt_direct(workflow)
            history = await self._wait_for_completion(prompt_id)
            return {"method": "direct", "prompt_id": prompt_id, "history": history}
        except Exception as e:
            logger.warning(f"Direct ComfyUI API failed: {e}")

        # Fallback: try API wrapper
        if self.api_wrapper_url and self.token:
            try:
                logger.info("Trying API wrapper (/generate/sync)...")
                result = await self._generate_via_wrapper(workflow, request_id)
                return {"method": "wrapper", "result": result}
            except Exception as e:
                logger.error(f"API wrapper also failed: {e}")
                raise

        raise RuntimeError("All ComfyUI generation methods failed")

    # ================================================================
    # Extract output filename
    # ================================================================

    def _extract_video_filename(self, gen_result: dict) -> str | None:
        """Extract the video filename from generation result."""

        if gen_result.get("method") == "direct":
            # Direct API: look in history → outputs
            history = gen_result.get("history", {})
            outputs = history.get("outputs", {})

            for node_id, node_output in outputs.items():
                for key in ["gifs", "videos", "images"]:
                    items = node_output.get(key, [])
                    if items:
                        filename = items[0].get("filename")
                        if filename:
                            logger.info(f"Found output in node {node_id}: {filename}")
                            return filename

        elif gen_result.get("method") == "wrapper":
            # Wrapper API: look in comfyui_response
            result = gen_result.get("result", {})
            comfyui_resp = result.get("comfyui_response", {})

            for node_id, node_output in comfyui_resp.items():
                if isinstance(node_output, dict):
                    for key in ["gifs", "videos", "images"]:
                        items = node_output.get(key, [])
                        if items:
                            filename = items[0].get("filename")
                            if filename:
                                logger.info(f"Found output in node {node_id}: {filename}")
                                return filename

            # Also check top-level output
            output = result.get("output", [])
            if output and isinstance(output, list):
                for item in output:
                    if isinstance(item, dict) and "filename" in item:
                        return item["filename"]

        logger.warning("No output file found in response")
        return None

    # ================================================================
    # Download
    # ================================================================

    async def download_video(self, filename: str, save_path: str) -> str:
        """Download a generated video from ComfyUI."""
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(
                f"{self.comfyui_url}/view",
                params=self._auth_params({"filename": filename, "type": "output"}),
            )
            resp.raise_for_status()
            with open(save_path, "wb") as f:
                f.write(resp.content)

        file_size = os.path.getsize(save_path)
        logger.info(f"Downloaded video: {save_path} ({file_size / 1024 / 1024:.1f} MB)")
        return save_path

    # ================================================================
    # Full Pipeline
    # ================================================================

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
        """Full pipeline: build workflow → generate → download."""
        logger.info(
            f"Generating video for scene {scene_number}: "
            f"'{prompt[:60]}...' ({duration_seconds}s)"
        )

        # Build workflow
        workflow = self._build_workflow(
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration_seconds=duration_seconds,
            seed=seed,
            width=width,
            height=height,
        )

        # Generate
        request_id = f"{job_id}_scene_{scene_number:02d}"
        gen_result = await self.generate(workflow, request_id)

        logger.info(f"Generation completed via {gen_result.get('method', 'unknown')} method")

        # Extract filename
        filename = self._extract_video_filename(gen_result)

        response = {
            "request_id": request_id,
            "filename": filename,
            "video_url": None,
            "local_path": None,
            "method": gen_result.get("method"),
        }

        if filename:
            response["video_url"] = (
                f"{self.comfyui_url}/view?filename={filename}&type=output"
            )

            # Download to local storage
            output_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "output", job_id,
            )
            save_path = os.path.join(output_dir, f"scene_{scene_number:02d}.mp4")
            try:
                local_path = await self.download_video(filename, save_path)
                response["local_path"] = local_path
            except Exception as e:
                logger.error(f"Failed to download video: {e}")

        return response
