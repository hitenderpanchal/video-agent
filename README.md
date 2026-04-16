# AI Video Content Agent Pipeline

A multi-agent AI system that transforms a user's idea into a complete video production package using CrewAI, FastAPI, and DeepSeek/Ollama.

## What It Does

Takes a simple topic or idea and generates:
- 📖 **Full narrative story**
- 🎬 **Scene-by-scene script** with camera directions
- 🎙️ **Voiceover narration** per scene (TTS-ready)
- 🎥 **Video generation prompts** (ComfyUI-optimized)
- 🖼️ **Image generation prompts** (SDXL/Flux-optimized)
- 🎨 **Thumbnail prompt** (click-optimized)

## Architecture

```
n8n HTTP Request → FastAPI REST API → CrewAI Pipeline → Structured JSON
                                        │
                                        ├── Story Writer Agent
                                        ├── Script Writer Agent
                                        ├── Voiceover Writer Agent
                                        ├── Video Prompt Agent
                                        ├── Image Prompt Agent
                                        └── Thumbnail Agent
```

## Quick Start

### 1. Setup Environment

```bash
# Clone and enter directory
cd videoagent16apr

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your DEEPSEEK_API_KEY
```

### 2. Run Locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Test It

```bash
# Health check
curl http://localhost:8000/api/health

# Start a generation job
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "A story about a robot learning to paint in a post-apocalyptic world",
    "video_type": "story",
    "duration_seconds": 120,
    "style": "cinematic",
    "target_audience": "sci-fi enthusiasts 18-35",
    "num_scenes": 5
  }'

# Poll status (replace JOB_ID)
curl http://localhost:8000/api/status/JOB_ID

# Get result when complete
curl http://localhost:8000/api/result/JOB_ID
```

## Docker Deployment (AWS Ubuntu)

```bash
# Build and run
docker-compose up -d

# Check logs
docker-compose logs -f video-agent-api

# Stop
docker-compose down
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/generate` | Start content generation |
| `GET` | `/api/status/{job_id}` | Poll job status |
| `GET` | `/api/result/{job_id}` | Get completed result |
| `GET` | `/api/jobs` | List recent jobs |
| `GET` | `/api/health` | Health check |
| `GET` | `/docs` | Interactive API docs (Swagger) |

## n8n Integration

1. **HTTP Request Node** → `POST /api/generate` with user input
2. **Wait Node** → 10 second delay
3. **HTTP Request Node** → `GET /api/status/{job_id}`
4. **IF Node** → Check if `status == "completed"`
5. **Loop back** to step 2 if not completed
6. **HTTP Request Node** → `GET /api/result/{job_id}`
7. **Parse JSON** → Route to ComfyUI / Supabase

## Switching LLM Providers

### DeepSeek (default)
```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-key
DEEPSEEK_MODEL=deepseek-chat
```

### Ollama (Vast.ai instance)
```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://your-vastai-ip:11434/v1
OLLAMA_MODEL=gemma3:27b
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `deepseek` | `deepseek` or `ollama` |
| `DEEPSEEK_API_KEY` | — | Your DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | `deepseek-chat` or `deepseek-reasoner` |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `OLLAMA_MODEL` | `gemma3:27b` | Ollama model name |
| `API_PORT` | `8000` | Server port |
| `CREATIVE_TEMPERATURE` | `0.8` | Temperature for story/script agents |
| `STRUCTURED_TEMPERATURE` | `0.4` | Temperature for prompt agents |
