"""
Pydantic models for API requests, responses, and structured agent output.
These models define the exact JSON schema that n8n will receive.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ============================================================
# Enums
# ============================================================

class JobStatus(str, Enum):
    """Job execution states."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoStyle(str, Enum):
    """Visual style options for generated content."""
    CINEMATIC = "cinematic"
    ANIME = "anime"
    REALISTIC = "realistic"
    CARTOON = "cartoon"
    DOCUMENTARY = "documentary"
    ABSTRACT = "abstract"
    MINIMALIST = "minimalist"
    NOIR = "noir"
    FANTASY = "fantasy"
    SCIFI = "sci-fi"


class VideoType(str, Enum):
    """Type of video content to generate."""
    EDUCATIONAL = "educational"
    ENTERTAINMENT = "entertainment"
    TUTORIAL = "tutorial"
    STORY = "story"
    MOTIVATIONAL = "motivational"
    NEWS = "news"
    DOCUMENTARY = "documentary"
    SHORT_FILM = "short_film"
    EXPLAINER = "explainer"
    PRODUCT = "product"


# ============================================================
# API Request Models
# ============================================================

class GenerateRequest(BaseModel):
    """Input from n8n / frontend to start content generation."""
    user_input: str = Field(
        ...,
        description="The user's topic, idea, or description for the video",
        min_length=5,
        max_length=5000,
        examples=["A story about a robot learning to paint in a post-apocalyptic world"]
    )
    video_type: VideoType = Field(
        default=VideoType.STORY,
        description="Type of video to generate"
    )
    duration_seconds: int = Field(
        default=120,
        ge=30,
        le=600,
        description="Target video duration in seconds"
    )
    style: VideoStyle = Field(
        default=VideoStyle.CINEMATIC,
        description="Visual style for the video"
    )
    target_audience: str = Field(
        default="general audience",
        description="Who the video is intended for",
        examples=["tech enthusiasts aged 18-35", "children aged 6-12"]
    )
    num_scenes: int = Field(
        default=5,
        ge=2,
        le=15,
        description="Number of scenes to generate"
    )
    language: str = Field(
        default="english",
        description="Language for the voiceover and script"
    )
    additional_instructions: Optional[str] = Field(
        default=None,
        description="Any additional creative direction or constraints",
        max_length=2000
    )
    comfyui_url: Optional[str] = Field(
        default=None,
        description="Direct ComfyUI URL for file downloads (e.g., http://vast-ai-ip:port)"
    )
    api_wrapper_url: Optional[str] = Field(
        default=None,
        description="API wrapper URL for authenticated ComfyUI access (e.g., http://vast-ai-ip:port)"
    )
    comfyui_token: Optional[str] = Field(
        default=None,
        description="Authentication token for the API wrapper"
    )


# ============================================================
# Structured Agent Output Models
# ============================================================

class Scene(BaseModel):
    """A single scene in the video content package."""
    scene_number: int = Field(
        ...,
        description="Sequential scene number"
    )
    scene_title: str = Field(
        ...,
        description="Short title for this scene"
    )
    description: str = Field(
        ...,
        description="Detailed visual description of what happens in this scene"
    )
    duration_seconds: int = Field(
        ...,
        description="How long this scene lasts"
    )
    voiceover_text: str = Field(
        ...,
        description="Narration text for this scene, written for spoken delivery"
    )
    video_prompt: str = Field(
        ...,
        description="ComfyUI-optimized video generation prompt for this scene"
    )
    image_prompt: str = Field(
        ...,
        description="ComfyUI-optimized image generation prompt for this scene"
    )
    negative_prompt: str = Field(
        default="blurry, low quality, distorted, deformed, watermark, text overlay, bad anatomy",
        description="Negative prompt for ComfyUI generation"
    )
    camera_movement: str = Field(
        ...,
        description="Camera movement instruction (e.g., 'slow zoom in', 'pan left to right')"
    )
    visual_style: str = Field(
        ...,
        description="Visual style for this specific scene"
    )
    mood: str = Field(
        ...,
        description="Emotional mood of the scene (e.g., 'tense', 'joyful', 'mysterious')"
    )
    transition: str = Field(
        default="fade",
        description="Transition to the next scene (e.g., 'cut', 'fade', 'dissolve', 'wipe')"
    )
    video_url: Optional[str] = Field(
        default=None,
        description="Generated video URL from ComfyUI (populated after generation)"
    )
    video_local_path: Optional[str] = Field(
        default=None,
        description="Local file path of the downloaded video"
    )


class VideoContentPackage(BaseModel):
    """Complete output package from the agent pipeline.
    This is the full structured result that n8n receives."""
    title: str = Field(
        ...,
        description="Catchy video title"
    )
    story_summary: str = Field(
        ...,
        description="Brief 2-3 sentence summary of the story"
    )
    full_story: str = Field(
        ...,
        description="Complete narrative story"
    )
    genre: str = Field(
        ...,
        description="Genre of the content"
    )
    target_audience: str = Field(
        ...,
        description="Target audience for the video"
    )
    total_duration_seconds: int = Field(
        ...,
        description="Total estimated duration in seconds"
    )
    scenes: list[Scene] = Field(
        ...,
        description="Ordered list of scenes"
    )
    thumbnail_prompt: str = Field(
        ...,
        description="ComfyUI-optimized prompt for thumbnail generation"
    )
    thumbnail_negative_prompt: str = Field(
        default="blurry, low quality, text, watermark, generic",
        description="Negative prompt for thumbnail"
    )
    thumbnail_description: str = Field(
        ...,
        description="Description of what the thumbnail should convey"
    )
    thumbnail_text_overlay: str = Field(
        default="",
        description="Suggested text to overlay on the thumbnail"
    )
    tags: list[str] = Field(
        ...,
        description="Tags for SEO and discoverability"
    )
    seo_title: str = Field(
        ...,
        description="SEO-optimized title"
    )
    seo_description: str = Field(
        ...,
        description="SEO meta description"
    )
    music_suggestion: str = Field(
        default="",
        description="Suggested background music style/mood"
    )
    color_palette: list[str] = Field(
        default_factory=list,
        description="Suggested color palette hex codes for consistency"
    )
    video_urls: list[str] = Field(
        default_factory=list,
        description="Generated video URLs from ComfyUI, one per scene"
    )


# ============================================================
# API Response Models
# ============================================================

class GenerateResponse(BaseModel):
    """Response when a generation job is submitted."""
    job_id: str = Field(
        ...,
        description="Unique job identifier for status polling"
    )
    status: JobStatus = Field(
        default=JobStatus.QUEUED,
        description="Current job status"
    )
    message: str = Field(
        default="Job queued for processing",
        description="Human-readable status message"
    )


class JobStatusResponse(BaseModel):
    """Response for job status polling."""
    job_id: str
    status: JobStatus
    current_step: str = Field(
        default="",
        description="Name of the currently executing agent/step"
    )
    progress_percent: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Estimated progress percentage"
    )
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class JobResultResponse(BaseModel):
    """Response containing the completed generation result."""
    job_id: str
    status: JobStatus
    result: Optional[VideoContentPackage] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    execution_time_seconds: Optional[float] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    llm_provider: str
    llm_model: str
    version: str = "1.0.0"
    uptime_seconds: float
