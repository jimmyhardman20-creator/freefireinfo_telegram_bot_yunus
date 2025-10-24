#!/usr/bin/env python3
"""
Free Fire Info Checker — Telegram Bot (Render-ready, webhook-based)
Author: ChatGPT

Env vars required:
- TELEGRAM_TOKEN: Telegram Bot token from @BotFather
- WEBHOOK_SECRET: a random string to secure the webhook path (e.g., 'abc123')
- PUBLIC_URL: your public Render URL (e.g., 'https://your-service.onrender.com')

Optional:
- DEFAULT_SERVER: defaults to 'sg'
"""
import json
import logging
import os
import re
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

# --- Config ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
DEFAULT_SERVER = os.getenv("DEFAULT_SERVER", "sg")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is not set")
if not PUBLIC_URL:
    logging.warning("PUBLIC_URL is not set. Webhook will not be auto-configured.")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
API_BASE = "https://yunus-freefire-api.onrender.com/get_player_personal_show"

# --- App ---
app = FastAPI()
logger = logging.getLogger("uvicorn.error")
logging.basicConfig(level=logging.INFO)


# --- Helpers ---
async def tg_request(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{TELEGRAM_API}/{method}"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload)
    try:
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=500, detail=f"Telegram API error: {resp.text[:300]}")
    if not data.get("ok"):
        logger.error("Telegram error: %s", data)
    return data


def build_api_url(uid: str, server: str) -> str:
    from urllib.parse import urlencode
    qs = urlencode({"server": server, "uid": uid})
    return f"{API_BASE}?{qs}"


async def fetch_player(uid: str, server: str) -> Dict[str, Any]:
    url = build_api_url(uid, server)
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
    if r.status_code != 200:
        # Try JSON body
        try:
            body = r.json()
            body_str = json.dumps(body, ensure_ascii=False)
        except Exception:
            body_str = r.text[:500]
        raise HTTPException(status_code=502, detail=f"[HTTP {r.status_code}] {body_str}")
    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid JSON from upstream API.")
    return data


def format_player_info(data: Dict[str, Any]) -> str:
    # Try to extract fields from both top-level and nested "data"
    def getf(d: Dict[str, Any], *keys: str, default: str = "—"):
        for k in keys:
            if k in d:
                return d[k]
            if k.lower() in d:
                return d[k.lower()]
        return default

    root = data
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}

    def g(*keys, default="—"):
        val = getf(root, *keys, default=default)
        if val == "—" and nested:
            val = getf(nested, *keys, default=default)
        return val

    nickname = g("nickname", "name")
    uid = g("uid")
    level = g("level")
    region = g("region", "server")
    rank_ = g("rank", "tier")
    likes = g("likes")
    guild = g("guild", "clan")
    bio = g("signature", "bio")
    country = g("country")

    lines = [
        "🟢 *Free Fire Player Info*",
        f"• *Nickname:* {nickname}",
        f"• *UID:* `{uid}`",
        f"• *Level:* {level}",
        f"• *Region/Server:* {region}",
        f"• *Rank/Tier:* {rank_}",
        f"• *Likes:* {likes}",
        f"• *Guild:* {guild}",
        f"• *Country:* {country}",
        f"• *Bio:* {bio}",
    ]

    # If there are obvious extra fields at root
    extra_keys = [k for k in list(root.keys()) if k not in {"data"} and k.lower() not in {
        "nickname","name","uid","level","region","server","rank","tier","likes","guild","clan","country","signature","bio"
    }]
    if extra_keys:
        lines.append("")
        lines.append("_Other fields available:_ `" + ", ".join(extra_keys[:15]) + "`")

    return "\n".join(lines)


def parse_command(text: str) -> Optional[Dict[str, str]]:
    """
    Accepts:
      /check <uid> [server]
      or a plain UID like "123456789"
    """
    text = (text or "").strip()
    if not text:
        return None

    # /check command
    m = re.match(r"^/check(?:@\w+)?\s+(\d+)(?:\s+([a-z]{2}))?$", text, re.IGNORECASE)
    if m:
        uid = m.group(1)
        server = m.group(2) or DEFAULT_SERVER
        return {"uid": uid, "server": server}

    # plain uid
    m2 = re.match(r"^(\d{6,20})$", text)
    if m2:
        return {"uid": m2.group(1), "server": DEFAULT_SERVER}

    return None


# --- Routes ---
@app.get("/")
async def root():
    return {"status": "ok", "service": "freefire-telegram-bot"}


@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")


@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def telegram_webhook(req: Request):
    update = await req.json()
    message = update.get("message") or update.get("edited_message")
    if not message:
        # Could be callback_query, etc.
        return JSONResponse({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    cmd = parse_command(text)
    if not cmd:
        help_text = (
            "Hi! Send your Free Fire UID to get info.\n\n"
            "Commands:\n"
            "• `/check <uid> [server]` — server default: sg\n"
            "Example: `/check 123456789 sg`\n\n"
            "Servers: try `sg`, `in`, `br` (default: sg)\n"
        )
        await tg_request("sendMessage", {
            "chat_id": chat_id,
            "text": help_text,
            "parse_mode": "Markdown",
        })
        return JSONResponse({"ok": True})

    uid = cmd["uid"]
    server = cmd["server"]
    try:
        data = await fetch_player(uid, server)
        msg = format_player_info(data)
    except HTTPException as e:
        msg = f"⚠️ Error: {e.detail}"

    await tg_request("sendMessage", {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })
    return JSONResponse({"ok": True})


@app.on_event("startup")
async def on_startup():
    # Configure webhook if PUBLIC_URL is set
    if not PUBLIC_URL:
        logger.warning("PUBLIC_URL not set; skipping webhook setup.")
        return
    webhook_url = f"{PUBLIC_URL}/webhook/{WEBHOOK_SECRET}"
    payload = {"url": webhook_url, "allowed_updates": ["message", "edited_message"]}
    res = await tg_request("setWebhook", payload)
    if not res.get("ok"):
        logger.error("Failed to set webhook: %s", res)
    else:
        logger.info("Webhook set to %s", webhook_url)
