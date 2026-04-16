import requests
import json

# ── Config ────────────────────────────────────────────
BASE_URL = "https://transactions-onto-sacred-promotion.trycloudflare.com"
TOKEN    = "4d5ed2b1663cb1a9863220ae713f5e40a0910d86f96acec935c5055e6a049bd8"

COMFYUI_URL = "http://76.71.171.224:46922"  # direct IP for image download

# ── Your Workflow (already loaded) ────────────────────
workflow = {
  "3": {
    "inputs": {
      "seed": 61133573315493,
      "steps": 20,
      "cfg": 8,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1,
      "model": ["4", 0],
      "positive": ["6", 0],
      "negative": ["7", 0],
      "latent_image": ["5", 0]
    },
    "class_type": "KSampler"
  },
  "4": {
    "inputs": {
      "ckpt_name": "v1-5-pruned-emaonly-fp16.safetensors"
    },
    "class_type": "CheckpointLoaderSimple"
  },
  "5": {
    "inputs": {
      "width": 512,
      "height": 512,
      "batch_size": 1
    },
    "class_type": "EmptyLatentImage"
  },
  "6": {
    "inputs": {
      "text": "beautiful scenery nature glass bottle landscape, purple galaxy bottle",
      "clip": ["4", 1]
    },
    "class_type": "CLIPTextEncode"
  },
  "7": {
    "inputs": {
      "text": "text, watermark",
      "clip": ["4", 1]
    },
    "class_type": "CLIPTextEncode"
  },
  "8": {
    "inputs": {
      "samples": ["3", 0],
      "vae": ["4", 2]
    },
    "class_type": "VAEDecode"
  },
  "9": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images": ["8", 0]
    },
    "class_type": "SaveImage"
  }
}

# ── Build Payload ─────────────────────────────────────
payload = {
    "input": {
        "request_id": "test-001",
        "workflow_json": workflow,
        "s3": {
            "access_key_id": "",
            "secret_access_key": "",
            "endpoint_url": "",
            "bucket_name": "",
            "region": ""
        },
        "webhook": {
            "url": "",
            "extra_params": {}
        }
    }
}

# ── Send Request ──────────────────────────────────────
print("=" * 50)
print("Sending request to API Wrapper...")
print("Waiting for image to generate...")
print("=" * 50)

try:
    response = requests.post(
        f"{BASE_URL}/generate/sync",
        params={"token": TOKEN},
        json=payload,
        timeout=300
    )

    result = response.json()

    print("\nRaw Response:")
    print(json.dumps(result, indent=2))

    # ── Try to download the image ─────────────────────
    print("\n" + "=" * 50)

    # Look for filename in response output
    output = result.get("output", [])
    comfyui_resp = result.get("comfyui_response", {})

    # Try to find image filename from comfyui_response
    filename = None
    try:
        node_9 = comfyui_resp.get("9", {})
        images = node_9.get("images", [])
        if images:
            filename = images[0].get("filename")
    except:
        pass

    if filename:
        print(f"Found image: {filename}")
        print("Downloading image...")

        img_response = requests.get(
            f"{COMFYUI_URL}/view",
            params={"filename": filename, "type": "output"},
            timeout=60
        )

        with open("result.png", "wb") as f:
            f.write(img_response.content)

        print("=" * 50)
        print("SUCCESS! Image saved as: result.png")
        print("Check the same folder as this script.")
        print("=" * 50)
    else:
        print("Job completed. Check the raw response above for the filename.")
        print(f"Then open: {COMFYUI_URL}/view?filename=YOUR_FILENAME&type=output")

except requests.exceptions.Timeout:
    print("\nTIMEOUT - The request took too long.")
    print(f"Check queue status: {BASE_URL}/queue-info?token={TOKEN}")

except Exception as e:
    print(f"\nERROR: {e}")
    print("Make sure your instance is still running on Vast.ai")
