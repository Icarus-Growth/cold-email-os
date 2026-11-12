---
name: search-client
description: Finds everything about one client - its row in the OS database, its cards on every board, its calls, forms, report numbers and stage history, and its notes in clients/<client-name>/ - from a name, part of a name, an email or a row id. Read only. Use when the user asks "what do we have on <client>?", "find <client>", "which client is this email?", "what is going on with <client>?" or before any work on one client.
area: global
agency: all
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY]
runs_on: either
---

# Search client

Finds one client and gathers what the repo and the database know about them. Any agent can follow
these steps: they are plain commands, run from the repo root. It only reads; it never changes a row
or a file.

It needs `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in `.env` to read the database (tab 1). Without
them, it searches only the `clients/` folders and says so.

## How it finds the client

1. **Sure matches first:** the same name (case, dots and words such as "Inc" or "Ltd" do not
   count), the same email, an email on the client's own domain, or a name listed in the client's
   `clients/<client-name>/about.md` (its other names, short forms and sub-brands).
2. **Close matches only when there is no sure match:** a name spelled nearly the same, or one that
   holds the words searched for. A close match is always marked "check it".
3. **Two or more matches:** it lists them and stops. It never picks one by itself.

A database row and a notes folder with the same name are the same client.

## Steps

1. Take what the user gave: a name (or part of one), an email, or the client's row id.
2. Run one of:
   - `python3 skills/global/search-client/scripts/search_client.py "Acme"`
   - `python3 skills/global/search-client/scripts/search_client.py --email jane@example.com`
   - `python3 skills/global/search-client/scripts/search_client.py --id <row id>`
3. If it lists more than one client, show the list and ask which one. Then run it again with the
   full name or `--id`.
4. If the match says "check it", ask the user if it is the right client before you go on.
5. Read the result. It holds:
   - the client in the OS: status, onboarding stage, contact, links, and who is in each role, with
     the link to the client's page in the OS;
   - every table with the client's rows: each board's cards (with stage, people, due date and a link
     to the card), calls, onboarding forms, daily and weekly numbers, and the stage history;
   - the files in `clients/<client-name>/`. Read `about.md` and any other file the question needs.
6. Answer the user's question from it, in a few short lines. Name the source of each fact (the OS,
   or which notes file). If something is missing, say so; do not guess.

More detail when needed: `--full` shows every column of every row (and every row, not only the first
25). `--json` prints the same as JSON for another script. `--files-only` skips the database.

## Keep the notes in step

- No `clients/` folder for the client: offer to make one with the create-client skill.
- A new name, email or domain for the client turned up: add it to its `about.md`, under "Other names
  for this client", so the next search finds it.
