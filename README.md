# BoB AI Trading

Autonomous daily crypto meme post generator. Once a day at 21:00 UTC, Bob the bear pulls his OKX trade results, scans live crypto news, picks a narrative angle, writes a caption in his own voice, generates a meme image, sends it to Telegram for your approval, then posts to X, Instagram, TikTok, and Telegram once approved.

Goal: follower acquisition for the OKX copy-trading lead trader profile.

---

## How it works

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitHub Actions (cron)                        │
│                         21:00 UTC daily                             │
│                    fire_bob_session.py runs here                    │
│              All secrets injected via GitHub Secrets                │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ creates session + streams events
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Anthropic Managed Agents (cloud)                       │
│                                                                     │
│  Agent: BoB AI Trading (claude-haiku-4-5)                          │
│  ┌─────────────────────────────────────────┐                        │
│  │  Built-in tools (file I/O)              │                        │
│  │  read / write / edit / glob / grep      │◄── /mnt/memory/        │
│  └─────────────────────────────────────────┘    bob-state/          │
│                                                 (Memory Store)      │
│  Custom tools (executed by GitHub Actions runner):                  │
│  ┌──────────────────────┐  agent emits agent.custom_tool_use        │
│  │ fetch_okx_closed_... │  session goes idle                        │
│  │ fetch_crypto_news    │  runner executes tool                     │
│  │ generate_meme_image  │  runner sends user.custom_tool_result     │
│  │ send_for_approval    │  agent resumes                            │
│  │ post_to_socials      │                                           │
│  └──────────────────────┘                                           │
└─────────────────────────────────────────────────────────────────────┘
         │              │             │              │
         ▼              ▼             ▼              ▼
      OKX API      RSS feeds     Replicate       Telegram
    (read-only)  (CoinTelegraph  (Flux Schnell   (approval +
                  CoinDesk etc)   meme image)    final post)
                                                      │
                                                      ▼ (after YES)
                                                   Zernio
                                              (X / IG / TikTok /
                                               Telegram channel)
```

**Key design decision:** Custom tools run on the GitHub Actions runner, not inside the Anthropic container. This means all API secrets stay in GitHub Secrets and never enter the Anthropic platform. The agent only sees the *results* of tool calls, never the credentials.

---

## Files

| File | Purpose |
|---|---|
| `bob_prompts.py` | Single source of truth for Bob's system prompt. Edit this to change his voice. |
| `create_agent.py` | One-time setup: creates the Managed Agents agent and saves its ID. |
| `setup_infra.py` | One-time setup: creates the cloud environment and memory store. |
| `test_session.py` | Manual dry-run with stubbed tools. Safe to run anytime — doesn't post. |
| `fire_bob_session.py` | Production runner. Called by GitHub Actions. Uses real APIs. |
| `.github/workflows/daily-bob.yml` | GitHub Actions cron definition (21:00 UTC). |
| `bob_ids.json` | Local cache of Anthropic resource IDs (git-ignored). |
| `.gitignore` | Ensures `bob_ids.json` and `.env` never reach git. |

---

## Daily cron flow (end-to-end)

```
21:00 UTC
  │
  ├─ GitHub Actions triggers daily-bob.yml
  ├─ Checks out repo, installs anthropic==0.99.0
  └─ Runs fire_bob_session.py with secrets injected as env vars
        │
        ├─ Creates Anthropic session (agent + env + memory store)
        ├─ Sends "Run today's BoB post." to kick off the agent
        └─ Enters streaming event loop:
              │
              ├─ Agent reads used_narratives.json  ← built-in read tool
              ├─ Tool call: fetch_okx_closed_trades ← runner hits OKX API
              ├─ Tool call: fetch_crypto_news       ← runner hits RSS feeds
              ├─ Agent picks narrative, writes slug ← built-in write tool
              ├─ Agent drafts caption + image prompt
              ├─ Tool call: generate_meme_image     ← runner hits Replicate
              ├─ Tool call: send_for_approval       ← runner sends Telegram msg
              │     │
              │     └─ (waits up to 10 min for your reply)
              │           YES → continues
              │           feedback → agent revises, loops back
              │
              ├─ Tool call: post_to_socials         ← runner hits Zernio
              ├─ Agent appends to post_history.json ← built-in write tool
              └─ Session ends (end_turn)
```

---

## Running a manual test

Two options:

**Option A — local dry-run (no real API calls except RSS):**
```bash
cd ~/bob-ai-trading
python3 test_session.py
```
This stubs OKX (fake data), Replicate (placeholder URL), approval (auto-yes), and Zernio (prints caption). RSS feeds are hit live. Safe to run as many times as you want.

**Option B — trigger the real workflow manually:**
1. Push your repo to GitHub
2. Go to **Actions → BoB AI Trading — daily post → Run workflow → Run workflow**
3. Watch the logs live in the Actions tab

For Option B to work all GitHub Secrets must be set (see the Secrets section below).

---

## Updating Bob's voice

**All voice rules live in one place: `bob_prompts.py`.**

```bash
# 1. Edit the prompt
vim bob_prompts.py   # or your editor of choice

# 2. Test it locally
python3 test_session.py

# 3. If happy, push — the next real run picks it up automatically
git add bob_prompts.py && git commit -m "voice tweak: ..."
git push
```

The production script (`fire_bob_session.py`) calls `agents.update()` at the start of every session to push the latest prompt. No agent recreation needed, no IDs change.

Things worth tuning in `bob_prompts.py`:
- Add/remove banned words to the LinkedIn-avoidance rule
- Adjust the bear-identity frequency (currently ~1 in 3)
- Change the caption length target (currently hard limit 240)
- Add seasonal personality shifts ("bear in summer = grill, not hibernation")

---

## Adding Zernio (when your account is ready)

1. Create a Zernio account and connect your X, Instagram, TikTok, and Telegram channel
2. Get your API key from the Zernio dashboard
3. Update the GitHub Secret `ZERNIO_API_KEY` with the real value
4. Verify the Zernio POST endpoint and payload format against their docs, then update `post_to_socials()` in `fire_bob_session.py` if needed

The stub guard in `post_to_socials()`:
```python
if not zernio_key or zernio_key == "placeholder":
    return {"skipped": True, "reason": "ZERNIO_API_KEY not set"}
```
Remove this guard (or set the secret to your real key) and you're live.

---

## Adding new platforms later

To add Discord, LinkedIn, Farcaster, etc.:

1. **In `fire_bob_session.py`**, extend the `post_to_socials()` function or add a new tool handler. The platform list sent to Zernio is just a list — add your new platform name:
```python
"platforms": ["x", "instagram", "tiktok", "telegram", "discord"],
```

2. **If Zernio doesn't support the new platform**, add a direct API call alongside the Zernio call inside `post_to_socials()`.

3. **Add a secret** for any new API key: GitHub repo → Settings → Secrets → add it, then inject it in `daily-bob.yml` under `env:`.

4. **No agent changes needed** — the agent only calls `post_to_socials` with a caption and image URL. Where those go is the runner's problem.

---

## Troubleshooting

**Run failed — where are the logs?**
GitHub Actions → your repo → Actions tab → click the failed run → expand "Run BoB session" step.

**Agent didn't call the right tools / wrong narrative:**
Check the session events. Retrieve a past session:
```python
import anthropic, json
client = anthropic.Anthropic()
events = client.beta.sessions.events.list("sesn_...", order="asc")
for e in events: print(e.type, getattr(e, 'name', ''))
```
The session ID is printed at the start of every run in the Actions log.

**OKX API returning empty trades:**
- Verify the key has `Read` scope in OKX settings (trade history + account balance)
- The copier-count endpoint (`/api/v5/copytrading/public-lead-traders`) requires the account to be an active lead trader — it may return empty until you're enrolled

**Replicate image generation failing:**
- Check your Replicate billing/credits
- `flux-schnell` model may need the model path updated — verify at replicate.com/black-forest-labs/flux-schnell

**Telegram approval timing out:**
The bot polls for 10 minutes. If you miss the window, the run exits cleanly (no post goes out). Next day's run starts fresh.

**Approval replied YES but post didn't go out:**
Zernio is likely still set to `placeholder`. Check the Actions log for `[Zernio not yet configured — skipping social post]`.

**Memory store desync (agent picks a used narrative):**
The memory store is persistent across sessions. If you suspect corruption:
```python
import anthropic
client = anthropic.Anthropic()
# List files in the memory store via a one-off session
# Or reset by creating a new memory store and updating BOB_MEMORY_STORE_ID
```

---

## Cost expectations

| Service | What drives cost | Expected monthly |
|---|---|---|
| Anthropic (Haiku 4.5) | ~1 session/day × ~10k tokens | ~$2–3 |
| Replicate (Flux Schnell) | ~30 images/month × ~$0.01 | ~$0.30 |
| Zernio | subscription (TBD) | check their pricing |
| GitHub Actions | free tier (2,000 min/mo) | $0 |
| OKX API | free | $0 |
| RSS feeds | free | $0 |

Total before Zernio: **under $5/month**.

---

## Security

**What's in GitHub Secrets:**
All API keys — OKX, Replicate, Telegram, Zernio, Anthropic. They are injected as environment variables at runtime and never written to disk or logs.

**What's git-ignored:**
`bob_ids.json` (contains Anthropic resource IDs — not secrets, but no reason to commit). `.env` files.

**Why no Anthropic Vault:**
The Vault API (`client.beta.vaults`) only stores credentials for MCP server authentication (it requires an `mcp_server_url`). Our tools run client-side on the GitHub Actions runner — the runner calls OKX/Replicate/etc. directly, so secrets never need to enter the Anthropic platform. GitHub Secrets is the right layer.

**What the agent can and can't see:**
The agent sees tool *results* only — e.g. a list of trades, a list of headlines, an image URL. It never sees an API key. The runner executes all external calls.
