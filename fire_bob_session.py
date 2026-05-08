"""
fire_bob_session.py — daily BoB AI Trading session runner.

Called by GitHub Actions at 21:00 UTC. Reads all credentials from
environment variables (set as GitHub Secrets). No hardcoded keys.

Environment variables required:
  ANTHROPIC_API_KEY      — Anthropic API key
  BOB_AGENT_ID           — agent_011...
  BOB_ENVIRONMENT_ID     — env_01...
  BOB_MEMORY_STORE_ID    — memstore_01...
  OKX_API_KEY            — OKX read-only key
  OKX_API_SECRET         — OKX read-only secret
  OKX_API_PASSPHRASE     — OKX passphrase
  REPLICATE_API_TOKEN    — Replicate token
  TELEGRAM_BOT_TOKEN     — Telegram bot token
  TELEGRAM_CHAT_ID       — your Telegram chat/user ID (for approvals)
  ZERNIO_API_KEY         — Zernio key (set to "placeholder" until wired up)

Optional:
  DRY_RUN                — when "true", skip post_to_socials and prepend a
                           DRY RUN banner to the Telegram approval message.
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import textwrap
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import anthropic

# ── Credentials from environment ─────────────────────────────────────────────

def require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"ERROR: required env var {name} is not set", file=sys.stderr)
        sys.exit(1)
    return val


def is_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "").strip().lower() == "true"


SOCIAL_PLATFORMS = ["x", "instagram", "tiktok", "telegram"]


# ── OKX API helper ────────────────────────────────────────────────────────────

def _okx_sign(timestamp: str, method: str, path: str, body: str = "") -> dict:
    secret = require_env("OKX_API_SECRET")
    passphrase = require_env("OKX_API_PASSPHRASE")
    prehash = timestamp + method.upper() + path + body
    sig = base64.b64encode(
        hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "OK-ACCESS-KEY":        require_env("OKX_API_KEY"),
        "OK-ACCESS-SIGN":       sig,
        "OK-ACCESS-TIMESTAMP":  timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type":         "application/json",
    }


def _okx_get(path: str) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    headers = _okx_sign(ts, "GET", path)
    url = "https://www.okx.com" + path
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_okx_closed_trades(tool_input: dict) -> dict:
    today = tool_input.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Closed orders (last 24h)
    try:
        orders_resp = _okx_get("/api/v5/trade/orders-history?instType=SWAP&state=filled&limit=20")
        raw_orders  = orders_resp.get("data", [])
    except Exception as exc:
        raw_orders = []
        print(f"  [OKX orders fetch error: {exc}]")

    trades = []
    total_pnl = 0.0
    for o in raw_orders:
        pnl = float(o.get("pnl", 0))
        total_pnl += pnl
        trades.append({
            "symbol":        o.get("instId", ""),
            "side":          o.get("side", ""),
            "pnl_usdt":      round(pnl, 2),
            "hold_minutes":  None,
        })

    # Account balance (AUM proxy)
    aum = 0.0
    try:
        bal_resp = _okx_get("/api/v5/account/balance?ccy=USDT")
        for detail in bal_resp.get("data", [{}])[0].get("details", []):
            if detail.get("ccy") == "USDT":
                aum = float(detail.get("eq", 0))
    except Exception as exc:
        print(f"  [OKX balance fetch error: {exc}]")

    # Copy-trading stats (lead trader endpoint)
    copiers = 0
    try:
        ct_resp = _okx_get("/api/v5/copytrading/public-lead-traders?instType=SWAP")
        for trader in ct_resp.get("data", []):
            if trader.get("leadTraderUid"):
                copiers = int(trader.get("copyTradingNum", 0))
                break
    except Exception as exc:
        print(f"  [OKX copier count fetch error: {exc}]")

    return {
        "date":           today,
        "trades":         trades,
        "total_pnl_usdt": round(total_pnl, 2),
        "aum_usdt":       round(aum, 2),
        "copier_count":   copiers,
    }


# ── RSS news ──────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt",       "https://decrypt.co/feed"),
    ("TheBlock",      "https://www.theblock.co/rss.xml"),
]


def fetch_crypto_news(tool_input: dict) -> list:
    import re
    max_items = tool_input.get("max_items_per_feed", 5)
    articles = []
    for source, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BoB-AI-Trading/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            for item in root.findall(".//item")[:max_items]:
                title   = (item.findtext("title")       or "").strip()
                summary = re.sub(r"<[^>]+>", "", item.findtext("description") or "")[:200]
                pub     = (item.findtext("pubDate")     or "").strip()
                articles.append({"title": title, "summary": summary,
                                  "source": source, "published_at": pub})
        except Exception as exc:
            articles.append({"title": f"[fetch error — {source}]",
                              "summary": str(exc), "source": source, "published_at": ""})
    return articles


# ── Replicate image generation ────────────────────────────────────────────────

CANONICAL_BOB_IMAGE = "https://raw.githubusercontent.com/msqai/bob-ai-trading/main/assets/bob_canonical.png"


def generate_meme_image(tool_input: dict) -> dict:
    token  = require_env("REPLICATE_API_TOKEN")
    prompt = tool_input["prompt"]

    # Create prediction (image-to-image off the canonical Bob ref)
    payload = json.dumps({
        "version": "black-forest-labs/flux-dev",
        "input":   {
            "prompt": prompt,
            "image": CANONICAL_BOB_IMAGE,
            "prompt_strength": 0.65,
            "num_outputs": 1,
            "output_format": "webp",
        },
    }).encode()
    req = urllib.request.Request(
        "https://api.replicate.com/v1/predictions",
        data=payload,
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        pred = json.loads(resp.read())

    pred_id  = pred["id"]
    poll_url = f"https://api.replicate.com/v1/predictions/{pred_id}"

    # Poll until done (Flux Dev typically 20-30s)
    for _ in range(30):
        time.sleep(2)
        req = urllib.request.Request(
            poll_url,
            headers={"Authorization": f"Token {token}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = json.loads(resp.read())
        if status["status"] == "succeeded":
            image_url = status["output"][0]
            return {"image_url": image_url}
        if status["status"] in ("failed", "canceled"):
            return {"error": f"Replicate prediction {status['status']}: {status.get('error')}"}

    return {"error": "Replicate prediction timed out after 60s"}


# ── Telegram approval ─────────────────────────────────────────────────────────

def _tg(method: str, payload: dict) -> dict:
    token = require_env("TELEGRAM_BOT_TOKEN")
    data  = json.dumps(payload).encode()
    req   = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def send_for_approval(tool_input: dict) -> dict:
    chat_id   = require_env("TELEGRAM_CHAT_ID")
    caption   = tool_input["caption"]
    image_url = tool_input["image_url"]
    char_count = len(caption)

    header = "🐻 *BoB AI Trading — Draft Post*"
    if is_dry_run():
        platforms = ", ".join(SOCIAL_PLATFORMS)
        header = (
            f"🧪 *DRY RUN — would have posted to: {platforms}*\n"
            f"🐻 *BoB AI Trading — Draft Post*"
        )

    msg = (
        f"{header}\n\n"
        f"*Caption ({char_count}/240):*\n`{caption}`\n\n"
        f"*Image:* {image_url}\n\n"
        f"Reply *YES* to post, or reply with feedback to revise."
    )
    _tg("sendMessage", {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})

    # Poll for reply (up to 10 minutes)
    last_update_id = None
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(10)
        params  = urllib.parse.urlencode({"timeout": 8, "allowed_updates": '["message"]'})
        updates = _tg("getUpdates", {}) if last_update_id is None else \
                  _tg("getUpdates", {"offset": last_update_id + 1})
        for update in updates.get("result", []):
            last_update_id = update["update_id"]
            text = update.get("message", {}).get("text", "").strip().upper()
            if text == "YES":
                return {"approved": True}
            elif text:
                return {"approved": False, "feedback": update["message"]["text"]}

    return {"approved": False, "feedback": "Approval timed out after 10 minutes."}


# ── Zernio social posting ─────────────────────────────────────────────────────

def post_to_socials(tool_input: dict) -> dict:
    if is_dry_run():
        print("DRY RUN — skipping social distribution")
        return {"skipped": True, "reason": "DRY_RUN", "platforms": SOCIAL_PLATFORMS}

    zernio_key = os.environ.get("ZERNIO_API_KEY", "").strip()
    caption    = tool_input["caption"]
    image_url  = tool_input["image_url"]

    if not zernio_key or zernio_key == "placeholder":
        print("  [Zernio not yet configured — skipping social post]")
        return {"skipped": True, "reason": "ZERNIO_API_KEY not set"}

    payload = json.dumps({
        "caption":   caption,
        "image_url": image_url,
        "platforms": SOCIAL_PLATFORMS,
    }).encode()
    req = urllib.request.Request(
        "https://api.zernio.com/v1/post",
        data=payload,
        headers={
            "Authorization": f"Bearer {zernio_key}",
            "Content-Type":  "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ── Tool dispatcher ───────────────────────────────────────────────────────────

TOOL_HANDLERS = {
    "fetch_okx_closed_trades": fetch_okx_closed_trades,
    "fetch_crypto_news":       fetch_crypto_news,
    "generate_meme_image":     generate_meme_image,
    "send_for_approval":       send_for_approval,
    "post_to_socials":         post_to_socials,
}


def dispatch_tool(name: str, tool_input: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return handler(tool_input)
    except Exception as exc:
        return {"error": str(exc)}


# ── Main session loop ─────────────────────────────────────────────────────────

def main():
    client = anthropic.Anthropic()

    agent_id    = require_env("BOB_AGENT_ID")
    env_id      = require_env("BOB_ENVIRONMENT_ID")
    memstore_id = require_env("BOB_MEMORY_STORE_ID")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== BoB AI Trading — daily run {today} ===\n")

    # Create session
    session = client.beta.sessions.create(
        agent=agent_id,
        environment_id=env_id,
        title=f"BoB daily run {today}",
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
    print(f"Session: {session.id}\n")

    # Stream + tool loop
    exit_code = 0
    stream = client.beta.sessions.events.stream(session.id)
    stream.__enter__()
    try:
        client.beta.sessions.events.send(
            session.id,
            events=[{
                "type":    "user.message",
                "content": [{"type": "text", "text": "Run today's BoB post."}],
            }],
        )

        for event in stream:
            etype = event.type

            if etype == "agent.custom_tool_use":
                print(f"[tool] {event.name} ← {json.dumps(event.input)[:120]}")
                result = dispatch_tool(event.name, event.input)
                print(f"[tool] {event.name} → {json.dumps(result)[:120]}")
                client.beta.sessions.events.send(
                    session.id,
                    events=[{
                        "type":               "user.custom_tool_result",
                        "custom_tool_use_id": event.id,
                        "content":            [{"type": "text", "text": json.dumps(result)}],
                    }],
                )

            elif etype == "agent.message":
                for block in getattr(event, "content", []):
                    if getattr(block, "type", "") == "text":
                        print(f"\n[bob]\n{block.text}\n")

            elif etype == "session.status_idle":
                if event.stop_reason and event.stop_reason.type == "end_turn":
                    print("[done]")
                    break

            elif etype == "session.status_terminated":
                print("[terminated]")
                break

            elif etype == "session.error":
                print(f"[error] {event}", file=sys.stderr)
                exit_code = 1
                break

    except KeyboardInterrupt:
        print("\n[interrupted]")
        exit_code = 1
    finally:
        stream.__exit__(None, None, None)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
