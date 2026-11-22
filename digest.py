"""SAH — hub-side digest/batching for non-critical alerts.

Only alerts that pass settings.should_send_telegram() and are NOT critical get
queued here instead of sent immediately. Critical always sends immediately
(app.py never calls queue() for critical). A background thread flushes each
tool's buffer once it's been sitting for >= digest_window_seconds, combining
everything queued for that tool into one Telegram message.

In-memory only: a queued-but-not-yet-flushed alert is lost if the process
restarts. Acceptable here since it's just a delivery-batching convenience —
the alert itself is already in the database and visible on /dashboard.
"""
import threading
import time
import datetime

import settings as settings_mod
import telegram_bot

_lock = threading.Lock()
_buffers = {}  # tool_name -> list of dicts: {severity, message, link, ts}
_thread_started = False


def queue(tool_name, severity, message, link):
    with _lock:
        _buffers.setdefault(tool_name, []).append({
            "severity": severity,
            "message": message,
            "link": link,
            "ts": datetime.datetime.utcnow(),
        })


def _format_digest(tool_name, entries):
    header = f"📦 [{tool_name}] {len(entries)} alerts in the last ~{len(entries)}s window"
    lines = [header]
    for e in entries:
        emoji = telegram_bot.SEVERITY_EMOJI.get(e["severity"], "")
        line = f"{emoji} {e['message']}"
        if e["link"]:
            line += f" — {e['link']}"
        lines.append(line)
    return "\n".join(lines)


def _flush_due(window_seconds):
    now = datetime.datetime.utcnow()
    to_send = []
    with _lock:
        for tool_name in list(_buffers.keys()):
            entries = _buffers[tool_name]
            if not entries:
                continue
            oldest = entries[0]["ts"]
            if (now - oldest).total_seconds() >= window_seconds:
                to_send.append((tool_name, entries))
                _buffers[tool_name] = []
    for tool_name, entries in to_send:
        if len(entries) == 1:
            e = entries[0]
            telegram_bot.send_alert(tool_name, e["severity"], e["message"], e["link"])
        else:
            telegram_bot.send_telegram_text(_format_digest(tool_name, entries))


def _flush_loop():
    while True:
        try:
            s = settings_mod.get_settings()
            window = max(1, int(s.get("digest_window_seconds", 20)))
            _flush_due(window)
        except Exception as e:
            print(f"[digest] flush error: {e}")
        time.sleep(5)


def start_digest_thread():
    global _thread_started
    if _thread_started:
        return
    _thread_started = True
    t = threading.Thread(target=_flush_loop, daemon=True, name="sah-digest-flush")
    t.start()
