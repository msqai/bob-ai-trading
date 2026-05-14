#!/usr/bin/env python3
"""
Phase E1: regenerate the 8 mood-variant Bob references using IPAdapter-class
character consistency.

Model: ideogram-ai/ideogram-character
  - character_reference_image: assets/bob_canonical.png (locks identity)
  - prompt:                    drives pose / scene / mood
  - style_type:                "Fiction" (cartoon)
  - magic_prompt_option:       "Off" (don't rewrite my prompt)
  - aspect_ratio:              "1:1"

Single pass per variant (no 3-pass strategy — IPAdapter-class models are
designed to lock identity on first attempt). Output is webp from Replicate;
converted to PNG via Pillow before saving to assets/bob_<variant>.png.
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image


CANONICAL_BOB_IMAGE = (
    "https://raw.githubusercontent.com/msqai/bob-ai-trading/"
    "main/assets/bob_canonical.png"
)
TOKEN = os.environ["REPLICATE_API_TOKEN"]

MODEL_OWNER   = "ideogram-ai"
MODEL_NAME    = "ideogram-character"
MODEL_VERSION = "1f8e198263a0d8171b76c55907c294e933e1e7d55e2d0c54f319c0e4a42c723d"

# Style anchor that every prompt should preserve, since the canonical Bob
# is a cartoon illustration on a dark green background.
STYLE_ANCHOR = "cartoon illustration style, dark green background"

VARIANTS = [
    ("bob_chill_winning",
     "Bob the brown grizzly bear wearing a navy blue blazer over a white button-up shirt, "
     "sitting in a chair leaning back, relaxed satisfied smile, holding beer mug raised at "
     "moderate height, laptop on desk showing a green up-trending chart, full upper-body shot, "
     "dark green background, cartoon illustration style"),
    ("bob_smug_winning",
     "Bob the brown grizzly bear wearing a navy blue blazer over a white button-up shirt, "
     "leaning forward at desk with confident smirk, beer mug raised high triumphantly, "
     "laptop on desk showing strong green up-trend chart, full upper-body shot, "
     "dark green background, cartoon illustration style"),
    ("bob_slumped_losing",
     "Bob the brown grizzly bear wearing a navy blue blazer over a white button-up shirt, "
     "slumped over desk with head resting on paw, defeated expression, beer mug sitting "
     "untouched on desk, laptop showing red downward chart, full upper-body shot, "
     "dark green background, cartoon illustration style"),
    ("bob_defeated_losing",
     "Bob the brown grizzly bear wearing a navy blue blazer over a white button-up shirt, "
     "looking away from laptop, paws limp on desk, beer mug empty and tipped on its side, "
     "laptop showing red downward arrow chart, full upper-body shot, "
     "dark green background, cartoon illustration style"),
    ("bob_hunched_focused",
     "Bob the brown grizzly bear wearing a navy blue blazer over a white button-up shirt, "
     "leaning forward intently with narrow scrutinizing eyes, paws on desk near laptop, "
     "beer mug to the side, laptop showing mixed candle chart, full upper-body shot, "
     "dark green background, cartoon illustration style"),
    ("bob_alert_skeptical",
     "Bob the brown grizzly bear wearing a navy blue blazer over a white button-up shirt, "
     "sitting upright with raised eyebrow, paw on chin in thoughtful pose, beer mug on desk, "
     "laptop showing volatile choppy chart, full upper-body shot, "
     "dark green background, cartoon illustration style"),
    ("bob_asleep_inactive",
     "Bob the brown grizzly bear wearing a navy blue blazer over a white button-up shirt, "
     "eyes closed with head resting on paw, beer mug full and untouched on desk, "
     "laptop screen dim or showing flat line, full upper-body shot, "
     "dark green background, cartoon illustration style"),
    ("bob_worried_volatile",
     "Bob the brown grizzly bear wearing a navy blue blazer over a white button-up shirt, "
     "eyes wide with concern, both paws slightly raised in alarm, beer mug pushed aside, "
     "laptop showing chaotic spiky price action, full upper-body shot, "
     "dark green background, cartoon illustration style"),
]

INTER_CALL_DELAY = 5  # seconds between successive POST /predictions to avoid 429 bursts


def _post_with_429_retry(url, data, headers, max_attempts=5):
    """POST with exponential backoff on 429 (Replicate rate limit)."""
    for attempt in range(max_attempts):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            if e.code == 429 and attempt < max_attempts - 1:
                retry_after = int(e.headers.get("Retry-After") or 0)
                wait = max(retry_after, 2 ** (attempt + 3))  # 8, 16, 32, 64
                print(f"    [429] backing off {wait}s (attempt {attempt+1}/{max_attempts})", flush=True)
                time.sleep(wait)
                continue
            print(f"    [HTTP {e.code}] body: {body[:500]}", flush=True)
            raise


def replicate_predict(input_dict):
    body = json.dumps({
        "version": MODEL_VERSION,
        "input":   input_dict,
    }).encode()
    pred = _post_with_429_retry(
        "https://api.replicate.com/v1/predictions",
        body,
        {"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"},
    )
    pid  = pred["id"]
    poll = f"https://api.replicate.com/v1/predictions/{pid}"
    for _ in range(90):  # up to 3 minutes
        time.sleep(2)
        req = urllib.request.Request(poll, headers={"Authorization": f"Token {TOKEN}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            s = json.loads(r.read())
        if s["status"] == "succeeded":
            out = s["output"]
            return out[0] if isinstance(out, list) else out
        if s["status"] in ("failed", "canceled"):
            raise RuntimeError(f"Replicate {s['status']}: {s.get('error')}")
    raise RuntimeError("Replicate prediction timed out")


def download_and_convert_to_png(url, out_path):
    req = urllib.request.Request(url, headers={"User-Agent": "BoB-AI-Trading/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.save(out_path, format="PNG")


def main():
    out_dir = os.environ.get("OUT_DIR", "assets")
    os.makedirs(out_dir, exist_ok=True)

    for slug, prompt in VARIANTS:
        print(f"=== {slug} ===", flush=True)
        print(f"  prompt: {prompt}", flush=True)
        try:
            url = replicate_predict({
                "prompt":                    prompt,
                "character_reference_image": CANONICAL_BOB_IMAGE,
                "style_type":                "Fiction",
                "magic_prompt_option":       "Off",
                "aspect_ratio":              "1:1",
                "rendering_speed":           "Default",
            })
            print(f"  url: {url}", flush=True)
            png_path = os.path.join(out_dir, f"{slug}.png")
            download_and_convert_to_png(url, png_path)
            print(f"  saved: {png_path}", flush=True)
        except Exception as exc:
            print(f"  [FAIL] {exc}", flush=True)
        time.sleep(INTER_CALL_DELAY)

    print("DONE")


if __name__ == "__main__":
    main()
