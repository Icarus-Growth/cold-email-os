# Database rules (Cold Email agency OS)

Every rule for the database lives here. `CLAUDE.md` links to this file and holds no rules. Read this before any database work. `SCHEMAS.md` lists every table and column.

## Tables and columns

1. **The wide-table rule.** A new field goes on the parent table as a column. A new table needs proof that one parent has many of the thing.
2. **The parent-columns rule.** A wide table is not a reason to split it. Keep adding columns to the parent (the client, the card) until the work shows that one parent has many of the thing, in what the team does or in the data. Then split, not before.
3. **Column names never name a tool.** The tool is a value in a column (for example `sending_tool = 'X'`), never a column called after the tool.
4. **Keys, tokens and passwords are never stored in a table.** They go in `.env`, which is never committed. Each `.env` line is `NAME=value`: no space before or after "=". `python3 apps/os/backend/db.py keys` checks it.
5. **Nothing is deleted.** A client or a card is archived (`archived_at`), and only an Owner or Admin archives or restores. `public.archive_client(id)` and `public.restore_client(id)` do a whole client.

## Stages and boards

6. **Stages are numbered**, for example "0 - Backlog", "29 - Amendments", "100 - Complete". A number ending in 9 means the work is held: sent back or blocked. "-1 - Rejected" means it will not be done. Only a "100 - ..." stage counts as finished. A live stage ("50 - Live") stays open.
7. **Live cards are open, not stuck.** The open-cards view (`v_open_cards`) marks a live or waiting stage with `is_live`. Those cards show on My Work and on their board, but never in the stuck or late lists.
8. **A change to a stage list** is made in the database AND in `apps/os/frontend/src/agency.config.ts`, in the same order. Then run `python3 tests/config_matches_db.py`. It must say PASS.
9. **A new board** needs its table, its stage list, `lock_table`, `attach_stage_log`, and a line in the open-cards view (with the archive conditions and an `is_live` value). Then the board rules in `OS_BUILD_RULES.md` (screens, alerts, AI connector).

## Access

10. **Only the team can see data.** Every new table: `select public.lock_table('<table>');`. Every new board: `select public.attach_stage_log('<table>');`. Every new view: `with (security_invoker = true)`.
11. **A new column on `team` needs a grant.** Add `grant select (<col>), insert (<col>), update (<col>) on public.team to authenticated;` in the same change file, or the screens cannot read it.

## Changes and commands

12. **A database change is a new file.** Never edit a change file that has already run: write a new one. `supabase migration new <name> --workdir apps/os/backend < /dev/null` (the `< /dev/null` stops it waiting for typed input), then `supabase db push --linked --yes --workdir apps/os/backend`. Then `python3 apps/os/backend/db.py schema` to write `SCHEMAS.md` again.
13. **Database commands.** Load `.env` into the terminal first (`set -a; . ./.env; set +a`). Add `--linked` to every `supabase db push`, `migration repair` and `migration list`, and `--yes` to every `supabase db push`, so no command waits for a keyboard. On a new computer, or after the SQL editor way, run `supabase link --project-ref "$SUPABASE_PROJECT_REF" --workdir apps/os/backend` once first. If Supabase says "Invalid access token" or 401, `SUPABASE_ACCESS_TOKEN` has expired: make a new one (Account, Access Tokens) and replace it in `.env`.
14. **Joining the change files** (tab 1, Step 10) is one command: `sh scripts/join_migrations.sh`. Never join them by hand in the terminal.

## Parts added by the set-up tabs
