#!/usr/bin/env python3
"""
One-off: generate 8 mood-variant Bob references via Replicate Flux.

Each variant runs three passes and uploads all 24 outputs as artifacts so the
caller can pick the best result per variant after visual review:
  pass1 — img2img off canonical_bob.png at prompt_strength 0.85
  pass2 — img2img at 0.92
  pass3 — text-to-image fallback (no input image) with extensive identity anchor

Outputs to ./out/<variant>_pass<N>.png. Caller picks the best per variant and
commits only the 8 chosen PNGs to assets/bob_<variant>.png on main.
"""
import json
import os
import time
import urllib.request


CANONICAL_BOB_IMAGE = (
    "https://raw.githubusercontent.com/msqai/bob-ai-trading/"
    "main/assets/bob_canonical.png"
)
TOKEN = os.environ["REPLICATE_API_TOKEN"]

# Identity anchor required in every prompt (per Phase 2A spec).
IDENTITY = "Bob the brown grizzly bear in navy blazer with beer mug"

VARIANTS = [
    ("bob_chill_winning",    "relaxed satisfied smile, beer raised modestly, leaning back in chair, laptop showing green chart, calm winning vibe"),
    ("bob_smug_winning",     "confident smirk, beer raised high triumphantly, leaning forward, laptop showing strong green up-trend, victorious"),
    ("bob_slumped_losing",   "head down on paw, slumped over desk, beer mug sitting untouched, laptop showing red chart, defeated"),
    ("bob_defeated_losing",  "looking away from laptop, beer mug empty and tipped, paws limp on desk, laptop showing red downward arrow, exhausted"),
    ("bob_hunched_focused",  "leaning forward intently, narrow scrutinizing eyes, beer mug to the side, laptop with mixed candle chart, focused"),
    ("bob_alert_skeptical",  "sitting upright, raised eyebrow, paw on chin in thought, laptop showing volatile chart, skeptical"),
    ("bob_asleep_inactive",  "eyes closed, head resting in paw, beer mug full and untouched, laptop screen dim or off, peaceful nap"),
    ("bob_worried_volatile", "eyes wide, paws slightly raised, beer mug pushed away, laptop showing chaotic price action, alarmed"),
]

# Text-to-image fallback prefix. Heavier identity anchoring since no ref image.
TTI_PREFIX = (
    "Bob the brown grizzly bear, cartoon illustration style, wearing navy blue blazer "
    "over white button-up shirt, brown fur, friendly round face, large paws, dark green "
    "background. "
)


import urllib.error


def _post_with_429_retry(url, data, headers, max_attempts=5):
    """POST with exponential backoff on 429 (Replicate rate limit)."""
    for attempt in range(max_attempts):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_attempts - 1:
                retry_after = int(e.headers.get("Retry-After") or 0)
                wait = max(retry_after, 2 ** (attempt + 3))  # 8, 16, 32, 64
                print(f"    [429] backing off {wait}s (attempt {attempt+1}/{max_attempts})", flush=True)
                time.sleep(wait)
                continue
            raise


def replicate(input_dict):
    body = json.dumps({
        "version": "black-forest-labs/flux-dev",
        "input":   input_dict,
    }).encode()
    pred = _post_with_429_retry(
        "https://api.replicate.com/v1/predictions",
        body,
        {"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"},
    )
    pid  = pred["id"]
    poll = f"https://api.replicate.com/v1/predictions/{pid}"
    for _ in range(60):
        time.sleep(2)
        req = urllib.request.Request(poll, headers={"Authorization": f"Token {TOKEN}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            s = json.loads(r.read())
        if s["status"] == "succeeded":
            return s["output"][0]
        if s["status"] in ("failed", "canceled"):
            raise RuntimeError(f"Replicate {s['status']}: {s.get('error')}")
    raise RuntimeError("Replicate prediction timed out")


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "BoB-AI-Trading/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        with open(path, "wb") as f:
            f.write(resp.read())


INTER_CALL_DELAY = 5  # seconds between successive POST /predictions, avoid 429 bursts


def _try_pass(slug, pass_num, label, input_dict):
    """Run one pass and save the output. Swallow per-pass exceptions so a
    single failure doesn't abort the rest of the batch."""
    out = f"out/{slug}_pass{pass_num}.png"
    print(f"  pass{pass_num} ({label})...", flush=True)
    try:
        url = replicate(input_dict)
        download(url, out)
        print(f"    -> {url}", flush=True)
    except Exception as exc:
        print(f"    [FAIL] {exc}", flush=True)


def main():
    os.makedirs("out", exist_ok=True)
    for slug, scene in VARIANTS:
        print(f"=== {slug} ===", flush=True)
        scene_prompt = f"{IDENTITY}, {scene}, dark green background, cartoon style"

        _try_pass(slug, 1, "img2img 0.85", {
            "prompt":          scene_prompt,
            "image":           CANONICAL_BOB_IMAGE,
            "prompt_strength": 0.85,
            "num_outputs":     1,
            "output_format":   "png",
        })
        time.sleep(INTER_CALL_DELAY)

        _try_pass(slug, 2, "img2img 0.92", {
            "prompt":          scene_prompt,
            "image":           CANONICAL_BOB_IMAGE,
            "prompt_strength": 0.92,
            "num_outputs":     1,
            "output_format":   "png",
        })
        time.sleep(INTER_CALL_DELAY)

        _try_pass(slug, 3, "text-to-image fallback", {
            "prompt":        TTI_PREFIX + scene,
            "num_outputs":   1,
            "output_format": "png",
        })
        time.sleep(INTER_CALL_DELAY)

    print("DONE")


if __name__ == "__main__":
    main()
