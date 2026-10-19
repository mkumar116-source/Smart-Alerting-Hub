# SAH — HANDOVER

**Status (2026-10-13):** First build done (app.py, db.py, telegram_bot.py, templates, SPEC.md, requirements.txt). Not yet run live — needs setup steps below. Code was syntax-checked and route-tested locally (in the dev sandbox) before pushing, not yet tested on kumar-pc itself.

**What this tool is:** Smart Alerting Hub — a central Flask tool that aggregates alerts from Kumar's other Flask tools (Auto Backup, Write Guard, FinTracer, LG Energy Dashboard, MediaGapDash, etc.). LAN Network Monitor's NetMonBot (interactive approval flow) stays separate, untouched.

**Design (full detail in SPEC.md):** source tools POST to `/api/alert` with a per-tool `X-Hub-Key`; hub dedups on (tool, alert_key) with a cooldown (default 30 min), rate-limits per key (default 60/hr), logs every request to an audit table, and delivers via a dedicated Telegram bot. Dashboard at `/dashboard`, API key generation at `/admin/keys`, health check at `/health` (for Write Guard to watch).

**Before first run on kumar-pc:**
1. Create a Telegram bot via BotFather, get its token.
2. Get your chat_id (same method as NETMON's `telegram_get_chat_id.py`, or message the new bot and check `getUpdates`).
3. Run `start.bat` once — it creates `data/config.json` with empty placeholders (bot_token: "", chat_ids: []) and prints a dashboard warning until filled in. Edit that file with the real token/chat_id.
4. Visit `/admin/keys` to generate a key for the first client tool (Write Guard or Auto Backup are the planned pilots).
5. Use `POST /api/alert/test` with that key to confirm the pipeline end-to-end.

**Not yet started:** wiring any actual source tool (Write Guard/Auto Backup) to call this hub's API — that happens from each tool's own chat once this hub is confirmed working.

**Note:** a stray generic `CHANGE_LOG.md`/`BACKLOG.md` (no key prefix) appeared in this folder on 2026-10-12, likely scaffolded by Auto Backup's Jira Sync — Kumar is cleaning these up himself since this chat has no delete capability on kumar-pc. `SAH_CHANGE_LOG.md`/`SAH_BACKLOG.md` are the correct ones.
