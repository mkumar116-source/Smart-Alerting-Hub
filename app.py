"""SAH — Smart Alerting Hub. Central alert receiver/router for Kumar's Flask tools."""
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from werkzeug.serving import WSGIRequestHandler

import auth
import db
import telegram_bot

app = Flask(__name__)

MAX_MESSAGE_LEN = 2000
MAX_ALERT_KEY_LEN = 100


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


class QuietRequestHandler(WSGIRequestHandler):
    """Drops the Flask/Python version details from the Server header."""
    server_version = "Werkzeug"
    sys_version = ""


def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr)


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

    cooldown = db.get_cooldown_minutes(payload["alert_key"])
    existing = db.find_recent_alert(tool_name, payload["alert_key"], cooldown)
    if existing:
        db.bump_alert(existing["id"])
        db.log_audit(ip, tool_name, "deduped", None)
        return jsonify({"status": "deduped", "dedup": True, "count": existing["count"] + 1})

    db.insert_alert(tool_name, payload["alert_key"], payload["severity"],
                     payload["message"], payload["link"])
    telegram_bot.send_alert(tool_name, payload["severity"], payload["message"], payload["link"])
    db.log_audit(ip, tool_name, "accepted", None)
    return jsonify({"status": "sent", "dedup": False})


@app.route("/api/alert", methods=["POST"])
def api_alert():
    return _handle_alert(is_test=False)


@app.route("/api/alert/test", methods=["POST"])
def api_alert_test():
    return _handle_alert(is_test=True)


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
    alerts = db.list_alerts(tool_name=tool_filter, severity=severity_filter)
    tools = db.list_tool_names()
    return render_template(
        "dashboard.html",
        alerts=alerts,
        tools=tools,
        severities=db.VALID_SEVERITIES,
        current_tool=tool_filter,
        current_severity=severity_filter,
        telegram_configured=telegram_bot.is_configured(),
    )


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


if __name__ == "__main__":
    db.init_db()
    telegram_bot.ensure_default_config()
    app.secret_key = auth.get_secret_key()
    app.run(host="0.0.0.0", port=8512, debug=False, request_handler=QuietRequestHandler)
