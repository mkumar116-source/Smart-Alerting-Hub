# SAH — SPEC

## Purpose
Central Flask tool that aggregates alerts from Kumar's other Flask tools (Auto Backup, Write Guard, FinTracer, LG Energy Dashboard, MediaGapDash, etc.) instead of each tool building its own notification delivery. Delivers via a dedicated Telegram bot. LAN Network Monitor's NetMonBot (interactive approval flow) is untouched and out of scope.

## Integration model
- Each source tool sends alerts via `POST /api/alert` to the hub (direct HTTP, LAN only).
- If the hub is unreachable, the source tool queues the alert in its own local SQLite table and retries later (source-tool responsibility, not built by this project).
- Alerts include both business events (e.g. "backup failed") and each tool's own lifecycle events (`tool_started`, `tool_crashed`).

## Out of scope: secret/credential delivery
This hub is for non-secret operational alerts only. Anything that delivers a credential or one-time secret (e.g. Auto Backup's planned recovery-code delivery) stays on that tool's own separate, direct Telegram bot — not routed through this hub. Reason: hub alerts are persisted in the `alerts` table and shown on `/dashboard`, which has no access control beyond being LAN-only; that's an acceptable exposure for "backup failed" but not for a recovery key.

## API

### POST /api/alert
Headers: `X-Hub-Key: <per-tool key>`
Body:
```json
{
  "alert_key": "backup_failed",
  "severity": "critical",
  "message": "Upload to Drive failed after 3 retries",
  "link": "http://localhost:8508/logs"
}
```
- `tool` is never read from the body — identity comes from the API key.
- `severity` must be one of `info`/`warning`/`critical`.
- `message` capped at 2000 chars, `alert_key` capped at 100 chars.
- Flow: validate key → rate-limit check → dedup check (same tool+alert_key within cooldown window collapses, no re-send) → else insert + send Telegram → always logged to audit table (accepted/deduped/rejected/rate_limited).

### POST /api/alert/test
Same auth. Forces a real Telegram send bypassing dedup, for end-to-end pipeline verification. Not shown in dashboard history by default.

### GET /health
No auth (LAN only). `{"status": "ok"}`. Polled by Write Guard as the hub's own watchdog (see below).

### GET /dashboard
Alert history, filterable by tool/severity.

### GET/POST /admin/keys
Generate a new per-tool API key (shown once). Manual, low-traffic — no key rotation UI in v1.

## Dedup
Same `(tool, alert_key)` within a cooldown window (default 30 min, overridable per `alert_key` in the `alert_config` table) collapses into the existing alert — no re-send, count incremented.

## Security
- Per-tool API keys; hub derives tool identity from the key, never trusts a client-supplied tool name.
- Rate limiting per key (default 60 accepted alerts/hour) — exceeding it logs+rejects rather than delivering.
- Audit log of every request (accepted/deduped/rejected/rate_limited) with timestamp, source IP, tool identity.
- LAN-only exposure, no external port-forwarding (consistent with Kumar's standing no-remote-access stance).

## Delivery
Dedicated Telegram bot, config in `data/config.json` (bot token + list of chat_ids, gitignored). Not committed to git. Live as of 2026-10-17 — bot created, chat_id configured, end-to-end test confirmed delivered.

## Watchdog
Write Guard polls `GET /health` on its existing schedule; if unreachable, Write Guard raises its own alert through its own channel (not through this hub, to avoid circularity).

## Out of scope for v1
- Acknowledge/resolve alert lifecycle (fire-and-forget only)
- Mute/snooze beyond the dedup cooldown
- Email delivery channel
- Homelab Portal integration (dashboard lives here for now)

## Storage
SQLite, `data/sah.db`. Tables: `api_keys`, `alerts`, `alert_audit`, `alert_config`.
