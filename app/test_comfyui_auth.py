"""
Test script to figure out the correct ComfyUI API wrapper auth.
Run: python3 app/test_comfyui_auth.py

Update the CONFIG below with your current Vast.ai instance details.
"""
import requests
import json

# ── UPDATE THESE WITH YOUR CURRENT INSTANCE ──
API_WRAPPER_URL = "http://108.255.76.60:52224"   # from n8n: api_wrapper_url
COMFYUI_URL     = "http://108.255.76.60:52275"   # from n8n: comfyui_url
TOKEN           = "18371a221d28e5932cdab0c9011e38540fcfdae43349cfe97e592c29841b4e3c"  # from n8n: token

# Simple test workflow (just a prompt, won't actually generate — just tests auth)
test_workflow = {
    "267:266": {
        "inputs": {"value": "test prompt"},
        "class_type": "PrimitiveStringMultiline",
        "_meta": {"title": "Prompt"}
    }
}

payload = {
    "input": {
        "request_id": "auth-test-001",
        "workflow_json": test_workflow,
        "s3": {"access_key_id": "", "secret_access_key": "", "endpoint_url": "", "bucket_name": "", "region": ""},
        "webhook": {"url": "", "extra_params": {}}
    }
}

print("=" * 60)
print("Testing ComfyUI API Wrapper Authentication")
print("=" * 60)

# ── Test 1: API Wrapper /queue-info with token param ──
print("\n[Test 1] GET /queue-info?token=TOKEN")
try:
    r = requests.get(f"{API_WRAPPER_URL}/queue-info", params={"token": TOKEN}, timeout=10, allow_redirects=False)
    print(f"  Status: {r.status_code}")
    print(f"  Headers: {dict(r.headers)}")
    if r.status_code == 302:
        print(f"  Redirect to: {r.headers.get('location')}")
except Exception as e:
    print(f"  Error: {e}")

# ── Test 2: API Wrapper /queue-info with Bearer header ──
print("\n[Test 2] GET /queue-info with Bearer header")
try:
    r = requests.get(f"{API_WRAPPER_URL}/queue-info", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10, allow_redirects=False)
    print(f"  Status: {r.status_code}")
    if r.status_code == 302:
        print(f"  Redirect to: {r.headers.get('location')}")
except Exception as e:
    print(f"  Error: {e}")

# ── Test 3: API Wrapper /generate/sync with token param (no redirect) ──
print("\n[Test 3] POST /generate/sync?token=TOKEN (no redirect)")
try:
    r = requests.post(f"{API_WRAPPER_URL}/generate/sync", params={"token": TOKEN}, json=payload, timeout=10, allow_redirects=False)
    print(f"  Status: {r.status_code}")
    if r.status_code == 302:
        print(f"  Redirect to: {r.headers.get('location')}")
    else:
        print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")

# ── Test 4: Follow the redirect manually as POST ──
print("\n[Test 4] POST /generate/sync → follow redirect as POST")
try:
    r = requests.post(f"{API_WRAPPER_URL}/generate/sync", params={"token": TOKEN}, json=payload, timeout=10, allow_redirects=False)
    if r.status_code in (301, 302, 307, 308):
        redirect_url = r.headers.get("location", "")
        print(f"  Got redirect to: {redirect_url}")
        # Make it absolute if relative
        if redirect_url.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(API_WRAPPER_URL)
            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
        print(f"  Following as POST to: {redirect_url}")
        r2 = requests.post(redirect_url, json=payload, timeout=30)
        print(f"  Status: {r2.status_code}")
        print(f"  Body: {r2.text[:300]}")
    else:
        print(f"  Status: {r.status_code}")
        print(f"  Body: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {e}")

# ── Test 5: Direct ComfyUI /system_stats ──
print("\n[Test 5] GET ComfyUI /system_stats (no auth)")
try:
    r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=10)
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")

# ── Test 6: Direct ComfyUI /system_stats with token ──
print("\n[Test 6] GET ComfyUI /system_stats?token=TOKEN")
try:
    r = requests.get(f"{COMFYUI_URL}/system_stats", params={"token": TOKEN}, timeout=10)
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")

# ── Test 7: Direct ComfyUI /prompt with token ──
print("\n[Test 7] POST ComfyUI /prompt?token=TOKEN")
try:
    comfy_payload = {"prompt": test_workflow, "client_id": "test-123"}
    r = requests.post(f"{COMFYUI_URL}/prompt", params={"token": TOKEN}, json=comfy_payload, timeout=10)
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n" + "=" * 60)
print("Copy the results and share them!")
print("=" * 60)
