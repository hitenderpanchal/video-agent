"""
Background job manager for tracking agent pipeline execution.
Uses in-memory storage — sufficient for single-instance deployment.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models import JobStatus, VideoContentPackage


class Job:
    """Represents a single generation job."""

    def __init__(self, job_id: str, user_input: str):
        self.job_id = job_id
        self.user_input = user_input
        self.status: JobStatus = JobStatus.QUEUED
        self.current_step: str = ""
        self.progress_percent: int = 0
        self.result: Optional[VideoContentPackage] = None
        self.error: Optional[str] = None
        self.created_at: datetime = datetime.now(timezone.utc)
        self.updated_at: datetime = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None

    @property
    def execution_time_seconds(self) -> Optional[float]:
        """Calculate execution time if job is completed."""
        if self.completed_at:
            return (self.completed_at - self.created_at).total_seconds()
        return None

    def update_step(self, step: str, progress: int):
        """Update the current execution step and progress."""
        self.current_step = step
        self.progress_percent = min(progress, 100)
        self.updated_at = datetime.now(timezone.utc)

    def mark_running(self):
        """Mark job as running."""
        self.status = JobStatus.RUNNING
        self.updated_at = datetime.now(timezone.utc)

    def mark_completed(self, result: VideoContentPackage):
        """Mark job as completed with result."""
        self.status = JobStatus.COMPLETED
        self.result = result
        self.progress_percent = 100
        self.current_step = "completed"
        self.completed_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def mark_failed(self, error: str):
        """Mark job as failed with error message."""
        self.status = JobStatus.FAILED
        self.error = error
        self.current_step = "failed"
        self.completed_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class JobManager:
    """Manages background generation jobs."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, user_input: str) -> Job:
        """Create a new job and return it."""
        job_id = str(uuid.uuid4())
        job = Job(job_id=job_id, user_input=user_input)

        async with self._lock:
            self._jobs[job_id] = job

        return job

    async def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by its ID."""
        async with self._lock:
            return self._jobs.get(job_id)

    async def update_job_step(self, job_id: str, step: str, progress: int):
        """Update the current step of a running job."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update_step(step, progress)

    async def list_jobs(self, limit: int = 20) -> list[Job]:
        """List recent jobs, newest first."""
        async with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda j: j.created_at,
                reverse=True
            )
            return jobs[:limit]

    async def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Remove jobs older than max_age_hours."""
        cutoff = datetime.now(timezone.utc)
        async with self._lock:
            to_remove = [
                job_id
                for job_id, job in self._jobs.items()
                if (cutoff - job.created_at).total_seconds() > max_age_hours * 3600
                and job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
            ]
            for job_id in to_remove:
                del self._jobs[job_id]


# Singleton instance
job_manager = JobManager()
