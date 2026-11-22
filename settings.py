"""SAH — delivery-policy settings: severity routing, quiet hours, escalation, digest.

Stored in data/config.json alongside Telegram/auth config. Never clobbers bot_token/
chat_ids/secret_key/admin_password_hash — only adds/updates its own keys.
"""
import json
import os
import datetime

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "config.json")

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

DEFAULTS = {
    "telegram_min_severity": "info",   # send this severity and above to Telegram
    "quiet_hours_enabled": False,
    "quiet_start": "23:00",            # HH:MM, local (kumar-pc) time
    "quiet_end": "07:00",
    "escalation_count": 5,             # re-notify if an alert_key repeats this many
    "escalation_window_minutes": 15,   # ...additional times within this many minutes
    "digest_enabled": False,
    "digest_window_seconds": 20,       # batch non-critical alerts from one tool into
                                        # one Telegram message within this window
}


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def ensure_settings_defaults():
    cfg = _load_config()
    changed = False
    for k, v in DEFAULTS.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    if changed:
        _save_config(cfg)
    return cfg


def get_settings():
    cfg = ensure_settings_defaults()
    return {k: cfg.get(k, v) for k, v in DEFAULTS.items()}


def save_settings(new_values):
    """Merge new_values (any subset of DEFAULTS' keys) into config.json, leaving
    every other key (bot_token, chat_ids, secret_key, admin_password_hash, ...) untouched."""
    cfg = _load_config()
    for k in DEFAULTS:
        if k in new_values:
            cfg[k] = new_values[k]
    _save_config(cfg)


def _parse_hhmm(s):
    h, m = s.split(":")
    return int(h), int(m)


def is_quiet_hours(settings=None, now=None):
    settings = settings or get_settings()
    if not settings.get("quiet_hours_enabled"):
        return False
    now = now or datetime.datetime.now()
    sh, sm = _parse_hhmm(settings["quiet_start"])
    eh, em = _parse_hhmm(settings["quiet_end"])
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if start <= end:
        return start <= now < end
    # window wraps past midnight, e.g. 23:00 -> 07:00
    return now >= start or now < end


def should_send_telegram(severity, settings=None, now=None):
    """Critical always bypasses both the severity floor and quiet hours."""
    if severity == "critical":
        return True
    settings = settings or get_settings()
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK.get(settings["telegram_min_severity"], 0):
        return False
    if is_quiet_hours(settings, now):
        return False
    return True
