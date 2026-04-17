"""
ComfyUI API Client — sends video generation prompts via the Vast.ai API Wrapper.

Authentication: token as query param + Authorization: Bearer header.
Endpoint: POST /generate/sync?token=TOKEN
Payload:  { "input": { "workflow_json": {...}, "request_id": "..." } }

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
    """Client for interacting with ComfyUI via the Vast.ai API wrapper.

    Uses /generate/sync with both:
    - ?token=TOKEN query param
    - Authorization: Bearer TOKEN header
    """

    def __init__(
        self,
        api_wrapper_url: str,
        token: str,
        comfyui_url: str | None = None,
        timeout: float = 600,
    ):
        self.api_wrapper_url = api_wrapper_url.rstrip("/")
        self.token = token
        self.comfyui_url = comfyui_url.rstrip("/") if comfyui_url else None
        self.timeout = timeout
        self._workflow_template = None

        # Auth: both query param and Bearer header
        self._auth_headers = {"Authorization": f"Bearer {self.token}"}
        self._auth_params = {"token": self.token}

        logger.info(
            f"ComfyUI client initialized: wrapper={self.api_wrapper_url}, "
            f"comfyui={self.comfyui_url}, token={'set' if self.token else 'none'}"
        )

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
        """Check if the API wrapper is reachable."""
        try:
            # Don't follow redirects — just check if server responds
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.api_wrapper_url}/queue-info",
                    params=self._auth_params,
                    headers=self._auth_headers,
                )
                # Accept any response (even 302/401) as "server is up"
                logger.info(
                    f"API wrapper health check ({self.api_wrapper_url}): "
                    f"{resp.status_code}"
                )
                return True  # If we got ANY response, server is alive
        except Exception as e:
            logger.warning(f"API wrapper health check failed (no response): {e}")
            return False

    # ================================================================
    # Generate via API Wrapper
    # ================================================================

    async def generate_sync(self, workflow: dict, request_id: str) -> dict:
        """Send a workflow for synchronous generation via the API wrapper.

        Uses POST /generate/sync with:
        - ?token=TOKEN query param
        - Authorization: Bearer TOKEN header
        - NO redirect following (to prevent POST→GET conversion)
        """
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

        url = f"{self.api_wrapper_url}/generate/sync"
        logger.info(f"Sending sync generation request to {url} (request_id={request_id})")

        # IMPORTANT: Do NOT follow redirects — POST→GET conversion breaks the API
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            resp = await client.post(
                url,
                params=self._auth_params,
                headers=self._auth_headers,
                json=payload,
            )

            # If we get a redirect, follow it manually as POST
            if resp.status_code in (301, 302, 307, 308):
                redirect_url = resp.headers.get("location", "")
                logger.info(f"Got {resp.status_code} redirect to: {redirect_url}")
                if redirect_url:
                    resp = await client.post(
                        redirect_url,
                        params=self._auth_params,
                        headers=self._auth_headers,
                        json=payload,
                    )

            logger.info(f"Response status: {resp.status_code}")
            resp.raise_for_status()
            result = resp.json()

        logger.info(f"Generation response received for {request_id}")
        return result

    # ================================================================
    # Extract output filename
    # ================================================================

    def _extract_video_filename(self, result: dict) -> str | None:
        """Extract the video filename from the API wrapper response."""

        # Check comfyui_response
        comfyui_resp = result.get("comfyui_response", {})

        # Search all nodes for video/image output
        for node_id, node_output in comfyui_resp.items():
            if isinstance(node_output, dict):
                for key in ["gifs", "videos", "images"]:
                    items = node_output.get(key, [])
                    if items:
                        filename = items[0].get("filename")
                        if filename:
                            logger.info(f"Found output in node {node_id}: {filename}")
                            return filename

        # Check top-level output field
        output = result.get("output", [])
        if output and isinstance(output, list):
            for item in output:
                if isinstance(item, dict) and "filename" in item:
                    return item["filename"]

        logger.warning("No output file found in response")
        logger.debug(f"Full response keys: {list(result.keys())}")
        return None

    # ================================================================
    # Download
    # ================================================================

    async def download_video(self, filename: str, save_path: str) -> str:
        """Download a generated video from ComfyUI (direct URL, no auth needed)."""
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # Use direct ComfyUI URL for downloads (no auth needed per test_api-2.py)
        download_base = self.comfyui_url or self.api_wrapper_url

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(
                f"{download_base}/view",
                params={"filename": filename, "type": "output"},
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
        """Full pipeline: build workflow → generate via wrapper → download."""
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

        # Generate via API wrapper (synchronous)
        request_id = f"{job_id}_scene_{scene_number:02d}"
        result = await self.generate_sync(workflow, request_id)

        # Extract filename
        filename = self._extract_video_filename(result)

        response = {
            "request_id": request_id,
            "filename": filename,
            "video_url": None,
            "local_path": None,
        }

        if filename:
            # Build video URL using direct ComfyUI URL
            download_base = self.comfyui_url or self.api_wrapper_url
            response["video_url"] = (
                f"{download_base}/view?filename={filename}&type=output"
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
