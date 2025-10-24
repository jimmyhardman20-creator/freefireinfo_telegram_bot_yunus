#!/usr/bin/env python3
"""
Free Fire Info Checker — Telegram Bot (Render-ready) v2.4
Fixes:
- Telegram formatting error by using HTML parse mode + safe escaping.
- Keeps recursive parsing across nested sections (basicinfo/profileinfo/...).
- Adds /start, GET /webhook/<secret>/test, lifespan webhook setup, and __main__ runner.
"""
import html
import json
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple
from contextlib import asynccontextmanager

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
# PUBLIC_URL optional (used to auto-set webhook)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
API_BASE = "https://yunus-freefire-api.onrender.com/get_player_personal_show"

logger = logging.getLogger("uvicorn.error")
logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: auto-set webhook if PUBLIC_URL provided
    if PUBLIC_URL:
        webhook_url = f"{PUBLIC_URL}/webhook/{WEBHOOK_SECRET}"
        payload = {"url": webhook_url, "allowed_updates": ["message", "edited_message"]}
        try:
            res = await tg_request("setWebhook", payload)
            if not res.get("ok"):
                logger.error("Failed to set webhook: %s", res)
            else:
                logger.info("Webhook set to %s", webhook_url)
        except Exception as e:
            logger.error("Error setting webhook on startup: %s", e)
    else:
        logger.warning("PUBLIC_URL not set; skipping webhook setup.")
    yield

app = FastAPI(lifespan=lifespan)

# --- Telegram helpers ---
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

# --- Upstream API helpers ---
def build_api_url(uid: str, server: str) -> str:
    from urllib.parse import urlencode
    qs = urlencode({"server": server, "uid": uid})
    return f"{API_BASE}?{qs}"

async def fetch_player(uid: str, server: str) -> Dict[str, Any]:
    url = build_api_url(uid, server)
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
    if r.status_code != 200:
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

# --- Recursive search utilities ---
def _norm(s: str) -> str:
    return s.replace("_", "").replace("-", "").lower()

def _search(obj: Any, want: set[str], path: str = ""):
    """Depth-first search for any key in 'want'. Returns (value, path) | None"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            nk = _norm(k)
            if nk in want:
                return v, f"{path}.{k}" if path else k
        # search recursively
        for k, v in obj.items():
            sub = _search(v, want, f"{path}.{k}" if path else k)
            if sub:
                return sub
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            sub = _search(item, want, f"{path}[{idx}]")
            if sub:
                return sub
    return None

def find_first(obj: Any, keys: list[str]):
    want = {_norm(k) for k in keys}
    found = _search(obj, want)
    if not found:
        return "—", None
    val, where = found
    try:
        if isinstance(val, (dict, list)):
            s = json.dumps(val, ensure_ascii=False)[:200]
        else:
            s = str(val)
    except Exception:
        s = str(val)
    return s, where

# --- Formatting (HTML-safe) ---
def h(s: str) -> str:
    return html.escape(s or "")

def format_player_info(data: Dict[str, Any]) -> str:
    # Prefer nested "data" if present
    root = data.get("data") if isinstance(data.get("data"), dict) else data

    nickname, w1 = find_first(root, ["nickname", "name", "playername", "ign"])
    uid, w2 = find_first(root, ["uid", "playerid", "id"])
    level, w3 = find_first(root, ["level", "playerlevel"])
    region, w4 = find_first(root, ["region", "server"])
    rank_, w5 = find_first(root, ["rank", "tier", "ranktier"])
    likes, w6 = find_first(root, ["likes", "likecount"])
    guild, w7 = find_first(root, ["guild", "clan", "guildname", "clanname"])
    country, w8 = find_first(root, ["country", "nationality"])
    bio, w9 = find_first(root, ["signature", "bio", "about"])

    parts = [
        "<b>🟢 Free Fire Player Info</b>",
        f"• <b>Nickname:</b> {h(nickname)}",
        f"• <b>UID:</b> <code>{h(uid)}</code>",
        f"• <b>Level:</b> {h(level)}",
        f"• <b>Region/Server:</b> {h(region)}",
        f"• <b>Rank/Tier:</b> {h(rank_)}",
        f"• <b>Likes:</b> {h(likes)}",
        f"• <b>Guild:</b> {h(guild)}",
        f"• <b>Country:</b> {h(country)}",
        f"• <b>Bio:</b> {h(bio)}",
    ]

    # Field sources (for debugging)
    where = []
    for label, w in [("nickname", w1), ("uid", w2), ("level", w3), ("region", w4), ("rank", w5), ("likes", w6), ("guild", w7), ("country", w8), ("bio", w9)]:
        if w:
            where.append(f"{label}←<code>{h(w)}</code>")
    if where:
        parts.append("")
        parts.append("<i>Fields source:</i> " + ", ".join(where))

    # List top sections
    if isinstance(root, dict):
        keys_preview = ", ".join(list(root.keys())[:20])
        if keys_preview:
            parts.append("")
            parts.append("<i>Sections available:</i> " + h(keys_preview))

    return "\n".join(parts)

# --- Command parsing ---
def parse_command(text: str) -> Optional[Dict[str, str]]:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("/start"):
        return {"cmd": "start"}
    m = re.match(r"^/check(?:@\w+)?\s+(\d+)(?:\s+([a-z]{2}))?$", text, re.IGNORECASE)
    if m:
        uid = m.group(1)
        server = m.group(2) or DEFAULT_SERVER
        return {"cmd": "check", "uid": uid, "server": server}
    m2 = re.match(r"^(\d{6,20})$", text)
    if m2:
        return {"cmd": "check", "uid": m2.group(1), "server": DEFAULT_SERVER}
    return None

# --- Routes ---
@app.get("/")
async def root():
    return {"status": "ok", "service": "freefire-telegram-bot"}

@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")

@app.get(f"/webhook/{WEBHOOK_SECRET}/test")
async def webhook_test():
    return PlainTextResponse("webhook path ok")

@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def telegram_webhook(req: Request):
    try:
        update = await req.json()
    except Exception as e:
        logger.error("Invalid JSON on webhook: %s", e)
        raise HTTPException(status_code=400, detail="invalid json")
    logger.info("Update: %s", json.dumps(update)[:500])

    message = update.get("message") or update.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    cmd = parse_command(text)
    logger.info("Parsed command: %s", cmd)

    if not cmd:
        help_text = (
            "Hi! Send your Free Fire UID to get info.\n\n"
            "Commands:\n"
            "• <b>/check &lt;uid&gt; [server]</b> — server default: sg\n"
            "Example: <b>/check 123456789 sg</b>\n\n"
            "Servers: try <code>sg</code>, <code>in</code>, <code>br</code> (default: <code>sg</code>)\n"
        )
        await tg_request("sendMessage", {"chat_id": chat_id, "text": help_text, "parse_mode": "HTML"})
        return JSONResponse({"ok": True})

    if cmd.get("cmd") == "start":
        msg = "Welcome! Send your Free Fire UID or use <b>/check &lt;uid&gt; [server]</b> (default server: <code>sg</code>)."
        await tg_request("sendMessage", {"chat_id": chat_id, "text": msg, "parse_mode": "HTML"})
        return JSONResponse({"ok": True})

    if cmd.get("cmd") == "check":
        uid = cmd["uid"]
        server = cmd["server"]
        try:
            data = await fetch_player(uid, server)
            msg = format_player_info(data)
        except HTTPException as e:
            msg = f"⚠️ Error: {html.escape(str(e.detail))}"
        await tg_request("sendMessage", {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        return JSONResponse({"ok": True})

    return JSONResponse({"ok": True})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
