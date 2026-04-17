"""
ComfyUI API Client — sends video generation prompts via the Vast.ai API Wrapper.

Auth: Authorization: Bearer <TOKEN> header
Endpoint: POST /generate/sync
Payload: { "input": { "request_id": "...", "workflow_json": {...} } }

Node Mapping (from LTX 2.3 workflow):
  267:266 → Positive prompt
  267:247 → Negative prompt
  267:225 → Frame count
  267:237 → Random seed
  267:257 → Width
  267:258 → Height
  267:201 → Text2Video switch
"""

import json
import os
import logging
import copy
import random
import httpx

logger = logging.getLogger(__name__)

WORKFLOW_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "video_ltx2_3_t2v-2.json"
)

NODES = {
    "prompt": "267:266",
    "negative_prompt": "267:247",
    "frame_count": "267:225",
    "seed": "267:237",
    "width": "267:257",
    "height": "267:258",
    "t2v_switch": "267:201",
    "frame_rate": "267:260",
    "save_video": "75",
}

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 25
MAX_FRAMES = 121


class ComfyUIClient:
    """Client for ComfyUI via Vast.ai API wrapper.

    Auth: Authorization: Bearer <TOKEN> header on all requests.
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

        # Auth header — per Vast.ai docs
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        logger.info(
            f"ComfyUI client initialized: wrapper={self.api_wrapper_url}, "
            f"comfyui={self.comfyui_url}"
        )

    def _load_workflow_template(self) -> dict:
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
        workflow = copy.deepcopy(self._load_workflow_template())

        frame_count = min(int(DEFAULT_FPS * duration_seconds), MAX_FRAMES)
        frame_count = (frame_count // 8) * 8 + 1

        if seed is None:
            seed = random.randint(0, 2**53)

        workflow[NODES["prompt"]]["inputs"]["value"] = prompt
        workflow[NODES["negative_prompt"]]["inputs"]["text"] = negative_prompt
        workflow[NODES["frame_count"]]["inputs"]["value"] = frame_count
        workflow[NODES["seed"]]["inputs"]["noise_seed"] = seed
        workflow[NODES["width"]]["inputs"]["value"] = width
        workflow[NODES["height"]]["inputs"]["value"] = height
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
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.api_wrapper_url}/queue-info",
                    headers=self._headers,
                )
                is_ok = resp.status_code == 200
                logger.info(f"Health check: {resp.status_code} → {'OK' if is_ok else 'FAIL'}")
                return is_ok
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    # ================================================================
    # Generate via API Wrapper
    # ================================================================

    async def generate_sync(self, workflow: dict, request_id: str) -> dict:
        """POST /generate/sync with Bearer auth and wrapped payload."""
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
        logger.info(f"Sending generation request to {url} (request_id={request_id})")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers=self._headers,
                json=payload,
            )
            logger.info(f"Response status: {resp.status_code}")
            resp.raise_for_status()
            result = resp.json()

        logger.info(f"Generation completed for {request_id}: status={result.get('status')}")
        return result

    # ================================================================
    # Extract output filename
    # ================================================================

    def _extract_video_info(self, result: dict) -> tuple[str | None, str]:
        """Extract video filename and subfolder from the API wrapper response.

        Returns:
            (filename, subfolder) tuple. subfolder defaults to 'video'.
        """
        comfyui_resp = result.get("comfyui_response", {})

        # comfyui_response can be nested: {prompt_id: {prompt: [...], outputs: {node: {gifs: [...]}}}}
        for key, value in comfyui_resp.items():
            if isinstance(value, dict):
                outputs = value.get("outputs", {})
                if outputs:
                    for node_id, node_output in outputs.items():
                        for media_key in ["gifs", "videos", "images"]:
                            items = node_output.get(media_key, [])
                            if items:
                                item = items[0]
                                filename = item.get("filename")
                                subfolder = item.get("subfolder", "video")
                                if filename:
                                    logger.info(f"Found output: {filename} (subfolder={subfolder})")
                                    return filename, subfolder

                # Also check direct node outputs (flat structure)
                for media_key in ["gifs", "videos", "images"]:
                    items = value.get(media_key, [])
                    if items:
                        item = items[0]
                        filename = item.get("filename")
                        subfolder = item.get("subfolder", "video")
                        if filename:
                            logger.info(f"Found output: {filename} (subfolder={subfolder})")
                            return filename, subfolder

        # Check top-level output
        output = result.get("output", [])
        if output and isinstance(output, list):
            for item in output:
                if isinstance(item, dict) and "filename" in item:
                    return item["filename"], item.get("subfolder", "video")

        logger.warning(f"No output file found. Response keys: {list(result.keys())}")
        return None, "video"

    # ================================================================
    # Download
    # ================================================================

    async def download_video(self, filename: str, subfolder: str, save_path: str) -> str:
        """Download a generated video from ComfyUI."""
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        download_base = self.comfyui_url or self.api_wrapper_url

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(
                f"{download_base}/view",
                headers=self._headers,
                params={"filename": filename, "type": "output", "subfolder": subfolder},
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

        workflow = self._build_workflow(
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration_seconds=duration_seconds,
            seed=seed,
            width=width,
            height=height,
        )

        request_id = f"{job_id}_scene_{scene_number:02d}"
        result = await self.generate_sync(workflow, request_id)

        filename, subfolder = self._extract_video_info(result)

        response = {
            "request_id": request_id,
            "filename": filename,
            "video_url": None,
            "local_path": None,
        }

        if filename:
            download_base = self.comfyui_url or self.api_wrapper_url
            response["video_url"] = (
                f"{download_base}/view?filename={filename}&type=output&subfolder={subfolder}"
            )

            output_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "output", job_id,
            )
            save_path = os.path.join(output_dir, f"scene_{scene_number:02d}.mp4")
            try:
                local_path = await self.download_video(filename, subfolder, save_path)
                response["local_path"] = local_path
            except Exception as e:
                logger.error(f"Failed to download video: {e}")

        return response
