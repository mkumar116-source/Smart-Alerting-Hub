"""SAH — SQLite schema and data-access helpers."""
import sqlite3
import secrets
import datetime
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sah.db")

VALID_SEVERITIES = ("info", "warning", "critical")
DEFAULT_COOLDOWN_MINUTES = 30
DEFAULT_RATE_LIMIT_PER_HOUR = 60


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_column_if_missing(conn, table, coldef):
    col_name = coldef.split()[0]
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL UNIQUE,
            api_key TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            alert_key TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            count INTEGER NOT NULL DEFAULT 1,
            is_test INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_alerts_tool_key ON alerts(tool_name, alert_key);

        CREATE TABLE IF NOT EXISTS alert_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            source_ip TEXT,
            tool_name TEXT,
            result TEXT NOT NULL,
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS alert_config (
            alert_key TEXT PRIMARY KEY,
            cooldown_minutes INTEGER NOT NULL
        );
        """
    )
    # Migrations for columns added after the original schema (SQLite has no
    # "ADD COLUMN IF NOT EXISTS", so check PRAGMA table_info first).
    _add_column_if_missing(conn, "alerts", "resolved_at TEXT")
    _add_column_if_missing(conn, "alerts", "count_at_last_notify INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "alerts", "last_notified_at TEXT")
    _add_column_if_missing(conn, "alert_config", "snoozed_until TEXT")
    conn.commit()
    conn.close()


def now_iso():
    return datetime.datetime.utcnow().isoformat()


# ---------- API keys ----------

def validate_api_key(api_key):
    """Return tool_name for an active key, or None."""
    if not api_key:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT tool_name FROM api_keys WHERE api_key = ? AND active = 1", (api_key,)
    ).fetchone()
    conn.close()
    return row["tool_name"] if row else None


def create_api_key(tool_name):
    """Generate and store a new key for tool_name. Raises if tool_name already has one."""
    key = secrets.token_urlsafe(32)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO api_keys (tool_name, api_key, active, created_at) VALUES (?, ?, 1, ?)",
            (tool_name, key, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return key


def list_api_keys():
    conn = get_db()
    rows = conn.execute(
        "SELECT tool_name, active, created_at FROM api_keys ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- Rate limiting ----------

def check_rate_limit(tool_name, limit_per_hour=DEFAULT_RATE_LIMIT_PER_HOUR):
    """Return True if tool_name is under its hourly accepted-alert limit."""
    conn = get_db()
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM alert_audit WHERE tool_name = ? AND result = 'accepted' AND timestamp > ?",
        (tool_name, cutoff),
    ).fetchone()
    conn.close()
    return row["n"] < limit_per_hour


# ---------- Cooldown / dedup ----------

def get_cooldown_minutes(alert_key):
    conn = get_db()
    row = conn.execute(
        "SELECT cooldown_minutes FROM alert_config WHERE alert_key = ?", (alert_key,)
    ).fetchone()
    conn.close()
    return row["cooldown_minutes"] if row else DEFAULT_COOLDOWN_MINUTES


def set_cooldown_minutes(alert_key, minutes):
    conn = get_db()
    conn.execute(
        "INSERT INTO alert_config (alert_key, cooldown_minutes) VALUES (?, ?) "
        "ON CONFLICT(alert_key) DO UPDATE SET cooldown_minutes = excluded.cooldown_minutes",
        (alert_key, minutes),
    )
    conn.commit()
    conn.close()


def find_recent_alert(tool_name, alert_key, cooldown_minutes):
    """Only matches an open (not resolved) alert within the cooldown window."""
    conn = get_db()
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=cooldown_minutes)).isoformat()
    row = conn.execute(
        "SELECT * FROM alerts WHERE tool_name = ? AND alert_key = ? AND last_seen_at > ? "
        "AND resolved_at IS NULL ORDER BY last_seen_at DESC LIMIT 1",
        (tool_name, alert_key, cutoff),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_alert(tool_name, alert_key, severity, message, link, is_test=False):
    conn = get_db()
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO alerts (tool_name, alert_key, severity, message, link, count, is_test, "
        "first_seen_at, last_seen_at, count_at_last_notify, last_notified_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 1, ?)",
        (tool_name, alert_key, severity, message, link, 1 if is_test else 0, ts, ts, ts),
    )
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id


def bump_alert(alert_id):
    """Increments count and returns the updated row (for escalation checks)."""
    conn = get_db()
    conn.execute(
        "UPDATE alerts SET count = count + 1, last_seen_at = ? WHERE id = ?",
        (now_iso(), alert_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_notified(alert_id, count):
    conn = get_db()
    conn.execute(
        "UPDATE alerts SET count_at_last_notify = ?, last_notified_at = ? WHERE id = ?",
        (count, now_iso(), alert_id),
    )
    conn.commit()
    conn.close()


def check_escalation(alert_row, escalation_count, escalation_window_minutes):
    """Given a just-bumped alert row, decide whether it has repeated often enough,
    recently enough, to re-notify even though it's still inside its cooldown.
    If it escalates, records the new notify baseline so the next check starts fresh."""
    last_notified_at = alert_row.get("last_notified_at")
    if not last_notified_at:
        return False
    delta_count = alert_row["count"] - alert_row["count_at_last_notify"]
    if delta_count < escalation_count:
        return False
    last_dt = datetime.datetime.fromisoformat(last_notified_at)
    minutes_since = (datetime.datetime.utcnow() - last_dt).total_seconds() / 60.0
    if minutes_since > escalation_window_minutes:
        return False
    mark_notified(alert_row["id"], alert_row["count"])
    return True


# ---------- Resolve ----------

def resolve_alert(tool_name, alert_key):
    """Marks the latest open alert for (tool_name, alert_key) resolved. Returns True if one was found."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM alerts WHERE tool_name = ? AND alert_key = ? AND resolved_at IS NULL "
        "ORDER BY last_seen_at DESC LIMIT 1",
        (tool_name, alert_key),
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("UPDATE alerts SET resolved_at = ? WHERE id = ?", (now_iso(), row["id"]))
    conn.commit()
    conn.close()
    return True


# ---------- Snooze ----------

def set_snooze(alert_key, until_iso):
    conn = get_db()
    conn.execute(
        "INSERT INTO alert_config (alert_key, cooldown_minutes, snoozed_until) "
        "VALUES (?, ?, ?) ON CONFLICT(alert_key) DO UPDATE SET snoozed_until = excluded.snoozed_until",
        (alert_key, DEFAULT_COOLDOWN_MINUTES, until_iso),
    )
    conn.commit()
    conn.close()


def get_snoozed_until(alert_key):
    conn = get_db()
    row = conn.execute(
        "SELECT snoozed_until FROM alert_config WHERE alert_key = ?", (alert_key,)
    ).fetchone()
    conn.close()
    return row["snoozed_until"] if row and row["snoozed_until"] else None


def is_snoozed(alert_key):
    until = get_snoozed_until(alert_key)
    if not until:
        return False
    return datetime.datetime.fromisoformat(until) > datetime.datetime.utcnow()


def list_snoozed_keys():
    """Returns {alert_key: snoozed_until_iso} for every key currently snoozed."""
    conn = get_db()
    now = now_iso()
    rows = conn.execute(
        "SELECT alert_key, snoozed_until FROM alert_config WHERE snoozed_until IS NOT NULL AND snoozed_until > ?",
        (now,),
    ).fetchall()
    conn.close()
    return {r["alert_key"]: r["snoozed_until"] for r in rows}


# ---------- Audit ----------

def log_audit(source_ip, tool_name, result, reason=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO alert_audit (timestamp, source_ip, tool_name, result, reason) VALUES (?, ?, ?, ?, ?)",
        (now_iso(), source_ip, tool_name, result, reason),
    )
    conn.commit()
    conn.close()


# ---------- Dashboard queries ----------

def list_alerts(tool_name=None, severity=None, include_test=False, include_resolved=False, search=None, limit=200):
    conn = get_db()
    query = "SELECT * FROM alerts WHERE 1=1"
    params = []
    if not include_test:
        query += " AND is_test = 0"
    if not include_resolved:
        query += " AND resolved_at IS NULL"
    if tool_name:
        query += " AND tool_name = ?"
        params.append(tool_name)
    if severity:
        query += " AND severity = ?"
        params.append(severity)
    if search:
        query += " AND (message LIKE ? ESCAPE '\\' OR alert_key LIKE ? ESCAPE '\\')"
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params.append(like)
        params.append(like)
    query += " ORDER BY last_seen_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_tool_names():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT tool_name FROM alerts ORDER BY tool_name").fetchall()
    conn.close()
    return [r["tool_name"] for r in rows]
