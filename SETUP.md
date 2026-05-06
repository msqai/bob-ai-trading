# BoB AI Trading — External Account Setup

Complete these three setups before the first real daily run. Each section is a self-contained checklist.

---

## 1. Telegram bot (for approval messages)

You need a Telegram bot that messages **you** (the trader) with each draft post for approval.

### Steps

- [ ] Open Telegram and search for **@BotFather**
- [ ] Send `/newbot`
- [ ] Choose a name: e.g. `BoB AI Trading`
- [ ] Choose a username: e.g. `bob_ai_trading_bot` (must end in `bot`)
- [ ] BotFather replies with your **bot token** — looks like `7123456789:AAF...`
  - Save this as GitHub Secret: `TELEGRAM_BOT_TOKEN`

- [ ] Find your personal Telegram **chat ID**:
  - Start a conversation with your new bot (send it any message)
  - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
  - Look for `"chat":{"id":XXXXXXXXX}` in the JSON — that number is your chat ID
  - Save this as GitHub Secret: `TELEGRAM_CHAT_ID`

- [ ] Test the bot sends to you:
  ```bash
  curl -s "https://api.telegram.org/bot<TOKEN>/sendMessage" \
    -d "chat_id=<CHAT_ID>&text=Bob+test+message"
  ```
  You should receive "Bob test message" in Telegram.

### How approval works

When Bob's draft is ready, your bot sends you a message like:

```
🐻 BoB AI Trading — Draft Post

Caption (163/240):
`Colombia turning its Caribbean coast into a bitcoin...`

Image: https://replicate.delivery/...

Reply YES to post, or reply with feedback to revise.
```

Reply **YES** (case-insensitive) to publish. Reply anything else and Bob treats it as feedback and revises. You have a 10-minute window — after that the run exits cleanly and nothing posts.

---

## 2. Zernio account (for cross-platform posting)

Zernio handles posting to X, Instagram, TikTok, and Telegram channel from a single API call.

### Steps

- [ ] Create an account at [zernio.com](https://zernio.com) (or wherever they direct you)
- [ ] In the Zernio dashboard, connect each platform:
  - [ ] **X (Twitter)** — authorize via OAuth
  - [ ] **Instagram** — authorize via OAuth (requires a Business or Creator account)
  - [ ] **TikTok** — authorize via OAuth
  - [ ] **Telegram channel** — add the Zernio bot as admin to your channel
- [ ] Generate a Zernio API key from the dashboard
  - Save this as GitHub Secret: `ZERNIO_API_KEY`

- [ ] Verify the exact POST endpoint and request format from Zernio docs, then check it matches `post_to_socials()` in `fire_bob_session.py`:
  ```python
  # Current assumed format — update if Zernio's API differs:
  payload = {
      "caption":   caption,
      "image_url": image_url,
      "platforms": ["x", "instagram", "tiktok", "telegram"],
  }
  # POST https://api.zernio.com/v1/post
  # Authorization: Bearer <key>
  ```
  Adjust the endpoint URL, payload shape, or platform names to match their actual API.

- [ ] Do one manual test post via Zernio's own dashboard before enabling the bot — confirm all 4 platforms accept posts from their system.

### Activating in the code

Once `ZERNIO_API_KEY` is set to a real value (not `placeholder`) in GitHub Secrets, the guard in `fire_bob_session.py` disables automatically and posts go live.

---

## 3. GitHub Secrets (final checklist)

Go to: **your repo → Settings → Secrets and variables → Actions**

Add all 11 secrets:

| Secret | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys |
| `BOB_AGENT_ID` | `bob_ids.json` locally: `agent_011Cam38eU86YAaRJscQK5GP` |
| `BOB_ENVIRONMENT_ID` | `bob_ids.json` locally: `env_01CLDC22s6xepptAtnLKt2TW` |
| `BOB_MEMORY_STORE_ID` | `bob_ids.json` locally: `memstore_0121eh7a2p8a63PC2HPN39fX` |
| `OKX_API_KEY` | OKX → Account → API Management (read-only key) |
| `OKX_API_SECRET` | same |
| `OKX_API_PASSPHRASE` | same |
| `REPLICATE_API_TOKEN` | replicate.com → Account → API tokens |
| `TELEGRAM_BOT_TOKEN` | from BotFather (step 1 above) |
| `TELEGRAM_CHAT_ID` | from getUpdates call (step 1 above) |
| `ZERNIO_API_KEY` | set to `placeholder` until step 2 is done |

- [ ] All 11 secrets added
- [ ] Push the repo to GitHub
- [ ] Go to **Actions → BoB AI Trading — daily post → Run workflow** for a first live test
- [ ] Watch the logs — confirm OKX data returns, RSS feeds load, Telegram approval arrives, Zernio skips cleanly (or posts if configured)

---

## Order of operations

1. **Do Telegram first** — approval is required for every post, this blocks everything else
2. **Set all GitHub Secrets** including `ZERNIO_API_KEY=placeholder`
3. **Push the repo and trigger a manual workflow run** — verify OKX + Replicate + Telegram work end-to-end
4. **Do Zernio** when ready — posts start going live once the secret is updated
