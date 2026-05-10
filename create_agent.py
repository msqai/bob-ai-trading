"""
Phase 3: create the BoB AI Trading agent.
Run once. Updates bob_ids.json with the agent_id.
"""

import json
import anthropic
from bob_prompts import SYSTEM_PROMPT

# ── Tool definitions (importable without side effects) ────────────────────────
TOOLS = [
    # Built-in file tools (for memory store I/O)
    {
        "type": "agent_toolset_20260401",
        "default_config": {"enabled": False},
        "configs": [
            {"name": "read",  "enabled": True, "permission_policy": {"type": "always_allow"}},
            {"name": "write", "enabled": True, "permission_policy": {"type": "always_allow"}},
            {"name": "edit",  "enabled": True, "permission_policy": {"type": "always_allow"}},
            {"name": "glob",  "enabled": True, "permission_policy": {"type": "always_allow"}},
            {"name": "grep",  "enabled": True, "permission_policy": {"type": "always_allow"}},
            # bash / web_fetch / web_search stay off — use custom tools instead
        ],
    },
    {
        "type": "custom",
        "name": "fetch_okx_closed_trades",
        "description": (
            "Fetch trading performance from OKX: 24h closed trades plus 24h and 7d "
            "PnL aggregates, current AUM, copier count, and currently-open positions. "
            "Returns a JSON object with keys: trades_24h (list of recent fills with "
            "symbol/side/pnl_usdt), trades_7d_count (int), pnl_24h_usdt (float), "
            "pnl_7d_usdt (float), pnl_24h_pct (float), pnl_7d_pct (float), "
            "aum_usdt (float), copier_count (int), open_positions (list of "
            "active swap positions, each with symbol/side/size_contracts/upl_usdt; "
            "empty list if no positions are open), date (YYYY-MM-DD)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to fetch closed trades for, YYYY-MM-DD. Omit for today (UTC).",
                }
            },
            "required": [],
        },
    },
    {
        "type": "custom",
        "name": "fetch_crypto_news",
        "description": (
            "Pull the latest crypto headlines from public RSS feeds "
            "(CoinTelegraph, CoinDesk, Decrypt, The Block, CryptoSlate, "
            "Bitcoin Magazine, CoinGape) and return them alongside cross-source "
            "trending topics. "
            "Items are pre-filtered to <24h old and sorted newest-first. "
            "Returns a JSON object with: "
            "raw_items (list of fresh articles, each with title/summary/source/"
            "published_at/age_hours — age_hours is a float, hours since publication) "
            "and trending_topics (list of clusters, each with topic/story_count/"
            "sample_headlines, sorted by story_count desc, only clusters of >=2 "
            "stories included, computed over fresh items only). "
            "Prefer leading with a topic from trending_topics where story_count >= 3; "
            "fall back to raw_items when no cluster is dominant. "
            "Use age_hours to enforce the <6h freshness gate when quoting any "
            "external market figure from a headline (per the 'Specific numbers' rules)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_items_per_feed": {
                    "type": "integer",
                    "description": "Max headlines to return per feed. Defaults to 5.",
                    "default": 5,
                }
            },
            "required": [],
        },
    },
    {
        "type": "custom",
        "name": "generate_meme_image",
        "description": (
            "Generate a Bob-the-bear meme image via Replicate Flux Schnell. "
            "Returns a JSON object with image_url (str) pointing to the generated image. "
            "Always describe Bob as a cartoon brown grizzly in a navy blazer holding a beer mug. "
            "The scene should reflect the trade_outcome."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Image generation prompt. Must describe Bob the bear "
                        "(cartoon brown grizzly, navy blazer, beer mug) and a scene matching "
                        "the trade outcome. Under 100 words."
                    ),
                },
                "trade_outcome": {
                    "type": "string",
                    "enum": ["win", "loss", "mixed"],
                    "description": (
                        "'win' = profitable day, 'loss' = down day, 'mixed' = flat or choppy."
                    ),
                },
            },
            "required": ["prompt", "trade_outcome"],
        },
    },
    {
        "type": "custom",
        "name": "send_for_approval",
        "description": (
            "Send the draft caption and meme image to the trader's Telegram for approval. "
            "The session will pause here until the trader replies. "
            "Returns a JSON object with approved (bool) and optionally feedback (str) "
            "if the trader requests changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "caption": {
                    "type": "string",
                    "description": "The post caption. Must be under 240 characters.",
                },
                "image_url": {
                    "type": "string",
                    "description": "URL of the generated meme image.",
                },
            },
            "required": ["caption", "image_url"],
        },
    },
    {
        "type": "custom",
        "name": "post_to_socials",
        "description": (
            "Post the approved caption and image to all social platforms "
            "(X/Twitter, Instagram, TikTok, Telegram channel) via Zernio. "
            "Returns a JSON object with platform_results (dict mapping platform name "
            "to post_id or error string)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "caption": {
                    "type": "string",
                    "description": "The approved post caption.",
                },
                "image_url": {
                    "type": "string",
                    "description": "URL of the meme image to post.",
                },
            },
            "required": ["caption", "image_url"],
        },
    },
]


def main():
    client = anthropic.Anthropic()

    with open("bob_ids.json") as f:
        ids = json.load(f)

    print("=== BoB AI Trading — Agent Setup ===\n")

    print("Creating BoB agent...")
    agent = client.beta.agents.create(
        model="claude-haiku-4-5",
        name="BoB AI Trading",
        description=(
            "Daily crypto meme post generator. Pulls OKX trade data, reads RSS news, "
            "picks a narrative, writes a caption in Bob-the-bear's voice, generates a meme "
            "image via Replicate, sends for Telegram approval, then posts via Zernio."
        ),
        system=SYSTEM_PROMPT,
        tools=TOOLS,
    )
    print(f"  ✅ Agent: {agent.id}\n")

    ids["agent_id"] = agent.id
    with open("bob_ids.json", "w") as f:
        json.dump(ids, f, indent=2)

    print("=" * 55)
    print("bob_ids.json updated:")
    print(json.dumps(ids, indent=2))
    print("=" * 55)


if __name__ == "__main__":
    main()
