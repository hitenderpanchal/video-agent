"""
Test ComfyUI via Vast.ai API Wrapper — following official Vast.ai docs.

Auth: Authorization: Bearer <OPEN_BUTTON_TOKEN> header
Endpoint: POST /generate/sync
Payload: { "request_id": "...", "workflow_json": {...} }

UPDATE the 3 config values below with your current Vast.ai instance.
Run: pip install requests && python3 test_vastai_comfyui.py
"""
import requests
import json
import time

# ══════════════════════════════════════════════════════════
# UPDATE THESE WITH YOUR CURRENT VAST.AI INSTANCE
# ══════════════════════════════════════════════════════════
API_WRAPPER_URL = "http://108.255.76.60:63100"   # api_wrapper_url from n8n
COMFYUI_URL     = "http://108.255.76.60:63204"   # comfyui_url from n8n
TOKEN           = "4d6e2d37cca34bae7e4871f425cbb448f713892e2b0864c6947f8f5e783db1ea"  # token from n8n

# Auth header per Vast.ai docs
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# LTX 2.3 test workflow — short 2-sec video
# (Loads the real workflow file if available, otherwise uses a minimal test)
import os
workflow_path = os.path.join(os.path.dirname(__file__), "app", "video_ltx2_3_t2v-2.json")
if not os.path.exists(workflow_path):
    workflow_path = os.path.join(os.path.dirname(__file__), "video_ltx2_3_t2v-2.json")

if os.path.exists(workflow_path):
    with open(workflow_path) as f:
        WORKFLOW = json.load(f)
    # Inject test prompt
    WORKFLOW["267:266"]["inputs"]["value"] = "A calm ocean wave rolling onto a sandy beach at golden hour, cinematic, 4K"
    WORKFLOW["267:225"]["inputs"]["value"] = 25  # 1 second at 25fps
    print(f"✅ Loaded workflow from {workflow_path}")
else:
    print(f"⚠️  Workflow file not found, using minimal test")
    WORKFLOW = {}


print("=" * 60)
print("Vast.ai ComfyUI API Wrapper Test")
print("=" * 60)

# ══════════════════════════════════════════════════════════
# Test 1: Health check via API wrapper with Bearer token
# ══════════════════════════════════════════════════════════
print("\n[Test 1] GET API Wrapper /queue-info (Bearer header)")
try:
    r = requests.get(f"{API_WRAPPER_URL}/queue-info", headers=HEADERS, timeout=10)
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")

# ══════════════════════════════════════════════════════════
# Test 2: Health check via ComfyUI with Bearer token
# ══════════════════════════════════════════════════════════
print("\n[Test 2] GET ComfyUI /system_stats (Bearer header)")
try:
    r = requests.get(f"{COMFYUI_URL}/system_stats", headers=HEADERS, timeout=10)
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")

# ══════════════════════════════════════════════════════════
# Test 3: POST /generate/sync — Vast.ai docs (flat payload)
# ══════════════════════════════════════════════════════════
print("\n[Test 3] POST API Wrapper /generate/sync (Bearer + flat payload)")
flat_payload = {
    "request_id": "test-flat-001",
    "workflow_json": WORKFLOW,
}
try:
    r = requests.post(
        f"{API_WRAPPER_URL}/generate/sync",
        headers=HEADERS,
        json=flat_payload,
        timeout=300,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:500]}")
except Exception as e:
    print(f"  Error: {e}")

# ══════════════════════════════════════════════════════════
# Test 4: POST /generate/sync — wrapped payload (like test_api-2.py)
# ══════════════════════════════════════════════════════════
print("\n[Test 4] POST API Wrapper /generate/sync (Bearer + wrapped payload)")
wrapped_payload = {
    "input": {
        "request_id": "test-wrapped-001",
        "workflow_json": WORKFLOW,
        "s3": {"access_key_id": "", "secret_access_key": "", "endpoint_url": "", "bucket_name": "", "region": ""},
        "webhook": {"url": "", "extra_params": {}},
    }
}
try:
    r = requests.post(
        f"{API_WRAPPER_URL}/generate/sync",
        headers=HEADERS,
        json=wrapped_payload,
        timeout=300,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:500]}")
except Exception as e:
    print(f"  Error: {e}")

# ══════════════════════════════════════════════════════════
# Test 5: POST directly to ComfyUI /prompt (Bearer + standard format)
# ══════════════════════════════════════════════════════════
print("\n[Test 5] POST ComfyUI /prompt (Bearer + standard ComfyUI format)")
comfy_payload = {
    "prompt": WORKFLOW,
    "client_id": "test-client-001",
}
try:
    r = requests.post(
        f"{COMFYUI_URL}/prompt",
        headers=HEADERS,
        json=comfy_payload,
        timeout=30,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:500]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n" + "=" * 60)
print("DONE — share the output above!")
print("=" * 60)
