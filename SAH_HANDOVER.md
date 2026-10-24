# SAH — HANDOVER

**Status (2026-10-24):** Live on kumar-pc since 2026-10-17. First build (app.py, db.py, telegram_bot.py, templates, SPEC.md, requirements.txt) was syntax-checked and route-tested locally before pushing, then confirmed working end-to-end on kumar-pc: Telegram bot created, `data/config.json` filled in, first API key generated for Write Guard, `POST /api/alert/test` delivered a real Telegram message.

**What this tool is:** Smart Alerting Hub — a central Flask tool that aggregates alerts from Kumar's other Flask tools (Auto Backup, Write Guard, FinTracer, LG Energy Dashboard, MediaGapDash, etc.). LAN Network Monitor's NetMonBot (interactive approval flow) stays separate, untouched.

**Design (full detail in SPEC.md):** source tools POST to `/api/alert` with a per-tool `X-Hub-Key`; hub dedups on (tool, alert_key) with a cooldown (default 30 min), rate-limits per key (default 60/hr), logs every request to an audit table, and delivers via a dedicated Telegram bot. Dashboard at `/dashboard`, API key generation at `/admin/keys`, health check at `/health` (for dependent tools to watch).

**Scope boundary (added to SPEC.md 2026-10-17):** this hub is for non-secret operational alerts only. Anything delivering a credential or one-time secret (e.g. Auto Backup's recovery-code delivery) stays on that tool's own separate, direct Telegram bot — not routed through this hub, since `/dashboard` has no access control beyond being LAN-only.

**Pilot client — Write Guard (confirmed wired, 2026-10-24):** Write Guard sends regression alerts and a one-time `tool_started` alert through this hub, and separately polls this hub's `/health` and alerts through its own channel (not circularly through this hub) if the hub itself is down. Details live in Write Guard's own `RVG_CHANGE_LOG.md`/`RVG_HANDOVER.md`, not here.

**Not yet started:** wiring Auto Backup (still under discussion — recovery-code delivery stays on its own bot regardless) or any other source tool.

**In discussion, not yet built:** a "Router bot" — a second, new, separate Telegram bot that would show a menu of predefined per-tool actions, forward the chosen action to that tool's backend API, and relay the reply. Each tool (including this hub) keeps its own bot as an independent fallback/direct-test channel; NetMonBot stays fully independent. Open questions: exact readiness-tracking mechanism for per-tool actions, and one point in the design discussion that was cut off mid-sentence from Kumar's side, not yet resolved.

**Note on stray generic files:** a generic `CHANGE_LOG.md`/`BACKLOG.md` (no key prefix) appeared in this folder on 2026-10-12, likely scaffolded by Auto Backup's Jira Sync. They were not deleted (this chat has no delete capability on kumar-pc) — instead each got a redirect note added on 2026-10-17 pointing to `SAH_CHANGE_LOG.md`/`SAH_BACKLOG.md` as the authoritative files. They still exist in the folder as pointers only; Kumar can delete them himself whenever convenient.
