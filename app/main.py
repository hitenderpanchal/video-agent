"""
FastAPI Application — REST API for the AI Video Content Agent Pipeline.

Endpoints:
  POST /api/generate      → Start content generation job
  GET  /api/status/{id}   → Poll job status
  GET  /api/result/{id}   → Get completed result
  GET  /api/health        → Health check
  GET  /api/jobs           → List recent jobs
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import (
    GenerateRequest,
    GenerateResponse,
    JobStatusResponse,
    JobResultResponse,
    HealthResponse,
    JobStatus,
)
from app.job_manager import job_manager, Job
from app.crew.crew import VideoContentCrew

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("video-agent-api")

# --- Thread pool for running CrewAI (which is blocking) ---
executor = ThreadPoolExecutor(max_workers=3)

# --- Track server start time ---
START_TIME = time.time()


# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("=" * 60)
    logger.info("🚀 Video Agent API starting up")
    logger.info(f"   LLM Provider: {settings.llm_provider}")
    logger.info(f"   LLM Model:    {settings.llm_model}")
    logger.info(f"   LLM Base URL: {settings.llm_base_url}")
    logger.info(f"   API Port:     {settings.api_port}")
    logger.info("=" * 60)
    yield
    logger.info("Video Agent API shutting down")
    executor.shutdown(wait=False)


# --- FastAPI App ---
app = FastAPI(
    title="AI Video Content Agent API",
    description=(
        "Multi-agent AI system that generates complete video content packages: "
        "story, script, voiceover, video prompts, image prompts, and thumbnail prompts."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# --- CORS (allow n8n and any frontend to call us) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Background Pipeline Runner
# ============================================================

def _run_pipeline_sync(job: Job, request: GenerateRequest):
    """Run the CrewAI pipeline synchronously (called in thread pool).

    This runs in a separate thread because CrewAI's kickoff() is blocking.
    """
    try:
        job.mark_running()
        logger.info(f"Job {job.job_id}: Pipeline started")

        # Create crew with step callback for progress tracking
        crew = VideoContentCrew(request)

        # Map step names to progress percentages
        step_progress = {
            "Initializing agents": 5,
            "Creating tasks": 10,
            "Starting Story Writer": 15,
            "Running pipeline — Story Writer": 20,
            "Running pipeline — Script Writer": 35,
            "Running pipeline — Voiceover Writer": 50,
            "Running pipeline — Video Prompt Agent": 65,
            "Running pipeline — Image Prompt Agent": 75,
            "Running pipeline — Thumbnail Agent": 85,
            "Parsing results": 90,
            "Generating videos via ComfyUI": 92,
            "Completed": 100,
        }

        def step_callback(step_name: str, progress: int):
            """Update job with current step — called from crew pipeline."""
            job.update_step(step_name, step_progress.get(step_name, progress))

        crew.set_step_callback(step_callback)

        # Run the pipeline
        result = crew.run(job_id=job.job_id)

        # Mark as completed
        job.mark_completed(result)
        logger.info(
            f"Job {job.job_id}: Pipeline completed in "
            f"{job.execution_time_seconds:.1f}s"
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        job.mark_failed(error_msg)
        logger.error(f"Job {job.job_id}: Pipeline failed — {error_msg}", exc_info=True)


# ============================================================
# API Endpoints
# ============================================================

@app.post("/api/generate", response_model=GenerateResponse)
async def generate_content(request: GenerateRequest):
    """Start a new video content generation job.

    This endpoint:
    1. Validates the request
    2. Creates a background job
    3. Returns a job_id for status polling
    4. The pipeline runs asynchronously

    **n8n Integration:**
    Call this endpoint via HTTP Request node, then poll /api/status/{job_id}
    until status is "completed", then fetch /api/result/{job_id}.
    """
    logger.info(
        f"New generation request: '{request.user_input[:100]}' "
        f"| type={request.video_type.value} "
        f"| duration={request.duration_seconds}s "
        f"| scenes={request.num_scenes}"
    )

    # Create a job
    job = await job_manager.create_job(user_input=request.user_input)

    # Submit to thread pool
    loop = asyncio.get_event_loop()
    loop.run_in_executor(executor, _run_pipeline_sync, job, request)

    return GenerateResponse(
        job_id=job.job_id,
        status=JobStatus.QUEUED,
        message=f"Job queued. Poll /api/status/{job.job_id} for progress.",
    )


@app.get("/api/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Poll the status of a generation job.

    Returns current step name and progress percentage.
    n8n should poll this every 5-10 seconds until status is "completed" or "failed".
    """
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        current_step=job.current_step,
        progress_percent=job.progress_percent,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        error=job.error,
    )


@app.get("/api/result/{job_id}", response_model=JobResultResponse)
async def get_job_result(job_id: str):
    """Get the completed result of a generation job.

    Returns the full VideoContentPackage with all scenes, prompts, and metadata.
    Only available when job status is "completed".
    """
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status == JobStatus.QUEUED or job.status == JobStatus.RUNNING:
        raise HTTPException(
            status_code=202,
            detail=f"Job is still {job.status.value}. Current step: {job.current_step}",
        )

    return JobResultResponse(
        job_id=job.job_id,
        status=job.status,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        completed_at=job.completed_at,
        execution_time_seconds=job.execution_time_seconds,
    )


@app.get("/api/jobs")
async def list_jobs(limit: int = 20):
    """List recent jobs with their statuses."""
    jobs = await job_manager.list_jobs(limit=limit)
    return {
        "jobs": [
            {
                "job_id": job.job_id,
                "status": job.status.value,
                "current_step": job.current_step,
                "progress_percent": job.progress_percent,
                "user_input": job.user_input[:100],
                "created_at": job.created_at.isoformat(),
            }
            for job in jobs
        ]
    }


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for monitoring."""
    return HealthResponse(
        status="healthy",
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        version="1.0.0",
        uptime_seconds=round(time.time() - START_TIME, 2),
    )


# ============================================================
# Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# ============================================================
