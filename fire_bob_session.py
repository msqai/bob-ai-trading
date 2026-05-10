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

import json
import os
import ssl
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

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


# ── OKX proxy (Cyprus VPS) ────────────────────────────────────────────────────

def fetch_okx_closed_trades(tool_input: dict) -> dict:
    today = tool_input.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    empty = {"trades": [], "total_pnl_usdt": 0, "aum_usdt": 0, "copier_count": 0}

    try:
        proxy_url    = os.environ["BOB_PROXY_URL"].rstrip("/")
        proxy_secret = os.environ["BOB_PROXY_SECRET"]
        url = f"{proxy_url}/closed-trades?" + urllib.parse.urlencode({"date": today})
        req = urllib.request.Request(url, headers={"X-Bob-Secret": proxy_secret})
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        return {**empty, "error": str(exc)}


# ── RSS news ──────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    ("CoinTelegraph",   "https://cointelegraph.com/rss"),
    ("CoinDesk",        "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt",         "https://decrypt.co/feed"),
    ("TheBlock",        "https://www.theblock.co/rss.xml"),
    ("CryptoSlate",     "https://cryptoslate.com/feed/"),
    ("BitcoinMagazine", "https://bitcoinmagazine.com/.rss/full/"),
    ("CoinGape",        "https://coingape.com/feed/"),
]

# Drop common English + crypto-generic words from keyword extraction so clusters
# form around meaningful topics (tickers, named entities, project names) rather
# than filler.
_STOPWORDS = {
    "the","a","an","and","or","but","of","to","in","on","for","with","at","by",
    "from","as","is","are","was","were","be","been","being","this","that","these",
    "those","it","its","up","down","over","under","into","out","new","now","said",
    "after","before","amid","plus","via","says","could","will","would","may","might",
    "has","have","had","not","no","yes","more","less","than","then","just","about",
    "vs","among","across","first","second","top","best","worst","big","small",
    "crypto","cryptocurrency","cryptocurrencies","price","prices","market","markets",
    "news","report","update","analysis","today","week","month","year","amid","amid",
}


def _keywords(title: str) -> list[str]:
    import re
    words = re.findall(r"[A-Za-z0-9$]{2,}", title)
    return [w for w in (w.lower() for w in words) if w not in _STOPWORDS and len(w) > 2]


def cluster_headlines(items: list, max_clusters: int = 10) -> list:
    """Group items by shared top keywords. Lightweight — not NLP-grade.

    Approach: count keyword frequency across all items, then for each item pick
    its rarest-but-still-shared keyword as its cluster label. Two items end up
    in the same cluster when they share that anchor keyword. Picking the rarer
    shared keyword surfaces specific stories ("clarity_act", "trump_media")
    instead of collapsing everything under generic anchors like "bitcoin".
    """
    from collections import Counter, defaultdict
    if not items:
        return []
    df = Counter()  # document frequency per keyword
    item_kws = []
    for it in items:
        kws = set(_keywords(it.get("title", "")))
        item_kws.append(kws)
        df.update(kws)
    # Anchor = rarest-but-still-shared keyword (df>=2). Tie-break by length desc (prefer more specific tokens).
    clusters: dict = defaultdict(list)
    for it, kws in zip(items, item_kws):
        shared = [k for k in kws if df[k] >= 2]
        if not shared:
            continue
        anchor = min(shared, key=lambda k: (df[k], -len(k)))
        clusters[anchor].append(it)
    ordered = sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:max_clusters]
    return [
        {
            "topic": topic,
            "story_count": len(group),
            "sample_headlines": [g.get("title", "") for g in group[:3]],
        }
        for topic, group in ordered
        if len(group) >= 2
    ]


AGE_LIMIT_HOURS = 24


def _fetch_with_redirects(url: str, max_hops: int = 5) -> bytes:
    """urllib's default redirect handler historically refused 308 (some Python
    versions still raise HTTPError on it). Follow 30x manually — covers
    CoinDesk's permanent 308 to its CDN-hosted feed."""
    for _ in range(max_hops):
        req = urllib.request.Request(url, headers={"User-Agent": "BoB-AI-Trading/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location")
                if not loc:
                    raise
                url = urllib.parse.urljoin(url, loc)
                continue
            raise
    raise RuntimeError(f"too many redirects for {url}")


def fetch_crypto_news(tool_input: dict) -> dict:
    import re
    max_items   = tool_input.get("max_items_per_feed", 8)
    age_limit_h = tool_input.get("age_limit_hours",   AGE_LIMIT_HOURS)
    now         = datetime.now(timezone.utc)

    fresh: list = []
    per_source: dict = {}

    for source, url in RSS_FEEDS:
        per_source[source] = 0
        try:
            raw  = _fetch_with_redirects(url)
            root = ET.fromstring(raw)
        except Exception as exc:
            print(f"[fetch_crypto_news] {source} fetch error: {exc}", file=sys.stderr)
            continue

        for item in root.findall(".//item")[:max_items]:
            title   = (item.findtext("title")       or "").strip()
            summary = re.sub(r"<[^>]+>", "", item.findtext("description") or "")[:200]
            pub_str = (item.findtext("pubDate")     or "").strip()

            age_h = None
            if pub_str:
                try:
                    dt = parsedate_to_datetime(pub_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age_h = (now - dt).total_seconds() / 3600
                except Exception:
                    age_h = None

            if age_h is None or age_h > age_limit_h:
                continue

            fresh.append({
                "title":        title,
                "summary":      summary,
                "source":       source,
                "published_at": pub_str,
                "age_hours":    round(age_h, 1),
            })
            per_source[source] += 1

    fresh.sort(key=lambda a: a["age_hours"])

    for source, n in per_source.items():
        if n == 0:
            print(f"[fetch_crypto_news] WARN: zero fresh items from {source}", file=sys.stderr)
    if len(fresh) < 5:
        print(f"[fetch_crypto_news] WARN: only {len(fresh)} fresh items across all sources", file=sys.stderr)

    return {
        "raw_items":       fresh,
        "trending_topics": cluster_headlines(fresh),
    }


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
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        print(f"[telegram] {method} HTTP {e.code}: {body}", file=sys.stderr)
        raise RuntimeError(f"Telegram {method} HTTP {e.code}: {body}") from e


def send_for_approval(tool_input: dict) -> dict:
    chat_id   = require_env("TELEGRAM_CHAT_ID")
    caption   = tool_input["caption"]
    image_url = tool_input["image_url"]

    header = "🐻 *BoB AI Trading. Draft Post*"
    if is_dry_run():
        platforms = ", ".join(SOCIAL_PLATFORMS)
        header = (
            f"🧪 *DRY RUN. Would have posted to: {platforms}*\n"
            f"🐻 *BoB AI Trading. Draft Post*"
        )

    msg = (
        f"{header}\n\n"
        f"{caption}\n\n"
        f"Reply *YES* to post, or reply with feedback to revise."
    )
    _tg("sendPhoto", {
        "chat_id":    chat_id,
        "photo":      image_url,
        "caption":    msg,
        "parse_mode": "Markdown",
    })

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
