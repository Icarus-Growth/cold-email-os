# Architecture: where to find everything

The Cold Email agency OS. One repo holds everything: the database, the screens, the onboarding form,
the automations, the skills and the second brain.

| Folder or file | What is in it |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | The rules for the AI (same text in both, under 150 lines) |
| `SCHEMAS.md` | Every table and column in the live database |
| `DECISIONS.md` | The choices made so far |
| `apps/os/backend/` | The database: `supabase/migrations/` (the change files), `supabase/config.toml` (sign-in settings), `db.py` (a helper to run SQL, check the locks and write `SCHEMAS.md`) |
| `apps/os/frontend/` | The screens (built in tab 2) |
| `apps/os/automations/` | The OS's own automations, one Modal app (`app.py`): Slack alerts, the new client post in new-tasks, the daily summary, the new team member message. `alert_rules.json` says which stage move posts where; `channels.json` holds the channels. The OS never makes or posts in client channels. Set up in tab 3 |
| `apps/os/automations/mcp_server.py` | The AI connector, in the same Modal app: each person's private key (an `Authorization: Bearer` header to `/mcp/`; Claude on the web uses `/mcp/s/<key>/`, which Modal's log keeps), the five tools, the role checks and the `mcp_audit` log. `mcp_actions.py` holds every action; `mcp_actions.json` says which actions and board fields this agency type has. It reads the copy of `second-brain/` made at each deploy (never `inbox/`). Set up in tab 5 |
| `apps/onboarding/` | The onboarding form app (built in tab 2) |
| `.claude/skills/` | Skills the AI can run (any agent: read the `SKILL.md`). `create-client` makes a client's notes folder from `clients/_template/`. `search-client` finds everything about one client: its database rows on every table and its `clients/` notes |
| `shared/` | Code used by more than one skill or app: `slack_notify.py` (every Slack post), `supabase_client.py` (read and write the database from Python) |
| `clients/` | Notes about each of your clients, one folder per client (made by the `create-client` skill). Not linked to the OS |
| `second-brain/` | Your second brain (built in tab 4) |
| `docs/` | The five set-up tabs, the agency process, the Interview change files and the example rows |
| `archive/` | Old files kept for the record. Nothing here runs |
| `tests/` | Checks you can run at any time |

## The boards

Tasks, Campaigns (tables: tasks, campaigns). Other tables with stages: inbox_batches (a list on the client page, no board).
Every stage change on every board is written to the `stage_log` table by the database itself.
