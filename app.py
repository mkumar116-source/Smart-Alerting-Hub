"""SAH — Smart Alerting Hub. Central alert receiver/router for Kumar's Flask tools."""
from flask import Flask, request, jsonify, render_template

import db
import telegram_bot

app = Flask(__name__)

MAX_MESSAGE_LEN = 2000
MAX_ALERT_KEY_LEN = 100


@app.before_request
def _startup_once():
    pass  # init happens at import time below


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


@app.route("/dashboard", methods=["GET"])
@app.route("/", methods=["GET"])
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
    app.run(host="0.0.0.0", port=8512, debug=False)
