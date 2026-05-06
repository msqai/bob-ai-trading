"""
Phase 4: dry-run test session for BoB AI Trading.

- Updates the agent with the corrected system prompt from create_agent.py
- Creates a session with the memory store attached
- Stubs 4 of the 5 custom tools; fetch_crypto_news hits real RSS
- Streams all events and prints Bob's full output
"""

import json
import sys
import textwrap
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import anthropic
from bob_prompts import SYSTEM_PROMPT

# ── Config ────────────────────────────────────────────────────────────────────

FAKE_TRADES = {
    "date": "2026-05-06",
    "trades": [
        {"symbol": "BTC-USDT-SWAP", "side": "long",  "pnl_usdt":  847, "pnl_pct":  12.3, "hold_minutes": 240},
        {"symbol": "ETH-USDT-SWAP", "side": "long",  "pnl_usdt":  320, "pnl_pct":   4.1, "hold_minutes":  90},
        {"symbol": "SOL-USDT-SWAP", "side": "short", "pnl_usdt": -180, "pnl_pct":  -2.8, "hold_minutes":  60},
    ],
    "total_pnl_usdt": 987,
    "aum_usdt": 847000,
    "copier_count": 312,
}

RSS_FEEDS = [
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt",       "https://decrypt.co/feed"),
    ("TheBlock",      "https://www.theblock.co/rss.xml"),
]

# ── RSS fetch (real network) ──────────────────────────────────────────────────

def fetch_rss_news(max_items: int = 5) -> list:
    articles = []
    for source, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BoB-AI-Trading/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            items = root.findall(".//item")[:max_items]
            for item in items:
                title   = (item.findtext("title")       or "").strip()
                summary = (item.findtext("description") or "").strip()
                pub     = (item.findtext("pubDate")     or "").strip()
                # strip HTML tags from summary crudely
                import re
                summary = re.sub(r"<[^>]+>", "", summary)[:200]
                articles.append({
                    "title":        title,
                    "summary":      summary,
                    "source":       source,
                    "published_at": pub,
                })
        except Exception as exc:
            articles.append({
                "title":        f"[fetch error — {source}]",
                "summary":      str(exc),
                "source":       source,
                "published_at": "",
            })
    return articles


# ── Tool stubs ────────────────────────────────────────────────────────────────

def dispatch_tool(name: str, tool_input: dict) -> dict:
    _hr()
    print(f"  TOOL CALL  →  {name}")
    print(f"  input: {json.dumps(tool_input, indent=4)}")

    if name == "fetch_okx_closed_trades":
        result = FAKE_TRADES

    elif name == "fetch_crypto_news":
        max_items = tool_input.get("max_items_per_feed", 5)
        print(f"  [live RSS fetch, max {max_items} per feed]")
        result = fetch_rss_news(max_items)

    elif name == "generate_meme_image":
        print(f"  [stub — Replicate skipped]")
        result = {"image_url": "https://example.com/bob_test.jpg"}

    elif name == "send_for_approval":
        print(f"  [stub — auto-approving]")
        result = {"approved": True}

    elif name == "post_to_socials":
        print(f"  [stub — dry run]")
        result = {
            "dry_run":    True,
            "would_post": tool_input.get("caption", ""),
            "image_url":  tool_input.get("image_url", ""),
        }

    else:
        result = {"error": f"unknown tool: {name}"}

    print(f"  result: {json.dumps(result, indent=4)[:400]}")
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hr(char="─", width=70):
    print(char * width)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    client = anthropic.Anthropic()

    with open("bob_ids.json") as f:
        ids = json.load(f)

    agent_id      = ids["agent_id"]
    env_id        = ids["environment_id"]
    memstore_id   = ids["memory_store_id"]

    # ── Step 1: update agent system prompt ───────────────────────────────────
    print("Fetching current agent version...")
    agent = client.beta.agents.retrieve(agent_id)
    print(f"  agent version: {agent.version}")

    print("Updating agent system prompt...")
    agent = client.beta.agents.update(
        agent_id,
        version=agent.version,
        system=SYSTEM_PROMPT,
    )
    print(f"  ✅ Agent updated to version {agent.version}\n")

    # ── Step 2: create session ────────────────────────────────────────────────
    print("Creating test session...")
    session = client.beta.sessions.create(
        agent=agent_id,
        environment_id=env_id,
        title="BoB dry-run test 2026-05-06",
        resources=[
            {
                "type":            "memory_store",
                "memory_store_id": memstore_id,
                "access":          "read_write",
                "instructions":    (
                    "Store used narrative slugs in /mnt/memory/bob-state/used_narratives.json "
                    "and post history in /mnt/memory/bob-state/post_history.json."
                ),
            }
        ],
    )
    print(f"  ✅ Session: {session.id}\n")

    # ── Step 3: stream + tool loop ────────────────────────────────────────────
    _hr("═")
    print("  BOB AI TRADING — DRY RUN")
    _hr("═")

    collected = {
        "narrative_slug": None,
        "caption":        None,
        "image_prompt":   None,
        "image_url":      None,
        "would_post":     None,
        "agent_messages": [],
    }

    stream = client.beta.sessions.events.stream(session.id)
    stream.__enter__()

    try:
        # Kick off the session — send before iterating so events are buffered
        client.beta.sessions.events.send(
            session.id,
            events=[{
                "type":    "user.message",
                "content": [{"type": "text", "text": "Run today's BoB post."}],
            }],
        )

        for event in stream:
            etype = event.type

            if etype == "session.status_running":
                print("\n[session running]\n")

            elif etype == "agent.thinking":
                thinking_text = getattr(event, "thinking", "")
                if thinking_text:
                    print(f"\n[thinking]\n{textwrap.fill(thinking_text, 70)}\n")

            elif etype == "agent.tool_use":
                # built-in tool (file read/write/etc.) — log briefly
                tool_name  = getattr(event, "name", "?")
                tool_input = getattr(event, "input", {})
                print(f"\n[built-in tool]  {tool_name}")
                if "path" in tool_input:
                    print(f"  path: {tool_input['path']}")

            elif etype == "agent.tool_result":
                pass  # built-in tool result, no need to log

            elif etype == "agent.custom_tool_use":
                result = dispatch_tool(event.name, event.input)

                # Capture key outputs for the summary
                if event.name == "generate_meme_image":
                    collected["image_prompt"] = event.input.get("prompt")
                    collected["image_url"]    = result.get("image_url")
                elif event.name == "post_to_socials":
                    collected["would_post"] = result.get("would_post")

                client.beta.sessions.events.send(
                    session.id,
                    events=[{
                        "type":              "user.custom_tool_result",
                        "custom_tool_use_id": event.id,
                        "content":           [{"type": "text", "text": json.dumps(result)}],
                    }],
                )

            elif etype == "agent.message":
                text = ""
                content = getattr(event, "content", [])
                for block in content:
                    if getattr(block, "type", "") == "text":
                        text += block.text
                if text:
                    _hr()
                    print(f"  BOB SAYS:\n")
                    print(textwrap.fill(text, 70))
                    collected["agent_messages"].append(text)

            elif etype == "session.status_idle":
                stop_type = event.stop_reason.type if event.stop_reason else "?"
                if stop_type == "end_turn":
                    print("\n[session end_turn — done]\n")
                    break
                # requires_action means we haven't sent all tool results yet — keep going

            elif etype == "session.status_terminated":
                print("\n[session terminated]\n")
                break

            elif etype == "session.error":
                print(f"\n[session error] {event}")
                sys.exit(1)

    finally:
        stream.__exit__(None, None, None)

    # ── Step 4: summary ───────────────────────────────────────────────────────
    _hr("═")
    print("  DRY-RUN SUMMARY")
    _hr("═")

    for msg in collected["agent_messages"]:
        # The last agent message often contains the narrative info
        if "slug" in msg.lower() or "narrative" in msg.lower():
            print(f"Narrative note:  {msg[:200]}")

    if collected["image_prompt"]:
        _hr()
        print("IMAGE PROMPT SENT TO REPLICATE:")
        print(textwrap.fill(collected["image_prompt"], 70))

    if collected["would_post"]:
        _hr()
        print("WOULD-POST CAPTION (what goes to X/IG/TikTok):")
        caption = collected["would_post"]
        print(f"\n  \"{caption}\"")
        print(f"\n  Characters: {len(caption)}/240")

    if collected["image_url"]:
        _hr()
        print(f"IMAGE URL:  {collected['image_url']}")

    _hr("═")
    ids["session_id_last_test"] = session.id
    with open("bob_ids.json", "w") as f:
        json.dump(ids, f, indent=2)
    print(f"Session ID saved to bob_ids.json: {session.id}")
    _hr("═")


if __name__ == "__main__":
    main()
