# SAH — CHANGE_LOG

| Date | Change | Jira |
|---|---|---|
| 2026-10-11 | Project created: folder, core files (CHANGE_LOG, HANDOVER, BACKLOG, NOTES, .gitignore, start.bat) scaffolded at D:\Flask Tools\smart-alerting-hub. Port 8512 assigned. Discussion-phase, no code yet. | |
| 2026-10-13 | SPEC.md written (agreed design: push-based alert ingestion, per-tool API keys, dedup/cooldown, rate limiting, audit log, dedicated Telegram bot, lean dashboard). First build: db.py (SQLite schema + helpers), telegram_bot.py (one-way send wrapper), app.py (POST /api/alert, POST /api/alert/test, GET /health, GET /dashboard, GET+POST /admin/keys), templates/base+dashboard+admin.html, requirements.txt. Syntax-checked and route-tested locally before push; verified on-device via re-stage+size-check after commit. Not yet run live on kumar-pc — needs venv/pip install and a Telegram bot token in data/config.json before first run. | |
| 2026-10-17 | First-run setup completed live on kumar-pc: start.bat run (venv/deps installed, data/sah.db created), Telegram bot created via BotFather, chat_id found via new get_chat_id.py helper, data/config.json filled in with bot_token+chat_id. First API key generated via /admin/keys for "write-guard". POST /api/alert/test confirmed end-to-end: 200 {"status":"sent","dedup":false} and the Telegram message was received live. Pipeline confirmed fully working. | |
