"""SAH — simple session-based login gate for the browser pages (/dashboard, /admin/keys).

Password is stored as a hash in data/config.json (gitignored), alongside the Telegram
config telegram_bot.py manages. This file never touches bot_token/chat_ids and never
overwrites an existing admin_password_hash.

/health and /api/alert* are NOT gated by this — those are the programmatic endpoints
source tools call with their own X-Hub-Key, not a browser session.
"""
import json
import os
import secrets
from functools import wraps

from flask import session, request, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "config.json")


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def ensure_auth_defaults():
    """Make sure config.json has a secret_key and an admin_password_hash field,
    even on a config file created before this feature existed. Idempotent;
    never overwrites an existing admin_password_hash or Telegram settings."""
    cfg = _load_config()
    changed = False
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        changed = True
    if "admin_password_hash" not in cfg:
        cfg["admin_password_hash"] = ""
        changed = True
    if changed:
        _save_config(cfg)
    return cfg


def get_secret_key():
    return ensure_auth_defaults()["secret_key"]


def password_is_set():
    return bool(_load_config().get("admin_password_hash"))


def set_password(new_password):
    cfg = _load_config()
    cfg["admin_password_hash"] = generate_password_hash(new_password)
    _save_config(cfg)


def check_password(candidate):
    stored = _load_config().get("admin_password_hash")
    if not stored:
        return False
    return check_password_hash(stored, candidate)


def is_logged_in():
    return session.get("sah_logged_in") is True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not password_is_set():
            return redirect(url_for("set_password"))
        if not is_logged_in():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped
