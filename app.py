"""SAH — Smart Alerting Hub. Central alert receiver/router for Kumar's Flask tools."""
import datetime

from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from werkzeug.serving import WSGIRequestHandler

import auth
import db
import digest
import settings as settings_mod
import telegram_bot

app = Flask(__name__)

MAX_MESSAGE_LEN = 2000
MAX_ALERT_KEY_LEN = 100

SNOOZE_CHOICES_HOURS = (2, 8, 24)


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    )
    return response


class QuietRequestHandler(WSGIRequestHandler):
    """Drops the Flask/Python version details from the Server header."""
    server_version = "Werkzeug"
    sys_version = ""


def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr)


def _deliver(tool_name, severity, message, link):
    """Decides whether/how a freshly-accepted (non-dedup) alert reaches Telegram:
    critical -> always immediate. Otherwise gated by settings.should_send_telegram
    (severity floor + quiet hours), then either queued for the digest or sent
    immediately depending on settings.digest_enabled."""
    s = settings_mod.get_settings()
    if severity == "critical":
        telegram_bot.send_alert(tool_name, severity, message, link)
        return
    if not settings_mod.should_send_telegram(severity, s):
        return
    if s.get("digest_enabled"):
        digest.queue(tool_name, severity, message, link)
    else:
        telegram_bot.send_alert(tool_name, severity, message, link)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


def _validate_alert_payload(data):
    alert_key = (data or {}).get("alert_key", "")
    severity = (data or {}).get("severity", "")
    message = (data or {}).get("message", "")
    link = (data or {}).get("link")

    if not alert_key or len(alert_key) > MAX_ALERT_KEY_LEN:
        return None, "invalid alert_key"
    if severity not in db.VALID_SEVERITIES:
        return None, "invalid severity"
    if not message or len(message) > MAX_MESSAGE_LEN:
        return None, "invalid message"
    return {"alert_key": alert_key, "severity": severity, "message": message, "link": link}, None


def _handle_alert(is_test=False):
    api_key = request.headers.get("X-Hub-Key")
    tool_name = db.validate_api_key(api_key)
    ip = _client_ip()

    if not tool_name:
        db.log_audit(ip, None, "rejected", "invalid_api_key")
        return jsonify({"error": "invalid or missing X-Hub-Key"}), 401

    if not db.check_rate_limit(tool_name):
        db.log_audit(ip, tool_name, "rate_limited", None)
        return jsonify({"error": "rate limit exceeded"}), 429

    payload, err = _validate_alert_payload(request.get_json(silent=True))
    if err:
        db.log_audit(ip, tool_name, "rejected", err)
        return jsonify({"error": err}), 400

    if is_test:
        telegram_bot.send_test()
        db.insert_alert(tool_name, payload["alert_key"], payload["severity"],
                         payload["message"], payload["link"], is_test=True)
        db.log_audit(ip, tool_name, "accepted", "test")
        return jsonify({"status": "sent", "dedup": False})

    if db.is_snoozed(payload["alert_key"]):
        db.log_audit(ip, tool_name, "snoozed", None)
        # still record it so the dashboard/count reflects reality, just no Telegram
        existing = db.find_recent_alert(tool_name, payload["alert_key"], db.get_cooldown_minutes(payload["alert_key"]))
        if existing:
            db.bump_alert(existing["id"])
        else:
            db.insert_alert(tool_name, payload["alert_key"], payload["severity"],
                             payload["message"], payload["link"])
        return jsonify({"status": "snoozed", "dedup": bool(existing)})

    cooldown = db.get_cooldown_minutes(payload["alert_key"])
    existing = db.find_recent_alert(tool_name, payload["alert_key"], cooldown)
    if existing:
        updated = db.bump_alert(existing["id"])
        db.log_audit(ip, tool_name, "deduped", None)
        s = settings_mod.get_settings()
        if settings_mod.should_send_telegram(updated["severity"], s) and \
                db.check_escalation(updated, s["escalation_count"], s["escalation_window_minutes"]):
            telegram_bot.send_alert(
                tool_name, updated["severity"],
                f"(escalating — {updated['count']}x so far) {updated['message']}",
                updated["link"],
            )
        return jsonify({"status": "deduped", "dedup": True, "count": updated["count"]})

    db.insert_alert(tool_name, payload["alert_key"], payload["severity"],
                     payload["message"], payload["link"])
    _deliver(tool_name, payload["severity"], payload["message"], payload["link"])
    db.log_audit(ip, tool_name, "accepted", None)
    return jsonify({"status": "sent", "dedup": False})


@app.route("/api/alert", methods=["POST"])
def api_alert():
    return _handle_alert(is_test=False)


@app.route("/api/alert/test", methods=["POST"])
def api_alert_test():
    return _handle_alert(is_test=True)


@app.route("/api/alert/resolve", methods=["POST"])
def api_alert_resolve():
    api_key = request.headers.get("X-Hub-Key")
    tool_name = db.validate_api_key(api_key)
    ip = _client_ip()
    if not tool_name:
        db.log_audit(ip, None, "rejected", "invalid_api_key")
        return jsonify({"error": "invalid or missing X-Hub-Key"}), 401

    data = request.get_json(silent=True) or {}
    alert_key = data.get("alert_key", "")
    if not alert_key or len(alert_key) > MAX_ALERT_KEY_LEN:
        db.log_audit(ip, tool_name, "rejected", "invalid alert_key")
        return jsonify({"error": "invalid alert_key"}), 400

    found = db.resolve_alert(tool_name, alert_key)
    db.log_audit(ip, tool_name, "resolved" if found else "resolve_noop", None)
    return jsonify({"status": "resolved" if found else "no_open_alert"})


@app.route("/set_password", methods=["GET", "POST"])
def set_password():
    if auth.password_is_set():
        return redirect(url_for("login"))
    error = None
    if request.method == "POST":
        pw = request.form.get("password") or ""
        pw2 = request.form.get("password2") or ""
        if len(pw) < 8:
            error = "Password must be at least 8 characters"
        elif pw != pw2:
            error = "Passwords do not match"
        else:
            auth.set_password(pw)
            session["sah_logged_in"] = True
            return redirect(url_for("dashboard"))
    return render_template("set_password.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if not auth.password_is_set():
        return redirect(url_for("set_password"))
    error = None
    if request.method == "POST":
        pw = request.form.get("password") or ""
        if auth.check_password(pw):
            session["sah_logged_in"] = True
            next_url = request.form.get("next") or request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        error = "Incorrect password"
    return render_template("login.html", error=error, next=request.args.get("next", ""))


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("sah_logged_in", None)
    return redirect(url_for("login"))


@app.route("/dashboard", methods=["GET"])
@app.route("/", methods=["GET"])
@auth.login_required
def dashboard():
    tool_filter = request.args.get("tool") or None
    severity_filter = request.args.get("severity") or None
    show_resolved = request.args.get("show_resolved") == "1"
    alerts = db.list_alerts(tool_name=tool_filter, severity=severity_filter, include_resolved=show_resolved)
    tools = db.list_tool_names()
    snoozed = db.list_snoozed_keys()
    return render_template(
        "dashboard.html",
        alerts=alerts,
        tools=tools,
        severities=db.VALID_SEVERITIES,
        current_tool=tool_filter,
        current_severity=severity_filter,
        show_resolved=show_resolved,
        telegram_configured=telegram_bot.is_configured(),
        snoozed=snoozed,
        snooze_choices=SNOOZE_CHOICES_HOURS,
    )


@app.route("/snooze", methods=["POST"])
@auth.login_required
def snooze():
    alert_key = request.form.get("alert_key", "")
    try:
        hours = int(request.form.get("hours", "0"))
    except ValueError:
        hours = 0
    if alert_key and hours in SNOOZE_CHOICES_HOURS:
        until = (datetime.datetime.utcnow() + datetime.timedelta(hours=hours)).isoformat()
        db.set_snooze(alert_key, until)
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/unsnooze", methods=["POST"])
@auth.login_required
def unsnooze():
    alert_key = request.form.get("alert_key", "")
    if alert_key:
        db.set_snooze(alert_key, None)
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/admin/keys", methods=["GET", "POST"])
@auth.login_required
def admin_keys():
    new_key = None
    error = None
    if request.method == "POST":
        tool_name = (request.form.get("tool_name") or "").strip()
        if not tool_name:
            error = "Tool name is required"
        else:
            try:
                new_key = db.create_api_key(tool_name)
            except Exception as e:
                error = f"Could not create key (tool name may already have one): {e}"
    keys = db.list_api_keys()
    return render_template("admin.html", keys=keys, new_key=new_key, error=error)


@app.route("/settings", methods=["GET", "POST"])
@auth.login_required
def settings_page():
    error = None
    if request.method == "POST":
        try:
            new_values = {
                "telegram_min_severity": request.form.get("telegram_min_severity", "info"),
                "quiet_hours_enabled": request.form.get("quiet_hours_enabled") == "on",
                "quiet_start": request.form.get("quiet_start", "23:00"),
                "quiet_end": request.form.get("quiet_end", "07:00"),
                "escalation_count": int(request.form.get("escalation_count", 5)),
                "escalation_window_minutes": int(request.form.get("escalation_window_minutes", 15)),
                "digest_enabled": request.form.get("digest_enabled") == "on",
                "digest_window_seconds": int(request.form.get("digest_window_seconds", 20)),
            }
            if new_values["telegram_min_severity"] not in db.VALID_SEVERITIES:
                raise ValueError("invalid severity")
            settings_mod.save_settings(new_values)
        except (ValueError, TypeError) as e:
            error = f"Invalid value: {e}"
    s = settings_mod.get_settings()
    return render_template("settings.html", s=s, severities=db.VALID_SEVERITIES, error=error)


if __name__ == "__main__":
    db.init_db()
    telegram_bot.ensure_default_config()
    settings_mod.ensure_settings_defaults()
    digest.start_digest_thread()
    app.secret_key = auth.get_secret_key()
    app.run(host="0.0.0.0", port=8512, debug=False, request_handler=QuietRequestHandler)
