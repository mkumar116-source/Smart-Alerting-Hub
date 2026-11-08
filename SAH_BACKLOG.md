# SAH — BACKLOG

- [ ] Source-tool retry queue: decide whether/how the hub (or sending tools) retry a failed Telegram delivery instead of silently dropping it. Write Guard deferred this on its own side (RVG-7); still an open design question for the hub's overall delivery contract.
- [ ] Telegram severity-routing decision: should info-level alerts skip Telegram entirely and stay dashboard-only, with only warning/critical pushed to Telegram?
- [ ] Sortable dashboard table columns (per PROJECT_SETUP_TEMPLATE.md's 2026-10-17 convention) — not yet implemented on /dashboard or /admin/keys.
- [ ] Router bot (new, separate, primary Telegram bot with a predefined per-tool action menu forwarding to each tool's backend API) — once design questions are resolved: readiness-tracking mechanism for per-tool actions, and the remaining open point from Kumar's cut-off message in the design discussion.
- [ ] F65 (binds 0.0.0.0): accepted risk, not fixed — restricting to 127.0.0.1 would cut off LAN access (other tools calling the hub, and viewing /dashboard from a phone). Mitigated instead by F66's new password gate. Revisit only if Kumar wants loopback-only.
- [ ] F310 (plain HTTP): accepted risk, not fixed — adding TLS means a self-signed cert plus updating every source tool's hub URL from http:// to https:// (Write Guard now, Auto Backup later). Cross-tool change, not a one-file fix; revisit as its own scoped task if wanted.
