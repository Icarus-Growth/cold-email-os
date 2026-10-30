# Cold Email Agency OS: instructions for the AI

This file and `CLAUDE.md` hold the same text, word for word. Claude Code reads `CLAUDE.md`; Codex and
other agents read `AGENTS.md`. When you change one, copy it to the other. Keep both under 150 lines.
Check with `python3 tests/agents_md_check.py`. Add a line here each time a part of the OS is built.

## Where things are

- `ARCHITECTURE.md`: where to find everything in this repo.
- `SCHEMAS.md`: every table and column in the live database. Read it before any database work.
- `DECISIONS.md`: the choices made so far, and what is not built yet.
- `docs/`: the set-up tabs (1 database, 2 OS set-up, 3 automations, 4 second brain, 5 AI connector) and the agency process.
- `apps/os/frontend/`: the OS screens. Put it live again with `python3 apps/os/frontend/tools/deploy.py` (add `--domain <OS address>` only if the OS has its own domain). Add `--dry-run` to see every call first.
- `apps/os/frontend/tools/domain.py`: domains and DNS records. Never buy a domain without the owner's yes to the price.

## Rules

1. **The wide-table rule.** A new field goes on the parent table as a column. A new table needs proof
   that one parent has many of the thing.
2. **Stages are numbered**, for example "0 - Backlog", "29 - Amendments", "100 - Complete". A number
   ending in 9 means the work is held: sent back or blocked. "-1 - Rejected" means it will not be done.
3. **Column names never name a tool.** The tool is a value in a column.
4. **Keys, tokens and passwords never go in a table, a commit or the chat.** They go in `.env`.
5. **Only the team can see data.** Every new table: `select public.lock_table('<table>');`.
   Every new board: `select public.attach_stage_log('<table>');`. Every new view:
   `with (security_invoker = true)`.
6. **Shared code lives in `shared/`.** Code used by two or more skills or apps (for example
   `slack_notify.py` and `supabase_client.py`) goes in `shared/`. Look there before you write a new helper.
7. **Skills** live in `.claude/skills/<name>/SKILL.md`. Any agent can use one: read the `SKILL.md`
   and follow it.
8. **Clients.** Anything specific to the user's own clients will fall in documents housed under
   `clients/<client-name>/`. A new client folder starts as a copy of `clients/_template/`. These notes
   are not linked to the OS or the database.
9. **`archive/`** holds old files. Never run or change anything in it.
10. **Database commands.** Load `.env` into the terminal first (`set -a; . ./.env; set +a`). Add
    `--linked` to every `supabase db push`, `migration repair` and `migration list`. On a new
    computer, or after the SQL editor way, run `supabase link --project-ref "$SUPABASE_PROJECT_REF" --workdir apps/os/backend` once first.
    If Supabase says "Invalid access token" or 401, `SUPABASE_ACCESS_TOKEN` has expired: make a new one (Account, Access Tokens) and
    replace it in `.env`.
11. **Plain words.** Explain what you did in short sentences. No jargon.
12. **A new column on `team` needs a grant.** Add `grant select (<col>), insert (<col>), update (<col>) on public.team to authenticated;` in the same change file, or the screens cannot read it.
13. **No client channel posts.** Nothing is ever posted in a client channel, and the OS never makes a client channel.
14. **The AI connector** is `apps/os/automations/mcp_server.py` (five fixed tools, link check, `mcp_audit`). Every action is in `mcp_actions.py`. Which actions and board fields this type has is in `mcp_actions.json`. A new ability is one action plus its name in `mcp_actions.json`. The five tools never change. It also reads `second-brain/` (the brain.* actions) from the copy made at each deploy, never `inbox/`. After any change to the notes, put the automations app live again: `python3 -m modal deploy apps/os/automations/app.py`.
15. **A new board** needs its table in `alert_rules.json` (boards) and in `mcp_actions.json` (boards: name column, stages, people, work link, fields). Then run the tests. My Work reads `alert_rules.json` to say who acts next on a card: put the OS live again after any change to it.

## Skills

- `create-client`: makes a client's notes folder, `clients/<client-name>/`, from `clients/_template/`. Use it for every new client folder.
- `search-client`: finds everything about one client: its rows on every table and its `clients/` notes. Use it before any work on one client.

## Built so far

- Nothing yet. Start with `docs/1-database.md`.
