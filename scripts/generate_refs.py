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


def replicate(input_dict):
    payload = json.dumps({
        "version": "black-forest-labs/flux-dev",
        "input":   input_dict,
    }).encode()
    req = urllib.request.Request(
        "https://api.replicate.com/v1/predictions",
        data=payload,
        headers={"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        pred = json.loads(resp.read())
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


def main():
    os.makedirs("out", exist_ok=True)
    for slug, scene in VARIANTS:
        print(f"=== {slug} ===", flush=True)
        scene_prompt = f"{IDENTITY}, {scene}, dark green background, cartoon style"

        print("  pass1 (img2img 0.85)...", flush=True)
        u1 = replicate({
            "prompt":          scene_prompt,
            "image":           CANONICAL_BOB_IMAGE,
            "prompt_strength": 0.85,
            "num_outputs":     1,
            "output_format":   "png",
        })
        download(u1, f"out/{slug}_pass1.png")
        print(f"    -> {u1}", flush=True)

        print("  pass2 (img2img 0.92)...", flush=True)
        u2 = replicate({
            "prompt":          scene_prompt,
            "image":           CANONICAL_BOB_IMAGE,
            "prompt_strength": 0.92,
            "num_outputs":     1,
            "output_format":   "png",
        })
        download(u2, f"out/{slug}_pass2.png")
        print(f"    -> {u2}", flush=True)

        print("  pass3 (text-to-image fallback)...", flush=True)
        u3 = replicate({
            "prompt":        TTI_PREFIX + scene,
            "num_outputs":   1,
            "output_format": "png",
        })
        download(u3, f"out/{slug}_pass3.png")
        print(f"    -> {u3}", flush=True)

    print("DONE")


if __name__ == "__main__":
    main()
