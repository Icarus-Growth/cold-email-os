# Tab 1: The database (Cold Email agency OS)

**How to use this tab.** Open this repo's folder (or an empty folder, if you do not have the repo yet) in your AI tool: Claude Code, Codex, or Hermes Agent (an open-source AI agent). Copy everything below the line and paste it in. The AI does the work and tells you when it needs you. Never paste a key or password into the chat: the AI will tell you which file to put it in.

---

You are setting up the database for a cold email agency's operating system. It is one Supabase project that holds everything the agency's OS needs: the team, the clients, the boards, the forms, the calls and the report numbers. It is not one project per client.

Work through the steps below in order. After each step, tell me what you did in one or two short sentences, then go on. Stop and wait for me only where a step says **STOP**. If a command fails, show me the error in plain words and stop. Do not try a different, riskier way on your own.

## The rules (keep these for the whole job, and for every later change)

1. **The wide-table rule.** A new field goes on the parent table as a column. A new table needs proof that one parent has many of the thing.
2. **Stages are numbered.** For example "0 - Backlog", "29 - Amendments", "100 - Complete". A number ending in 9 means the work is held: sent back or blocked. "-1 - Rejected" means it will not be done. Only a "100 - ..." stage counts as finished. A live stage ("50 - Live") stays open. Stages are stored as lists in the database, so they sort in order and show as a dropdown.
3. **Column names never name a tool.** The tool is a value in a column (for example `sending_tool = 'X'`), never a column called after the tool.
4. **Keys, tokens and passwords are never stored in a table**, and never pasted into this chat. They go in the `.env` file, which is never committed.
5. **Only team members can see data.** Every table is locked to signed-in people on the team list. Every saved view reads with the rights of the person asking.
6. **Do not invent tables or columns.** Use only the files already in this repo. If I want something they do not cover, write it down in `DECISIONS.md` under "Not built yet" and keep going.
7. **Every database rule is in `DATABASE_RULES.md`.** Read it now. It holds these rules and the commands for later changes.
8. **Can you run terminal commands?** If yes, use the commands. If no (you can read and write files but not run commands), use the "SQL editor way" in each step: give me one file at a time to paste into the Supabase SQL editor, and wait for me to tell you the result. Anything else you cannot do yourself, give me as a short checklist to do by hand, and wait until I say it is done. Each step says which.

## Step 0. Get the repo and the tools

1. If the repo is not in this folder yet, get it. The repo link is at the top of this Google Doc. Ask me which way:
   - open the link, press "Use this template", pick "Private" to make my own private copy, and give you its address. Then get it into this folder:
     - **This folder is empty** (`ls -A` shows nothing): `git clone <my copy's address> .` (the dot puts it in this folder).
     - **This folder is not empty, or it is already a git repo or worktree** (`git clone ... .` fails in these). Clone into a new folder, then move everything in:
       ```
       git clone <my copy's address> .os-download
       find .os-download -mindepth 1 -maxdepth 1 ! -name .git -exec sh -c 'for p; do n=${p#.os-download/}; [ -e "$n" ] && echo "$n"; done; true' sh {} +
       ```
       The second command lists every name that is in both folders. If it lists anything, **STOP**: delete the `.os-download` folder, show me the list and ask what to do. Nothing is overwritten. If it lists nothing, go on:
       ```
       if [ -e .git ]; then rm -rf .os-download/.git; fi
       find .os-download -mindepth 1 -maxdepth 1 -exec mv {} . \;
       rmdir .os-download
       ```
       The first line keeps this folder's own git (a repo or a worktree) when it has one. These commands work in bash and zsh. On Windows, do the same in PowerShell: clone into `.os-download`, check for names in both folders, then move each item (with `.git` only if this folder has none).
   - or open the link, press Code → Download ZIP, and unzip it into this folder.
2. Check the tools:
   - `python3 --version` must say 3.9 or higher. On Windows the command is `py --version`. Then use `py` in place of `python3` in every command in these tabs.
   - `node --version` must say 20 or higher.
   - `git --version` must work.
   If one is missing or too old, ask me to install it (python.org, nodejs.org, git-scm.com), then check again.
3. The ZIP way only: run `git init`. This repo will hold my agency's process and set-up, so it must be private. Ask me to make a **private** repo on GitHub (github.com/new, "Private") and give you its address. Then run `git remote add origin <the address>`.

**SQL editor way:** give me 1 to 3 as a checklist to do by hand (for example with GitHub Desktop), and wait until I say it is done.

## Step 1. Set up

1. Ask me to make a free Supabase account at supabase.com (if I do not have one) and **one** new project for my agency. I pick a name, a region close to my team, and a database password. The password must be letters and numbers only, because `.env` is loaded into the terminal with `set -a` and some symbols break that. Supabase's "Generate a password" button makes one like that. I save the password myself.
   Tell me this about the free plan, in plain words (Supabase's own pricing page said so in October 2026; check supabase.com/pricing if you can): a free project is paused after about one week with no use. While it is paused, the OS will not load, nobody can sign in, and the onboarding form cannot save answers. To wake it, open the project in the Supabase dashboard and press "Restore project"; it takes a few minutes. The free plan also has no automatic backups. Once real client data is in, the paid Pro plan (see supabase.com/pricing for the price) stops the pausing and adds daily backups.
2. Ask me to copy `.env.example` to `.env` and fill in these values. Tell me where each one is in the Supabase dashboard. Do not ask me to paste them here.
   - `SUPABASE_PROJECT_REF`: the project ID (Project Settings → General). It is a short code, not the web address.
   - `SUPABASE_URL`: the project URL (Project Settings → Data API).
   - `SUPABASE_PUBLISHABLE_KEY` and `SUPABASE_SECRET_KEY`: Project Settings → API Keys.
   - `SUPABASE_DB_PASSWORD`: the password I chose for the project (letters and numbers only).
   - `SUPABASE_ACCESS_TOKEN`: a personal access token. Walk me through the token screen:
     - click my account picture → Account preferences → Access Tokens → Generate token;
     - expiry: 30 days. When it expires, the `supabase` commands stop with "Invalid access token" (or a 401 error). Then make a new token the same way, put it in `.env` in place of the old `SUPABASE_ACCESS_TOKEN` value, and load `.env` again (4 below);
     - Resource access: "Project", then pick my organization and this project;
     - Permissions: pick the preset that gives read and write access. If there is none, set Project to read, Database to read and write, and Application services to read and write;
     - generate it and copy it. It starts with `sbp_`.
   **Write each line as `NAME=value`: no space before or after "=", and no quotes.** A space breaks the value when the terminal loads `.env`, with no clear error.
   Then check: `python3 apps/os/backend/db.py keys`. It prints each name (never a value) and says PASS, or which line to fix and how. Ask me to fix each line it names, then run it again until it says PASS.
3. Install the Supabase command-line tool. On a Mac: `brew install supabase/tap/supabase`. On Windows: `scoop bucket add supabase https://github.com/supabase/scoop-bucket.git` then `scoop install supabase`. If neither works, use `npx --yes supabase` in place of `supabase` in every command below. That needs Node.js: if `npx` is not found, ask me to install Node.js LTS from nodejs.org, then try again.
4. Load `.env` into the terminal, so the tool reads the token and the password from it. Never type a key or password into a command.
   - Mac or Linux: `set -a; . ./.env; set +a`
   - Windows PowerShell: `Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }`
   Do this again in every new terminal. Do not run `supabase login`. If a value looks cut short or the password is refused, the password has a symbol in it: ask me to change it to letters and numbers only (Project Settings → Database → Reset database password), and to put the new one in `.env`.
5. Link the project: `supabase link --project-ref "$SUPABASE_PROJECT_REF" --workdir apps/os/backend` (PowerShell: `$env:SUPABASE_PROJECT_REF`). The tool reads the password from `SUPABASE_DB_PASSWORD`.
6. Install the official Supabase agent skills, so you know Supabase well: `npx --yes skills add supabase/agent-skills`. If that fails, say so and go on. Keep what it adds (`.agents/`, `.claude/skills/`, `skills-lock.json`): they are committed with the rest of the repo.

**SQL editor way:** skip 3 to 6. I will use the SQL editor in the Supabase dashboard (left menu → SQL Editor). Do not open `.env` to check it, because that would show you every key. Instead give me this checklist: "Open `.env`. Every line from `SUPABASE_PROJECT_REF` to `SUPABASE_ACCESS_TOKEN` has something after the `=`. There is no space before or after any `=`. Save it." The `.env` values are still needed later for the OS.

## Step 2. Show me the process, then ask how to build

1. Read `docs/process.md` and show me the process in a short list. Ask: "Is this how your agency works? Anything different?" Note what I say.
2. Then ask: **"Basic (proven, quickest, recommended) or Interview (up to 10 questions, more custom)?"** **STOP** and wait for my answer.

## Step 3. Basic

Apply the change files that are already in `apps/os/backend/supabase/migrations/` (every file in that folder, in number order):

`supabase db push --linked --yes --workdir apps/os/backend`

This makes these boards: **Tasks, Campaigns, Inbox set-ups** (tables: tasks, campaigns, inbox_batches). Other tables with stages: none. Every client gets one column per role: account manager, campaign manager. The report numbers are: emails sent, replies, positive replies, meetings booked, bounce rate.

**SQL editor way:** give me the files in `apps/os/backend/supabase/sql-editor/` one at a time, in number order. I paste each one and press Run. I tell you "Success" or paste the error. Do not give me the next file until the last one worked.

Then go to Step 5.

## Step 4. Interview

Ask me these questions on one question page, not in the chat. Write them to `tools/question-page/out/interview.json` in the shape `tools/question-page/README.md` shows: one question per line below, its `text` the question in quotes, one `single` part with the choices "Yes" and "No", and `dest` set to `decision`. Then run `python3 tools/question-page/make.py tools/question-page/out/interview.json`. If no browser opens, give me the file path it prints. **STOP** until I paste the answers back. A question marked "SKIPPED" or "NOT ANSWERED" counts as No. Never ask more than 10 questions in total.

1. "Do you also sell LinkedIn outreach?" → if the answer is **Yes**: `docs/interview/q1_linkedin.sql`
2. "Do you also do cold calling, or set up SDRs for clients?" → if the answer is **Yes**: `docs/interview/q2_calling.sql`
3. "Do you check inbox health (spam placement, blocklists)?" → if the answer is **Yes**: `docs/interview/q3_inbox_health.sql`
4. "Do clients approve copy before launch?" → if the answer is **Yes**: `docs/interview/q4_client_copy_approval.sql`
5. "Which numbers do you report every week, on top of the basic ones?" → if the answer is **I name one or more extra numbers**: `docs/interview/q5_weekly_numbers.sql`
6. "Does a client ever get more than one person in the same role?" → if the answer is **Yes**: `docs/interview/all_more_than_one_person_per_role.sql`

Each answer switches on only the change written for that answer, after the arrow. Any other answer: skip that file. For each file that is switched on, copy it from `docs/interview/` into `apps/os/backend/supabase/migrations/` with the next free number in front: one higher than the highest number already in that folder (for example, if the highest is `0011_`, use `0012_`, then `0013_`, and so on). Do not change what the file does. The only file you may trim is the "which numbers" file: keep only the two lines for each number I named.

If a switched-on file adds or changes a stage list, the OS screens must match it. Run `python3 tests/config_matches_db.py`. If it fails, make the change it prints in `apps/os/frontend/src/agency.config.ts`, then run it again until it says PASS. (SQL editor way: give me the change to make in that file, and I make it.)

If an answer does not fit any file, do not make up a table. Write it in `DECISIONS.md` under "Not built yet".

Then apply everything (the Basic files and the ones I said yes to):

`supabase db push --linked --yes --workdir apps/os/backend`

**SQL editor way:** still copy each switched-on file into `migrations/` as above (it becomes part of the starting file in Step 10). Then give me every Basic file from `apps/os/backend/supabase/sql-editor/` first, then each switched-on file, one at a time, in the same order.

## Step 5. Add example rows

Add a few fake rows, so the OS has something to show:

`python3 apps/os/backend/db.py run docs/examples/add_examples.sql`

Every example row has `is_example = true`. Tell me that one command removes them all later:

`python3 apps/os/backend/db.py run docs/examples/delete_examples.sql`

**SQL editor way:** I paste `docs/examples/add_examples.sql`.

## Step 6. Lock it

1. Ask me for my full name and email. Add me to the team as the Owner who can sign in:
   `python3 apps/os/backend/db.py add-owner --name "<my name>" --email "<my email>"`
2. Turn off sign-ups (nobody can make their own login; I add people from the OS later):
   `python3 apps/os/backend/db.py signups-off`
3. Every table is already locked to the team by file 0005. Nothing else to do here.

**SQL editor way:** I paste this, with my details in place of the examples (write any apostrophe in a name twice, for example O''Brien): `insert into public.team (full_name, email, access, can_sign_in) values ('Jane Doe', lower('jane@example.com'), 'Owner', true);` For sign-ups: in the dashboard, Authentication → Sign In / Providers → turn off "Allow new users to sign up". Leave the Email provider on.

## Step 7. Check

Run both and show me the result in a short list:

- `python3 apps/os/backend/db.py check`: the tables, the row counts, which tables are locked, which views read as the person asking, where the stage log is on, and the sign-up setting.
- `python3 apps/os/backend/db.py access`: what a signed-in stranger can see. It must say PASS.

If any table is not locked, any view says NO, or the stranger check fails, **STOP** and tell me.

**SQL editor way:** I paste `apps/os/backend/supabase/sql-editor/check.sql` and send you the result. I check the sign-up setting in the dashboard myself.

## Step 8. Write SCHEMAS.md

`python3 apps/os/backend/db.py schema`

This writes `SCHEMAS.md` from the live project, not from the files, so it shows what is really there. It starts with two lines in plain words: which boards this OS has, and where the stage lists are. Read it, and tell me if anything looks wrong.

**SQL editor way:** I paste `apps/os/backend/supabase/sql-editor/schema.sql` and send you the result. Each row says if it is a table column, a view column or a list. You write `SCHEMAS.md` from it, one section per table and per view, with every column, and every list in full. Start it with two plain lines: the boards (Tasks, Campaigns, Inbox set-ups), and that the stage lists are in the last section.

## Step 9. Write DECISIONS.md

Do not keep this chat. Write the result in `DECISIONS.md` instead, under a heading with today's date:

- the tool I used (for example Claude Code, Codex, Hermes) and the way we ran it (terminal or SQL editor);
- Basic or Interview;
- what I said about the process in Step 2;
- every Interview question as one line: the date, the question, my answer, and why (my note, if I added one);
- anything under "Not built yet".

Keep it short and in plain words.

## Step 10. Tidy up

The change files did their job. Join them into one starting file, so the database tool still works for later changes. Then move the old files to `archive/`. One script does all of it. Load `.env` into the terminal first (Step 1, 4), then run:

`sh scripts/join_migrations.sh`

It works the same in bash, zsh and sh. It does this, in order:

1. Joins every change file that ran (`0001_…` and up), in number order, into one starting file: `apps/os/backend/supabase/migrations/<YYYYMMDDHHMMSS>_baseline.sql` (the time now, in UTC). Its first line says where the old files went and how to delete the example rows.
2. Moves the old files to `archive/`: the change files to `archive/migrations/`, `docs/examples/add_examples.sql` to `archive/examples/`, `docs/interview/` to `archive/interview/`, and `apps/os/backend/supabase/sql-editor/` to `archive/sql-editor/`. `docs/examples/delete_examples.sql` stays where it is until I delete the example rows. In a git repo it uses `git mv`, so the history shows a move.
3. Tells the database tool that the old files are replaced by the new one (`supabase migration repair ... --yes`), then checks that the migration list shows the starting file only and that nothing is left to push.

It checks everything before it moves anything. It must end with "PASS". If it says "STOPPED", show me the message. If the stop came at step 3 (for example "Invalid access token"), fix that (Step 1, 2 says how to make a new token), load `.env` again and run the same command again: it carries on from step 3 and does not join twice.

Nothing in `archive/` runs again. It is kept so we can see what was done.

**SQL editor way:**
1. You cannot run the script, so write the starting file yourself, as its step 1 says: `apps/os/backend/supabase/migrations/<YYYYMMDDHHMMSS>_baseline.sql`. First line: "-- Joined from the files in archive/migrations/. To delete the example rows, run docs/examples/delete_examples.sql." Then every change file, in number order, each after a line "-- From <file name>". If you cannot tell the time, ask me for today's date and time in UTC.
2. Give me `apps/os/backend/supabase/sql-editor/mark_baseline.sql` to paste, with the starting file's number in place of `<YYYYMMDDHHMMSS>`. It tells the project that the starting file has already run, so a later change does not run it again. Wait for my "Success". Do not skip this: without it, the first database change your successor makes fails with "already exists".
3. Give me the moves in the script's step 2 as a checklist to do by hand in my file browser, and wait until I say they are done. They are not optional: the database tool would try to run the old files again.
4. Skip the script's step 3. The `mark_baseline.sql` paste did that job.

## Step 11. Update CLAUDE.md and DATABASE_RULES.md

Add a short "Database" part at the end of `DATABASE_RULES.md`, under "Parts added by the set-up tabs":

- `SCHEMAS.md` lists every table and column. Read it before any database work. Run `python3 apps/os/backend/db.py schema` after every change.
- `DECISIONS.md` holds the choices made so far.
- A database change is a new file: `supabase migration new <name> --workdir apps/os/backend < /dev/null` (the `< /dev/null` stops it waiting for typed input, which would freeze an AI), then `supabase db push --linked --yes --workdir apps/os/backend`. Load `.env` into the terminal first.
- `docs/examples/delete_examples.sql` deletes the example rows: `python3 apps/os/backend/db.py run docs/examples/delete_examples.sql`. After that, move it to `archive/examples/` too.
- Every new table: `select public.lock_table('<table>');`. Every new board: `select public.attach_stage_log('<table>');`. Every new view: `with (security_invoker = true)`.

In `CLAUDE.md`, under "Built so far", replace "Nothing yet. Start with `docs/1-database.md`." with one line: "Database: Tasks, Campaigns, Inbox set-ups boards, locked to the team, set up on <date>. See SCHEMAS.md."

`CLAUDE.md` must stay at 50 lines or fewer, and `AGENTS.md` stays one line. Check with `python3 tests/agents_md_check.py`.

**SQL editor way:** count the lines of `CLAUDE.md` yourself (50 or fewer), and check that `AGENTS.md` is still one line. Skip the command.

## Step 12. Tell me we are done

Remind me in one line: on the free plan, the project pauses after about a week with no use; "Restore project" in the Supabase dashboard wakes it.

Give me a short list: the boards I now have, the number of tables, that the stranger check passed, that sign-ups are off, and that `SCHEMAS.md` and `DECISIONS.md` are written. Then commit everything (never `.env`) with the message "Database set up", and tell me the next tab to open: **Tab 2, OS set-up.**

**SQL editor way:** give me the commit as a checklist: "Commit all changed files with the message 'Database set up' in your git tool (for example GitHub Desktop). Check that `.env` is not in the list."
