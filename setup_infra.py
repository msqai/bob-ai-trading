"""
Phase 2: create the cloud environment and memory store for BoB AI Trading.
Run once. Saves IDs to bob_ids.json (git-ignored).
"""

import json
import os
import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

print("=== BoB AI Trading — Infrastructure Setup ===\n")

# ── Environment ──────────────────────────────────────────────────────────────
print("Creating cloud environment...")
env = client.beta.environments.create(
    name="bob-trading-env",
    description="BoB AI Trading daily post runner",
    config={
        "type": "cloud",
        "networking": {"type": "unrestricted"},  # needs outbound for RSS + OKX
    },
)
print(f"  ✅ Environment: {env.id}\n")

# ── Memory Store ─────────────────────────────────────────────────────────────
print("Creating memory store...")
store = client.beta.memory_stores.create(
    name="bob-state",
    description=(
        "Persistent state for BoB AI Trading. "
        "Contains used_narratives.json (list of narrative slugs used in last 24h) "
        "and post_history.json (log of past posts). "
        "Read used_narratives.json before picking a narrative angle. "
        "Append to it after posting."
    ),
)
print(f"  ✅ Memory store: {store.id}")
print(f"     Mounts at:   /mnt/memory/bob-state/\n")

# ── Save IDs ─────────────────────────────────────────────────────────────────
ids = {
    "environment_id": env.id,
    "memory_store_id": store.id,
}

with open("bob_ids.json", "w") as f:
    json.dump(ids, f, indent=2)

print("=" * 55)
print("IDs saved to bob_ids.json (git-ignored).")
print()
print(json.dumps(ids, indent=2))
print("=" * 55)
print("\nNext step: Phase 3 — create the BoB agent.")
