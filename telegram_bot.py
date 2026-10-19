"""SAH — minimal Telegram Bot API wrapper for one-way alert delivery.

Not interactive (no polling/buttons) — this hub only ever sends. Config lives in
data/config.json (gitignored): {"bot_token": "...", "chat_ids": [123456]}.
"""
import json
import os
import requests

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "config.json")

SEVERITY_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "🔴"}


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_default_config():
    """Create a placeholder config.json on first run if missing, so setup is obvious."""
    if os.path.exists(CONFIG_PATH):
        return
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"bot_token": "", "chat_ids": []}, f, indent=2)


def is_configured():
    cfg = _load_config()
    return bool(cfg.get("bot_token")) and bool(cfg.get("chat_ids"))


def format_message(tool_name, severity, message, link=None, count=1):
    emoji = SEVERITY_EMOJI.get(severity, "")
    text = f"{emoji} [{tool_name}] {severity.upper()}\n{message}"
    if count > 1:
        text += f"\n(repeated {count}x)"
    if link:
        text += f"\n{link}"
    return text


def send_telegram_text(text):
    """Low-level send to all configured chat_ids. Returns True if at least one send succeeded."""
    cfg = _load_config()
    token = cfg.get("bot_token")
    chat_ids = cfg.get("chat_ids") or []
    if not token or not chat_ids:
        print(f"[telegram_bot] WARNING: not configured (data/config.json) — alert not sent: {text}")
        return False

    ok = False
    for chat_id in chat_ids:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
            if resp.ok:
                ok = True
            else:
                print(f"[telegram_bot] send failed for chat_id={chat_id}: {resp.status_code} {resp.text}")
        except requests.RequestException as e:
            print(f"[telegram_bot] send error for chat_id={chat_id}: {e}")
    return ok


def send_alert(tool_name, severity, message, link=None, count=1):
    return send_telegram_text(format_message(tool_name, severity, message, link, count))


def send_test():
    return send_telegram_text("🧪 Smart Alerting Hub — test message. Pipeline is working.")
