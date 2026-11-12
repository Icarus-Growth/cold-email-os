# Architecture: where to find everything

The Cold Email agency OS. One repo holds everything: the database, the screens, the onboarding form,
the automations, the skills and the second brain.

| Folder or file | What is in it |
|---|---|
| `CLAUDE.md` | The instructions file for every AI: about the business, the team, where things live (50 lines at most) |
| `AGENTS.md` | One line that points to CLAUDE.md |
| `OS_BUILD_RULES.md` | Every build rule |
| `DATABASE_RULES.md` | Every database rule |
| `tools/question-page/` | Question pages: the AI asks its questions on one page, and you paste the answers back |
| `SCHEMAS.md` | Every table and column in the live database |
| `DECISIONS.md` | The choices made so far |
| `apps/os/backend/` | The database: `supabase/migrations/` (the change files), `supabase/config.toml` (sign-in settings), `db.py` (a helper to run SQL, check the locks and write `SCHEMAS.md`) |
| `apps/os/frontend/` | The screens (built in tab 2) |
| `apps/os/automations/` | The OS's own automations, one Modal app (`app.py`): Slack alerts, the new client post in new-tasks, the daily summary, the new team member message. `alert_rules.json` says which stage move posts where; `channels.json` holds the channels. The OS never makes or posts in client channels. Set up in tab 3 |
| `apps/os/automations/mcp_server.py` | The AI connector, in the same Modal app: each person's private key (an `Authorization: Bearer` header to `/mcp/`; Claude on the web uses `/mcp/s/<key>/`, which Modal's log keeps), the five tools, the role checks and the `mcp_audit` log. `mcp_actions.py` holds every action; `mcp_actions.json` says which actions and board fields this agency type has. It reads the copy of `second-brain/` made at each deploy (never `inbox/`). Set up in tab 5 |
| `apps/onboarding/` | The onboarding form app (built in tab 2) |
| `skills/` | Skills the AI can run (any agent: read the `SKILL.md`). `fulfilment/` is the team's delivery work, `owner/` is for the Owner and Admins, `global/` is for everyone. `scaffold` makes a new skill. `create-client` makes a client's notes folder from `clients/_template/`. `search-client` finds everything about one client. `tools/sync_skills.py` links each one into `.claude/skills/` so Claude Code finds it (the links are never committed) |
| `shared/` | Code used by more than one skill or app: `slack_notify.py` (every Slack post), `supabase_client.py` (read and write the database from Python) |
| `clients/` | Notes about each of your clients, one folder per client (made by the `create-client` skill). Not linked to the OS |
| `second-brain/` | Your second brain (built in tab 4) |
| `docs/` | The set-up tabs (1 to 5), the build-an-automation guide (6), the GitHub tab (7), the agency process, the Interview change files and the example rows |
| `archive/` | Old files kept for the record. Nothing here runs |
| `tests/` | Checks you can run at any time |

## The boards

Tasks, Campaigns, Inbox set-ups (tables: tasks, campaigns, inbox_batches). Other tables with stages: none.
Every stage change on every board is written to the `stage_log` table by the database itself.
