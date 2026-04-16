"""
CrewAI Crew Orchestration — assembles agents and tasks into the video content pipeline.

Execution Flow:
  Sequential: Story Writer → Script Writer → Voiceover Writer
  Then: Video Prompt + Image Prompt + Thumbnail (all receive prior context)

Raw outputs are saved to logs/ directory for inspection.
"""

import json
import os
import re
import logging
import asyncio
from datetime import datetime, timezone
from crewai import Crew, Process

from app.crew.agents import (
    create_story_writer,
    create_script_writer,
    create_voiceover_writer,
    create_video_prompt_agent,
    create_image_prompt_agent,
    create_thumbnail_agent,
)
from app.crew.tasks import (
    create_story_task,
    create_script_task,
    create_voiceover_task,
    create_video_prompt_task,
    create_image_prompt_task,
    create_thumbnail_task,
)
from app.models import (
    GenerateRequest,
    VideoContentPackage,
    Scene,
)

logger = logging.getLogger(__name__)

# Directory to save raw outputs
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")


def _ensure_logs_dir():
    """Create logs directory if it doesn't exist."""
    os.makedirs(LOGS_DIR, exist_ok=True)


class VideoContentCrew:
    """Orchestrates the multi-agent video content generation pipeline."""

    def __init__(self, request: GenerateRequest):
        self.request = request
        self._step_callback = None

    def set_step_callback(self, callback):
        """Set a callback function that receives (step_name, progress_percent)."""
        self._step_callback = callback

    def _notify_step(self, step: str, progress: int):
        """Notify the callback about current step progress."""
        if self._step_callback:
            self._step_callback(step, progress)
        logger.info(f"Pipeline step: {step} ({progress}%)")

    def _save_raw_output(self, job_id: str, name: str, content: str):
        """Save raw agent output to a log file for inspection."""
        _ensure_logs_dir()
        job_dir = os.path.join(LOGS_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        filepath = os.path.join(job_dir, f"{name}.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Saved raw output: {filepath}")

    def run(self, job_id: str = "unknown") -> VideoContentPackage:
        """Execute the full pipeline and return structured output."""
        try:
            # --- Create all agents ---
            self._notify_step("Initializing agents", 5)

            story_agent = create_story_writer()
            script_agent = create_script_writer()
            voiceover_agent = create_voiceover_writer()
            video_prompt_agent = create_video_prompt_agent()
            image_prompt_agent = create_image_prompt_agent()
            thumbnail_agent = create_thumbnail_agent()

            # --- Create all tasks ---
            self._notify_step("Creating tasks", 10)

            additional = self.request.additional_instructions or ""

            story_task = create_story_task(
                agent=story_agent,
                user_input=self.request.user_input,
                video_type=self.request.video_type.value,
                duration=self.request.duration_seconds,
                style=self.request.style.value,
                target_audience=self.request.target_audience,
                num_scenes=self.request.num_scenes,
                language=self.request.language,
                additional_instructions=additional,
            )

            script_task = create_script_task(
                agent=script_agent,
                num_scenes=self.request.num_scenes,
                duration=self.request.duration_seconds,
                style=self.request.style.value,
            )

            voiceover_task = create_voiceover_task(
                agent=voiceover_agent,
                duration=self.request.duration_seconds,
                language=self.request.language,
            )

            video_prompt_task = create_video_prompt_task(
                agent=video_prompt_agent,
                style=self.request.style.value,
            )

            image_prompt_task = create_image_prompt_task(
                agent=image_prompt_agent,
                style=self.request.style.value,
            )

            thumbnail_task = create_thumbnail_task(
                agent=thumbnail_agent,
                style=self.request.style.value,
            )

            # --- Set task dependencies (context) ---
            script_task.context = [story_task]
            voiceover_task.context = [story_task, script_task]
            video_prompt_task.context = [script_task, voiceover_task]
            image_prompt_task.context = [script_task, voiceover_task]
            thumbnail_task.context = [story_task, script_task]

            # --- Assemble the crew ---
            self._notify_step("Starting Story Writer", 15)

            # Store tasks in order for output retrieval
            all_tasks = [
                story_task, script_task, voiceover_task,
                video_prompt_task, image_prompt_task, thumbnail_task,
            ]
            task_names = [
                "story", "script", "voiceover",
                "video_prompts", "image_prompts", "thumbnail",
            ]

            crew = Crew(
                agents=[
                    story_agent, script_agent, voiceover_agent,
                    video_prompt_agent, image_prompt_agent, thumbnail_agent,
                ],
                tasks=all_tasks,
                process=Process.sequential,
                verbose=True,
            )

            self._notify_step("Running pipeline — Story Writer", 20)

            # --- Execute ---
            result = crew.kickoff()

            self._notify_step("Parsing results", 90)

            # --- Save ALL raw outputs ---
            result_str = str(result) if result else ""
            self._save_raw_output(job_id, "00_final_result", result_str)

            # Extract and clean individual task outputs
            task_outputs = {}
            for i, (task, name) in enumerate(zip(all_tasks, task_names)):
                raw = ""
                if hasattr(task, "output") and task.output:
                    raw = str(task.output)
                # Save raw version
                self._save_raw_output(job_id, f"{i+1:02d}_{name}_raw", raw)
                # Extract the actual result content from the wrapper string
                cleaned = self._extract_result_content(raw)
                task_outputs[name] = cleaned
                # Save cleaned version
                self._save_raw_output(job_id, f"{i+1:02d}_{name}_cleaned", cleaned)

            # Fallback: if no individual outputs, use combined result
            if not any(task_outputs.values()):
                logger.warning("No individual task outputs found, using combined result")
                cleaned_result = self._extract_result_content(result_str)
                task_outputs["thumbnail"] = cleaned_result

            # --- Parse into structured format ---
            package = self._parse_crew_output(task_outputs)

            # --- Generate videos via ComfyUI (if URL provided) ---
            if self.request.comfyui_url:
                self._notify_step("Generating videos via ComfyUI", 92)
                try:
                    package = self._generate_videos(package, job_id)
                except Exception as e:
                    logger.warning(
                        f"ComfyUI video generation failed (returning prompts only): {e}"
                    )
                    # Don't crash — still return the prompts package

            self._notify_step("Completed", 100)
            return package

        except Exception as e:
            logger.error(f"Pipeline failed: {str(e)}", exc_info=True)
            raise

    def _generate_videos(self, package: VideoContentPackage, job_id: str) -> VideoContentPackage:
        """Send each scene's video prompt to ComfyUI for video generation."""
        from app.comfyui_client import ComfyUIClient

        comfyui_url = self.request.comfyui_url
        logger.info(f"Starting ComfyUI video generation: {comfyui_url}")

        client = ComfyUIClient(base_url=comfyui_url, timeout=900)

        # Check ComfyUI health
        is_healthy = asyncio.run(client.check_health())
        if not is_healthy:
            logger.error(f"ComfyUI server not reachable at {comfyui_url}")
            raise ConnectionError(f"Cannot connect to ComfyUI at {comfyui_url}")

        video_urls = []
        total_scenes = len(package.scenes)

        for i, scene in enumerate(package.scenes):
            scene_progress = 92 + int((i / total_scenes) * 7)  # 92-99%
            self._notify_step(
                f"Generating video — Scene {scene.scene_number}/{total_scenes}",
                scene_progress,
            )

            try:
                # Cap scene duration for ComfyUI (max ~4.8s at 25fps/121 frames)
                duration = min(scene.duration_seconds, 4)

                result = asyncio.run(
                    client.generate_scene_video(
                        prompt=scene.video_prompt,
                        negative_prompt=scene.negative_prompt,
                        duration_seconds=duration,
                        job_id=job_id,
                        scene_number=scene.scene_number,
                    )
                )

                if result.get("video_url"):
                    scene.video_url = result["video_url"]
                    scene.video_local_path = result.get("local_path")
                    video_urls.append(result["video_url"])
                    logger.info(
                        f"Scene {scene.scene_number} video generated: {result['video_url']}"
                    )
                else:
                    logger.warning(f"Scene {scene.scene_number}: No video URL returned")

            except Exception as e:
                logger.error(
                    f"Scene {scene.scene_number} video generation failed: {e}",
                    exc_info=True,
                )
                # Continue with other scenes — don't fail the entire pipeline
                continue

        package.video_urls = video_urls
        logger.info(f"Video generation complete: {len(video_urls)}/{total_scenes} videos")
        return package

    def _parse_crew_output(self, task_outputs: dict) -> VideoContentPackage:
        """Parse raw agent text outputs into structured VideoContentPackage."""

        # --- Parse story ---
        story_raw = task_outputs.get("story", "")
        title = (
            self._extract_field(story_raw, "TITLE")
            or self._extract_field(story_raw, "Title")
            or self._extract_between_markers(story_raw, "**Title:**", "\n")
            or self._extract_between_markers(story_raw, "# ", "\n")
            or f"Video — {self.request.user_input[:60]}"
        )
        # Clean markdown bold from title
        title = re.sub(r"\*\*", "", title).strip()

        genre = (
            self._extract_field(story_raw, "GENRE")
            or self._extract_field(story_raw, "Genre")
            or self._extract_between_markers(story_raw, "**Genre:**", "\n")
            or self.request.video_type.value
        )
        genre = re.sub(r"\*\*", "", genre).strip()

        summary = (
            self._extract_field(story_raw, "SUMMARY")
            or self._extract_field(story_raw, "Summary")
            or self._extract_between_markers(story_raw, "**Summary:**", "\n\n")
            or ""
        )
        summary = re.sub(r"\*\*", "", summary).strip()

        music_mood = (
            self._extract_field(story_raw, "MUSIC_MOOD")
            or self._extract_field(story_raw, "Music Mood")
            or self._extract_field(story_raw, "Music")
            or self._extract_between_markers(story_raw, "**Music", "\n")
            or ""
        )

        color_palette_str = (
            self._extract_field(story_raw, "COLOR_PALETTE")
            or self._extract_field(story_raw, "Color Palette")
            or self._extract_field(story_raw, "Color")
            or self._extract_between_markers(story_raw, "**Color", "\n")
            or ""
        )

        # Extract story body - try multiple patterns
        full_story = (
            self._extract_section(story_raw, "STORY")
            or self._extract_section(story_raw, "Story")
            or self._extract_after_header(story_raw, "## Story")
            or self._extract_after_header(story_raw, "# Story")
            or story_raw  # fallback: use entire output
        )

        # --- Parse script + voiceover + prompts ---
        script_raw = task_outputs.get("script", "")
        voiceover_raw = task_outputs.get("voiceover", "")
        video_prompts_raw = task_outputs.get("video_prompts", "")
        image_prompts_raw = task_outputs.get("image_prompts", "")
        thumbnail_raw = task_outputs.get("thumbnail", "")

        # Build scenes
        scenes = self._parse_scenes(
            script_raw=script_raw,
            voiceover_raw=voiceover_raw,
            video_prompts_raw=video_prompts_raw,
            image_prompts_raw=image_prompts_raw,
            num_scenes=self.request.num_scenes,
        )

        # --- Parse thumbnail ---
        thumbnail_prompt = (
            self._extract_field(thumbnail_raw, "THUMBNAIL PROMPT")
            or self._extract_field(thumbnail_raw, "Thumbnail Prompt")
            or self._extract_field(thumbnail_raw, "POSITIVE")
            or self._extract_between_markers(thumbnail_raw, "**Thumbnail Prompt:**", "\n\n")
            or ""
        )
        thumbnail_neg = (
            self._extract_field(thumbnail_raw, "NEGATIVE PROMPT")
            or self._extract_field(thumbnail_raw, "Negative Prompt")
            or self._extract_field(thumbnail_raw, "NEGATIVE")
            or "blurry, low quality, text, watermark, generic"
        )
        thumbnail_desc = (
            self._extract_field(thumbnail_raw, "DESCRIPTION")
            or self._extract_field(thumbnail_raw, "Description")
            or self._extract_between_markers(thumbnail_raw, "**Description:**", "\n")
            or ""
        )
        thumbnail_text = (
            self._extract_field(thumbnail_raw, "TEXT_OVERLAY")
            or self._extract_field(thumbnail_raw, "Text Overlay")
            or self._extract_field(thumbnail_raw, "TEXT OVERLAY")
            or ""
        )
        if thumbnail_text.upper() == "NONE":
            thumbnail_text = ""

        # Calculate total duration
        total_duration = sum(s.duration_seconds for s in scenes) if scenes else self.request.duration_seconds

        seo_title = f"{title} | {genre.title()} Video"
        seo_description = summary[:160] if summary else f"Watch {title} — {genre}"
        tags = self._generate_tags(title, genre, self.request.user_input)

        return VideoContentPackage(
            title=title,
            story_summary=summary,
            full_story=full_story,
            genre=genre,
            target_audience=self.request.target_audience,
            total_duration_seconds=total_duration,
            scenes=scenes,
            thumbnail_prompt=thumbnail_prompt,
            thumbnail_negative_prompt=thumbnail_neg,
            thumbnail_description=thumbnail_desc,
            thumbnail_text_overlay=thumbnail_text,
            tags=tags,
            seo_title=seo_title,
            seo_description=seo_description,
            music_suggestion=music_mood,
            color_palette=[c.strip() for c in color_palette_str.split(",") if c.strip()][:5],
        )

    def _parse_scenes(self, script_raw: str, voiceover_raw: str,
                      video_prompts_raw: str, image_prompts_raw: str,
                      num_scenes: int) -> list[Scene]:
        """Parse all agent outputs and merge them into Scene objects."""
        scenes = []

        for i in range(1, num_scenes + 1):
            # --- Script parsing (multiple format attempts) ---
            scene_block = self._extract_scene_block(script_raw, i)

            scene_title = (
                self._extract_field(scene_block, "TITLE")
                or self._extract_field(scene_block, "Title")
                or self._extract_field(scene_block, "Scene Title")
                or self._extract_between_markers(scene_block, "**Title:**", "\n")
                or self._extract_between_markers(scene_block, f"**Scene {i}:", "**")
                or f"Scene {i}"
            )
            scene_title = re.sub(r"\*\*", "", scene_title).strip()

            duration_str = (
                self._extract_field(scene_block, "DURATION")
                or self._extract_field(scene_block, "Duration")
                or self._extract_between_markers(scene_block, "**Duration:**", "\n")
                or "20"
            )
            duration = self._parse_int(duration_str, default=20)

            description = (
                self._extract_field(scene_block, "DESCRIPTION")
                or self._extract_field(scene_block, "Description")
                or self._extract_field(scene_block, "Visual Description")
                or self._extract_between_markers(scene_block, "**Description:**", "\n\n")
                or self._extract_between_markers(scene_block, "**Visual Description:**", "\n\n")
                or scene_block[:500] if scene_block else ""
            )
            description = re.sub(r"\*\*", "", description).strip()

            camera = (
                self._extract_field(scene_block, "CAMERA")
                or self._extract_field(scene_block, "Camera")
                or self._extract_field(scene_block, "Camera Movement")
                or self._extract_between_markers(scene_block, "**Camera:**", "\n")
                or self._extract_between_markers(scene_block, "**Camera Movement:**", "\n")
                or "static"
            )
            camera = re.sub(r"\*\*", "", camera).strip()

            mood = (
                self._extract_field(scene_block, "MOOD")
                or self._extract_field(scene_block, "Mood")
                or self._extract_between_markers(scene_block, "**Mood:**", "\n")
                or "neutral"
            )
            mood = re.sub(r"\*\*", "", mood).strip()

            transition = (
                self._extract_field(scene_block, "TRANSITION")
                or self._extract_field(scene_block, "Transition")
                or self._extract_between_markers(scene_block, "**Transition:**", "\n")
                or "fade"
            )
            transition = re.sub(r"\*\*", "", transition).strip()

            # --- Voiceover parsing ---
            voiceover_text = self._extract_voiceover(voiceover_raw, i)

            # --- Video prompt parsing ---
            video_block = self._extract_scene_block(video_prompts_raw, i, prefix="SCENE")
            video_prompt = (
                self._extract_field(video_block, "POSITIVE")
                or self._extract_field(video_block, "Positive")
                or self._extract_field(video_block, "Video Prompt")
                or self._extract_field(video_block, "VIDEO PROMPT")
                or self._extract_between_markers(video_block, "**POSITIVE:**", "\n\n")
                or self._extract_between_markers(video_block, "**Positive:**", "\n\n")
                or description
            )
            video_negative = (
                self._extract_field(video_block, "NEGATIVE")
                or self._extract_field(video_block, "Negative")
                or self._extract_field(video_block, "Negative Prompt")
                or "blurry, low quality, distorted, deformed, watermark, text"
            )

            # --- Image prompt parsing ---
            image_block = self._extract_scene_block(image_prompts_raw, i, prefix="SCENE")
            image_prompt = (
                self._extract_field(image_block, "POSITIVE")
                or self._extract_field(image_block, "Positive")
                or self._extract_field(image_block, "Image Prompt")
                or self._extract_field(image_block, "IMAGE PROMPT")
                or self._extract_between_markers(image_block, "**POSITIVE:**", "\n\n")
                or self._extract_between_markers(image_block, "**Positive:**", "\n\n")
                or description
            )
            image_negative = (
                self._extract_field(image_block, "NEGATIVE")
                or self._extract_field(image_block, "Negative")
                or self._extract_field(image_block, "Negative Prompt")
                or "worst quality, low quality, blurry, watermark"
            )

            scenes.append(Scene(
                scene_number=i,
                scene_title=scene_title,
                description=description,
                duration_seconds=duration,
                voiceover_text=voiceover_text,
                video_prompt=video_prompt,
                image_prompt=image_prompt,
                negative_prompt=f"{video_negative}, {image_negative}",
                camera_movement=camera,
                visual_style=self.request.style.value,
                mood=mood,
                transition=transition,
            ))

        return scenes

    # ================================================================
    # Parsing Utilities — multiple strategies for flexible extraction
    # ================================================================

    @staticmethod
    def _extract_result_content(raw: str) -> str:
        """Extract the actual content from CrewAI 0.5.0 task output wrapper.

        The raw output looks like:
          description='...' summary='...' result='THE ACTUAL CONTENT HERE'

        We need to extract just the result='...' part and unescape it.
        """
        if not raw:
            return ""

        # Try to extract the result='...' portion
        # Match result=' followed by content up to the closing '
        match = re.search(r"result='(.*)'\s*$", raw, re.DOTALL)
        if match:
            content = match.group(1)
        else:
            # Fallback: maybe it's just plain text without wrapper
            content = raw

        # Unescape: replace literal \n with actual newlines
        content = content.replace("\\n", "\n")
        # Remove escaped single quotes
        content = content.replace("\\'", "'")
        # Clean up any remaining escape artifacts
        content = content.replace("\\\\", "\\")

        return content.strip()

    @staticmethod
    def _extract_field(text: str, field_name: str) -> str:
        """Extract 'FIELD_NAME: value' or '**Field Name:** value' patterns."""
        if not text:
            return ""
        # Pattern 1: FIELD_NAME: value (plain text)
        pattern1 = rf"(?:^|\n)\s*{re.escape(field_name)}\s*:\s*(.+?)(?:\n|$)"
        match = re.search(pattern1, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Pattern 2: **Field Name:** value (markdown bold)
        pattern2 = rf"\*\*{re.escape(field_name)}\s*:\*\*\s*(.+?)(?:\n|$)"
        match = re.search(pattern2, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Pattern 3: **Field Name**: value (markdown bold variant)
        pattern3 = rf"\*\*{re.escape(field_name)}\*\*\s*:\s*(.+?)(?:\n|$)"
        match = re.search(pattern3, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_between_markers(text: str, start: str, end: str) -> str:
        """Extract text between two marker strings."""
        if not text:
            return ""
        idx_start = text.lower().find(start.lower())
        if idx_start == -1:
            return ""
        idx_start += len(start)
        idx_end = text.find(end, idx_start)
        if idx_end == -1:
            # Take up to 500 chars if no end marker found
            return text[idx_start:idx_start + 500].strip()
        return text[idx_start:idx_end].strip()

    @staticmethod
    def _extract_section(text: str, section_name: str) -> str:
        """Extract a multi-line section following 'SECTION_NAME:'."""
        if not text:
            return ""
        # Try plain text format
        pattern = rf"(?:^|\n)\s*{re.escape(section_name)}\s*:\s*\n([\s\S]+?)(?:\n\s*[A-Z_]{{2,}}\s*:|$)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Fallback: everything after the section name
        parts = re.split(rf"{re.escape(section_name)}\s*:", text, flags=re.IGNORECASE)
        if len(parts) > 1:
            return parts[1].strip()
        return ""

    @staticmethod
    def _extract_after_header(text: str, header: str) -> str:
        """Extract content after a markdown header like '## Story'."""
        if not text:
            return ""
        # Find the header
        pattern = rf"(?:^|\n){re.escape(header)}\s*\n([\s\S]+?)(?:\n#|\Z)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_scene_block(text: str, scene_num: int, prefix: str = "SCENE") -> str:
        """Extract a scene block by number — handles multiple formats."""
        if not text:
            return ""
        # Pattern 1: SCENE N: or SCENE N (plain)
        pattern1 = rf"{prefix}\s*{scene_num}\s*[:\-]?\s*([\s\S]*?)(?={prefix}\s*{scene_num + 1}\s*[:\-]?|$)"
        match = re.search(pattern1, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Pattern 2: ### Scene N or ## Scene N (markdown headers)
        pattern2 = rf"#{1,3}\s*Scene\s*{scene_num}\s*[:\-]?\s*([\s\S]*?)(?=#{1,3}\s*Scene\s*{scene_num + 1}|$)"
        match = re.search(pattern2, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Pattern 3: **Scene N** (markdown bold)
        pattern3 = rf"\*\*Scene\s*{scene_num}[:\-]?\*\*\s*([\s\S]*?)(?=\*\*Scene\s*{scene_num + 1}|$)"
        match = re.search(pattern3, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Pattern 4: Numbered list "1." or "1)"
        pattern4 = rf"(?:^|\n)\s*{scene_num}\s*[\.\)]\s*([\s\S]*?)(?=\n\s*{scene_num + 1}\s*[\.\)]|$)"
        match = re.search(pattern4, text)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_voiceover(text: str, scene_num: int) -> str:
        """Extract voiceover text for a specific scene number."""
        if not text:
            return ""
        # Pattern 1: SCENE N VOICEOVER:
        pattern1 = rf"SCENE\s*{scene_num}\s*VOICEOVER\s*:\s*([\s\S]*?)(?=SCENE\s*{scene_num + 1}\s*VOICEOVER|$)"
        match = re.search(pattern1, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Pattern 2: Use scene block extraction
        block = VideoContentCrew._extract_scene_block(text, scene_num, prefix="SCENE")
        if block:
            cleaned = re.sub(r"^(?:VOICEOVER|Voiceover)\s*:\s*", "", block, flags=re.IGNORECASE)
            return cleaned.strip()
        return ""

    @staticmethod
    def _parse_int(value: str, default: int = 0) -> int:
        """Safely parse an integer from a string."""
        try:
            match = re.search(r"\d+", value)
            if match:
                return int(match.group())
            return default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _generate_tags(title: str, genre: str, user_input: str) -> list[str]:
        """Generate basic tags from available metadata."""
        tags = set()
        tags.add(genre.lower().strip())
        for text in [title, user_input]:
            words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
            for word in words:
                if word not in {"the", "and", "for", "with", "about", "that", "this", "from", "into"}:
                    tags.add(word)
                if len(tags) >= 15:
                    break
        return list(tags)[:15]
