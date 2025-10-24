# Free Fire Info Checker — Telegram Bot (Render)
A minimal Telegram bot that fetches Free Fire profile info using your updated API and serves it via webhook on Render.

## API (updated)
`https://yunus-freefire-api.onrender.com/get_player_personal_show?server=<server>&uid=<uid>`

## What it does
- Accepts `/check <uid> [server]` or just a numeric UID
- Pretty-prints common fields (nickname, uid, level, server, rank, likes, guild, country, bio)

## Quick Deploy (Render)
1. **Create bot** with @BotFather → get the **token**.
2. **Fork/Upload** these files to a new Git repo.
3. In Render, **Create New > Web Service** → connect the repo.
4. Set Environment Variables:
   - `TELEGRAM_TOKEN` = your BotFather token
   - `WEBHOOK_SECRET` = any random string (e.g. `abc123`)
   - `PUBLIC_URL` = the Render URL after service deploys (e.g. `https://your-service.onrender.com`)
   - (optional) `DEFAULT_SERVER` = `sg`
5. Deploy. On startup, the app auto-calls `setWebhook` to `PUBLIC_URL/webhook/WEBHOOK_SECRET`.

> Tip: After the first deploy, copy the Render URL into `PUBLIC_URL` and redeploy so the webhook gets set.

## Local run (for testing)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_TOKEN=YOUR_TOKEN
export WEBHOOK_SECRET=abc123
export PUBLIC_URL=http://localhost:8000   # optional for local webhook
uvicorn main:app --reload
```
Use a tunnel like `cloudflared` or `ngrok` and set the webhook:
```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-tunnel-domain/webhook/abc123","allowed_updates":["message","edited_message"]}'
```

## Usage
- Send: `123456789` → uses default server (`sg`)
- Or: `/check 123456789 sg`
- Reply contains parsed fields; if format changes, the raw JSON is still accepted internally and formatted best-effort.

## Notes
- Simple Markdown response; adjust `format_player_info` as your API evolves.
- Timeout and error handling are implemented.
- Health check: `GET /healthz`.
