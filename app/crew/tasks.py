"""
CrewAI Task Definitions — defines what each agent does and how they chain together.

Task Pipeline:
  1. Story Task → receives user input
  2. Script Task → receives story output
  3. Voiceover Task → receives script output
  4. Video Prompt Task → receives script + voiceover
  5. Image Prompt Task → receives script + voiceover
  6. Thumbnail Task → receives story + script
"""

from crewai import Task, Agent


def create_story_task(agent: Agent, user_input: str, video_type: str,
                      duration: int, style: str, target_audience: str,
                      num_scenes: int, language: str,
                      additional_instructions: str = "") -> Task:
    """Task 1: Generate the full narrative story."""
    return Task(
        description=f"""Create a compelling narrative story based on the following input:

**User's Idea:** {user_input}

**Video Type:** {video_type}
**Target Duration:** {duration} seconds
**Visual Style:** {style}
**Target Audience:** {target_audience}
**Number of Scenes:** {num_scenes}
**Language:** {language}
{f"**Additional Instructions:** {additional_instructions}" if additional_instructions else ""}

Your task:
1. Transform this idea into a rich, engaging narrative story
2. The story should be vivid and cinematic — every paragraph should paint a visual scene
3. Structure it with a clear hook, rising action, climax, and resolution
4. Make it appropriate for the target audience
5. The story should naturally divide into approximately {num_scenes} distinct visual scenes
6. Total duration when narrated should be approximately {duration} seconds (~{int(duration * 2.5)} words)

Provide your output in this exact format:

TITLE: [Catchy video title]
GENRE: [Genre classification]
SUMMARY: [2-3 sentence summary]
MUSIC_MOOD: [Background music mood suggestion]
COLOR_PALETTE: [Color mood - e.g., warm earth tones, cold blues, neon cyberpunk]

STORY:
[The complete narrative story - 800-2000 words]""",
        expected_output=(
            "A complete creative package including: a compelling title, genre, "
            "2-3 sentence summary, music mood suggestion, color palette mood, "
            "and a full narrative story (800-2000 words) that is vivid, visual, "
            "and perfectly structured for video adaptation."
        ),
        agent=agent,
    )


def create_script_task(agent: Agent, num_scenes: int, duration: int,
                       style: str) -> Task:
    """Task 2: Break the story into a scene-by-scene script."""
    return Task(
        description=f"""Take the story from the Story Writer and break it into exactly {num_scenes} distinct scenes.

**Target Total Duration:** {duration} seconds
**Visual Style:** {style}

For EACH scene, provide:

SCENE [number]:
TITLE: [3-5 word scene title]
DURATION: [seconds]
DESCRIPTION: [Detailed visual description - what the viewer SEES. Include setting, subjects, actions, lighting, key objects. Be specific enough for AI image/video generation. 50-100 words.]
CAMERA: [Camera movement - e.g., slow zoom in, pan left, static, dolly in, tracking shot, aerial]
MOOD: [Emotional tone - e.g., tense, peaceful, awe-inspiring, mysterious]
TRANSITION: [To next scene - cut, fade, dissolve, wipe]

Rules:
- Scene durations MUST add up to approximately {duration} seconds
- Minimum scene duration: 5 seconds
- Maximum scene duration: 60 seconds  
- Every scene must be visually concrete — no abstract concepts without visual anchors
- Maintain visual consistency in style across all scenes
- Include variety in camera movements — don't use the same movement for every scene
- First scene should be a hook (5-10 seconds)
- Last scene should be a satisfying resolution""",
        expected_output=(
            f"A detailed scene-by-scene breakdown of exactly {num_scenes} scenes, "
            f"totaling approximately {duration} seconds. Each scene includes: "
            "title, duration in seconds, detailed visual description, camera movement, "
            "mood, and transition type."
        ),
        agent=agent,
    )


def create_voiceover_task(agent: Agent, duration: int, language: str) -> Task:
    """Task 3: Write voiceover narration for each scene."""
    return Task(
        description=f"""Write voiceover narration for each scene from the Script Writer's breakdown.

**Language:** {language}
**Total Duration:** {duration} seconds
**Speaking Rate:** ~150 words per minute (2.5 words per second)

For EACH scene, provide:

SCENE [number] VOICEOVER:
[The exact narration text to be spoken]

Rules:
- Match word count to scene duration (scene_duration × 2.5 = approximate word count)
- Write for the SPOKEN word — short sentences, active voice, conversational
- Use contractions naturally (it's, you'll, they've)
- Don't describe what's visually obvious — ADD meaning to the visuals
- Some scenes may have [PAUSE] or [MUSIC ONLY] instead of narration
- Include [BEAT] for half-second pauses where needed
- Vary sentence structure — don't start every sentence the same way
- Opening narration should hook the viewer immediately
- Closing narration should be memorable and impactful
- Total words across all scenes should equal ~{int(duration * 2.5)} words""",
        expected_output=(
            "Complete voiceover narration for every scene, precisely timed to match "
            "scene durations. Each scene's narration should sound natural when spoken "
            "aloud, enhance the visual experience, and include appropriate pacing markers."
        ),
        agent=agent,
    )


def create_video_prompt_task(agent: Agent, style: str) -> Task:
    """Task 4: Generate LTX Video 2.3 prompts for each scene."""
    return Task(
        description=f"""Create optimized LTX Video 2.3 prompts for each scene from the Script Writer's breakdown.

**Visual Style:** {style}
**Target Model:** LTX Video 2.3 (NOT Stable Diffusion)

For EACH scene, provide:

SCENE [number] VIDEO PROMPT:
POSITIVE: [LTX 2.3 paragraph prompt — see rules below]
NEGATIVE: [Short focused negative — max 15 words]
CAMERA: [Simple camera description]
DURATION: [seconds matching the script]

### CRITICAL: LTX 2.3 Prompt Format
Write each prompt as a **single flowing paragraph** (4-8 sentences), like a film director writing shot notes.

Weave these 6 elements into ONE natural paragraph:
1. Shot framing (wide shot, close-up, tracking shot)
2. Scene environment (lighting, textures, colors, atmosphere)
3. Subject details (age, clothing, features — describe emotions PHYSICALLY)
4. Action in present tense ("she reaches forward", "the light flickers")
5. Camera movement ("the camera pushes in slowly", "a handheld shot follows")
6. Audio/ambient sound ("rain taps on metal", "distant laughter")

### ABSOLUTE RULES:
- Write in PRESENT TENSE always
- Use PHYSICAL descriptions for emotions ("hands trembling, eyes glistening") — NEVER abstract labels ("sad", "happy")
- ONE scene per prompt — NEVER describe montages
- NEVER use Stable Diffusion tags (masterpiece, best quality, 8k, film grain, bokeh, uhd)
- NEVER use comma-separated keyword lists
- Keep negative prompts SHORT (under 15 words): "worst quality, inconsistent motion, blurry, jittery, distorted"
- Match detail to duration: short clips = 3-4 sentences, long clips = 6-8 sentences

### GOOD example:
"A tired detective stands under a flickering street lamp in a narrow, rain-slicked alleyway after midnight. The camera performs a slow push-in toward his face as he lights a cigarette, his shoulders tense and jaw tight. Neon signs in red and blue reflect off the puddles. The audio captures rain tapping against metal and the distant wail of a siren."

### BAD example (DO NOT DO THIS):
"detective, alley, rain, night, neon lights, cinematic, masterpiece, best quality, 8k, film grain, bokeh"
""",
        expected_output=(
            "LTX Video 2.3 optimized prompts for every scene. Each prompt is a flowing "
            "natural language paragraph (4-8 sentences, 40-120 words) describing shot, "
            "environment, subject, action, camera, and audio. Negative prompts are short "
            "(under 15 words). No Stable Diffusion tags or keyword lists."
        ),
        agent=agent,
    )


def create_image_prompt_task(agent: Agent, style: str) -> Task:
    """Task 5: Generate ComfyUI image prompts for each scene."""
    return Task(
        description=f"""Create optimized ComfyUI image generation prompts for each scene.

**Visual Style:** {style}

For EACH scene, provide:

SCENE [number] IMAGE PROMPT:
POSITIVE: [Optimized image prompt - 60-150 words, comma-separated descriptors]
NEGATIVE: [Scene-specific negative prompt]  
ASPECT_RATIO: 16:9
STEPS: [30-50 recommended]
GUIDANCE_SCALE: [7-12 recommended]

Prompt Structure (in this order):
1. Main subject + pose/action
2. Setting/background
3. Lighting conditions
4. Composition/framing (close-up, wide shot, etc.)
5. Style references matching "{style}"
6. Quality tags: masterpiece, best quality, highly detailed, sharp focus, 8k uhd

Rules:
- EVERY prompt must include quality boosters
- Front-load the subject description
- Specify exact composition (close-up, medium shot, wide angle, etc.)
- Define lighting explicitly
- Maintain character consistency — use identical descriptors for recurring subjects
- Use the SAME style tags across all scenes for visual cohesion
- Negative prompts should prevent common image issues (bad anatomy, watermarks, etc.)
- All images should be in 16:9 aspect ratio for video frames""",
        expected_output=(
            "ComfyUI-optimized image generation prompts for every scene. Each includes: "
            "positive prompt (60-150 words), negative prompt, aspect ratio, steps, and "
            "guidance scale. Visual consistency is maintained across all scenes through "
            "consistent style tags and character descriptions."
        ),
        agent=agent,
    )


def create_thumbnail_task(agent: Agent, style: str) -> Task:
    """Task 6: Generate the thumbnail prompt."""
    return Task(
        description=f"""Design an irresistible YouTube thumbnail for this video.

**Visual Style:** {style}

Review the story summary and script, then create a single thumbnail that will maximize click-through rate.

Provide your output in this exact format:

THUMBNAIL PROMPT: [Optimized image generation prompt - 80-150 words]
NEGATIVE PROMPT: [Negative prompt for thumbnail]
DESCRIPTION: [What the thumbnail shows, in plain English]
TEXT_OVERLAY: [2-5 words to overlay on the thumbnail - or "NONE" if no text needed]
TEXT_PLACEMENT: [top-left, top-center, top-right, bottom-left, bottom-center, bottom-right, center]
DOMINANT_COLORS: [2-3 dominant colors and why they work]

Rules:
- ONE clear focal point — not cluttered
- High contrast for mobile visibility
- Should work at both large and tiny (160x90px) sizes
- Create curiosity gap — viewer needs to click to find out more
- Use dramatic lighting for visual impact
- No text in the AI-generated image — text will be overlaid separately
- Design for both light and dark YouTube interfaces
- The thumbnail should complement (not repeat) the video title""",
        expected_output=(
            "A complete thumbnail design package including: optimized generation prompt "
            "(80-150 words), negative prompt, plain English description, text overlay "
            "suggestion, text placement, and color rationale."
        ),
        agent=agent,
    )
