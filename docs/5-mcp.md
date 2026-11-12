# Tab 5: The AI connector (Cold Email agency OS)

**How to use this tab.** Do tabs 1 to 3 first: the connector runs in the automations app from tab 3. Open this repo's folder in your AI tool and paste everything below the line. This tab needs an AI that can run terminal commands (for example Claude Code or Codex). Never paste a key, token, password or connector link into the chat.

---

You are putting my agency OS's AI connector online. With it, each person in my agency works on their own cards from their own AI: Claude on the web, Claude Code, Codex or Hermes (Hermes Agent, an open-source AI agent). They ask what is most urgent, read a card, check the agency's second brain, run the team's skills, and hand the work back to the OS, without opening the app. It is an MCP server that is already built into the automations app (`apps/os/automations/mcp_server.py` and `mcp_actions.py`). You put it online and connect it; you do not write new code.

Work through the steps below in order. After each step, tell me what you did in one or two short sentences, then go on. Stop and wait for me only where a step says **STOP**. If a command fails, show me the error in plain words and stop.

## The rules (keep these for the whole job)

1. **A connector key is a password.** Each person has their own key, made by the "Connect your AI" button and shown once. The box also shows a link for Claude on the web, which holds the same key. The OS keeps only a scrambled copy, never the key. Never ask for a key or a link in the chat, never write one in a file in this repo, and never post one in Slack. If a key leaks, an Owner or Admin presses "Revoke" on that person's page. Claude Code, Codex and Hermes send the key in a header, which no log keeps. Modal's own log keeps the address of every request, so the Claude on the web link (`/mcp/s/...`) is in that log. Read the log only with `python3 apps/os/automations/logs.py`, which hides the links and keys, and never paste log lines into a chat.
2. **The AI acts as the person who owns the key.** "My work" means their cards. A Member can do only what a Member can do in the app. The team-wide urgent list, changes to a client, writing a client page document and the owner skills are for Owners and Admins.
3. **Nothing is deleted through the connector.** It cannot manage the team, keys or sign-in settings. A card moved through it writes the same stage log as the app, so the Slack alerts fire the same way.
4. **Every call is logged** in the `mcp_audit` table: who, which action, when, and whether it worked. Every revoke is logged too, as a `revoked` row.
5. **Load `.env` into the terminal first**, in every new terminal: Mac or Linux `set -a; . ./.env; set +a`. Windows PowerShell: `Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }`.

## What the connector can do

The AI sees five tools: list actions, describe an action, run a read, run a change, and check a long job. Every ability is an action (the list for this agency type is in `apps/os/automations/mcp_actions.json`). Every action that gets or reads one thing takes its `id`.

- **Read:** `my_queue` (my open cards, most urgent first: late, then due today, then waiting for my review, then the longest without a move), `urgent` (the whole team, Owners and Admins), `boards`, `cards.search`, `cards.get` (with its history and the first 500 characters and word count of each document), `clients.get` (with its client page documents), `team` (with each person's load), `calls.get`, `forms.get`, `metrics.get`.
- **Second brain (read only, everyone):** `brain.index`, `brain.list` (every note, or one area's), `brain.map` (one area), `brain.search` (20 notes at most), `brain.read` (one note). The AI reads the notes before work that needs judgment and names the notes it used, or says "the second brain has nothing on <subject>". It reads the copy of `second-brain/` that the deploy puts in the app (never `inbox/` or `raw/`), so after you change notes, deploy again (Step 7).
- **Skills:** `skills.list` and `skills.read` (a skill's steps and its files). Everyone sees the skills in `skills/fulfilment/` and `skills/global/`. Only Owners and Admins see `skills/owner/` (sales and deals). The connector reads the copy of `skills/` made at the last deploy.
- **Documents (the copy, scripts and briefs written in the OS):** `docs.read` gives one document in full, as Markdown, with its version and word count. `docs.write` saves the whole new text: everyone on card documents, Owners and Admins on client page documents. The AI must give the version it read. If someone saved after that, nothing is saved, and the AI is told to read it again and redo its change. A pasted link ("paste a link instead") is shown as it is; the AI cannot open it.
- **Change:** `cards.create`, `cards.move`, `cards.update` (due date, links, notes, work link), `cards.note` (a dated note), `calls.add`, `metrics.add`, and `clients.update` (Owners and Admins).
- **Any table:** `db.read` and `db.write` read and change rows in any table, for what the named actions do not cover. They run as the person, never as the server: the connector signs the person in, and the database's own rules decide. A Member cannot change what the app does not let a Member change. Nothing can be deleted.
- Every read gives at most 100 rows, with a "next page" pointer. Archived clients and cards are left out.

## Step 1. Check the database is ready

Run `python3 apps/os/backend/db.py query "select to_regclass('public.mcp_audit') is not null as log_ready, exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'team' and column_name = 'mcp_token_hash') as links_ready"`. Both must be true. Then run `python3 apps/os/backend/db.py query "select to_regclass('public.documents') is not null as docs_ready, to_regprocedure('public.save_document(uuid,integer,text,integer,uuid)') is not null as save_ready"`. Both must be true too. If not, tab 1 is not finished: apply each missing change file once with `python3 apps/os/backend/db.py run <the file>` (the files are in `apps/os/backend/supabase/migrations/`, or in `archive/migrations/` after the tab 1 tidy-up, as in tab 3 Step 8.1), then run this again.

## Step 2. The key secret

1. Check that `.env` has `MCP_TOKEN_PEPPER` and `SUPABASE_PUBLISHABLE_KEY` filled in (do not print them): `python3 -c "import re;t=open('.env').read();print([k for k in ('MCP_TOKEN_PEPPER','SUPABASE_PUBLISHABLE_KEY') if not re.search('^'+k+'=.+',t,re.M)] or 'both set')"`.
2. If `MCP_TOKEN_PEPPER` is empty, make it: `python3 apps/os/automations/connect_db.py secret`. It makes only what is missing. Never make the pepper again once it is set: a new one stops every key. If `SUPABASE_PUBLISHABLE_KEY` is empty, tab 1 is not finished: it is the publishable key from the Supabase project's API Keys page.
3. Load `.env` again (rule 5). Store the Modal secret again with the same command as tab 3 Step 7.5, which includes `MCP_TOKEN_PEPPER` and `SUPABASE_PUBLISHABLE_KEY`. Do not print the values.

## Step 3. Put it online

1. Deploy: `python3 -m modal deploy apps/os/automations/app.py`. The connector is in the same web address as the automations (`OS_AUTOMATIONS_URL`). The deploy also puts a copy of `second-brain/` and `skills/` in the app. If it fails with "reached limit of 5 scheduled functions", do what tab 3 Step 7.6 says.
2. Check it: `python3 apps/os/automations/mcp_check.py`. All three lines must say PASS: the connector answers with its five tools, a made-up key sees nothing, and making a key without the shared secret is turned away.
3. The "Connect your AI" button calls the automations app through the OS. The OS already has `OS_AUTOMATIONS_URL` and `OS_SHARED_SECRET` from tab 3 Step 7.8. If a button says "The AI connector is not set up yet", do that step for the OS project, then deploy the OS again.

## Step 4. Connect my own AI

1. Ask me to open the OS, go to Team, open my own page and press **Connect your AI**. The box shows, once: the link for Claude on the web, the server address and my key. The screen shows the key and the link only as dots and their last 4 characters, so a screenshot never holds them: I use each line's **Copy** button, not a screenshot. I copy the key and the link into my password manager. The server address is not secret: it is `OS_AUTOMATIONS_URL` followed by `/mcp/`.
2. Tell me the steps for my AI tool. I do them myself, in a terminal window or settings page, not in this chat. In each line, `<server>` is the server address, `<key>` is my key and `<link>` is the link for Claude on the web. The address works with or without the `/` at the end.
   - **Claude on the web (claude.ai):** Settings, Connectors, Add custom connector. Name: Agency OS. Pick "No sign-in". Paste this link as the URL: `<link>`. The link holds the key. Leave the OAuth Client ID and Client Secret empty, then press Add. Modal's log keeps this link. Use it only if nobody else can open your Modal account. Custom connectors work on the Free (one connector at most), Pro and Max plans. On a Team or Enterprise plan only a Claude Owner can add one, for the whole Claude organization, so everyone there would act as you: use Claude Code, Codex or Hermes instead.
   - **Claude Code:** `claude mcp add --transport http --scope user agency-os "<server>" --header "Authorization: Bearer <key>"`
   - **Codex:** add these three lines to `~/.codex/config.toml`: `[mcp_servers.agency_os]`, then `url = "<server>"`, then `http_headers = { "Authorization" = "Bearer <key>" }`. Then restart Codex.
   - **Hermes:** add to `~/.hermes/config.yaml`, under `mcp_servers:`, an entry `agency_os:` with `url: "<server>"` and, under it, `headers:` with `Authorization: "Bearer <key>"`. Then restart Hermes. Check it with `hermes mcp test agency_os`.
   - **Any other AI tool:** if it lets you add a header but not "Authorization", use the address `"<server>"` with the header `x-auth-token: <key>`. If it takes only an address, use `<link>`, as for Claude on the web.
3. **STOP** and wait until I say it is connected.

## Step 5. Test it

1. Ask me to open a new chat in my AI tool and ask: **"What is most urgent for me?"** It should call `list_actions` first (some AI tools go straight to `my_queue`, which is fine), then `my_queue`, and answer with my open cards in order (late first), each with a link that opens the card in the OS. Ask me what it said.
2. Show me the log: `python3 apps/os/backend/db.py query "select a.created_at, t.full_name, a.action, a.ok from public.mcp_audit a left join public.team t on t.id = a.team_id order by a.id desc limit 5"`. My name and `my_queue` must be there.
3. A change: ask me to tell my AI to move one example card to the next stage. Then tell me where to look: "Open the card in the OS. It is at the new stage. Open Slack, channel <the channel `alert_rules.json` names for that stage>. You should see a post with the card's name, the new stage and an Open the card button." (The bot cannot read Slack, so I look.) Then ask me to move it back.
4. A document: ask me to tell my AI "Open a document on one of the example cards and add one line at the end." It must call `cards.get` or `boards` to find it, `docs.read`, then `docs.write` with the version it read. Ask me to open that document in the OS: the new line is there, and "saved by" shows my name. Ask me to remove the line in the OS.
5. The second brain: ask me to ask my AI "How do we handle a client who is unhappy?". It must use the brain actions, then name the notes it used, or say the second brain has nothing on it (or that it is not set up yet, if tab 4 is not done). Ask me what it said.
6. Skills: ask me to ask my AI "Which skills can I run?". It must call `skills.list` and name them, or say there are none yet. Ask me what it said.
7. A Member: if a Member is on the team, ask me to connect their AI the same way (Step 4) and ask, as them, "Show me the urgent list for the whole team", then "Change the agency name in the settings to Test". The AI must say that the first is for Owners and Admins, and that the database refused the second. If there is no Member yet, skip this and say so.
8. Revoke: ask me to press **Revoke** on my page, wait one minute, and ask my AI again. It must say the key does not work. Show me the log again (2): the top row is `revoked`, with my name. Then press **Connect your AI** again and put the new key (or the new Claude on the web link) in my AI tool, with the steps from Step 4.

## Step 6. Give each person their key

For each person who will use it: an Owner or Admin opens their page, presses **Connect your AI**, and gives them the key (or, for Claude on the web, the link) in private (a password manager share, or in person). Never in a Slack channel or an email thread. They connect their own AI with the steps from Step 4.

## Step 7. Write it down

1. Add a short "AI connector" part at the end of `OS_BUILD_RULES.md`, under "Parts added by the set-up tabs":
   - The AI connector is in the automations app: `apps/os/automations/mcp_server.py` (the five tools, the key check and the log) and `mcp_actions.py` (every action). Which actions this agency type has, and each board's fields: `apps/os/automations/mcp_actions.json`.
   - A new ability is one action in `mcp_actions.py` and its name in `mcp_actions.json`. The five tools never change. Every action that gets one thing takes `id`. Run the tests, then deploy.
   - Keys are made and revoked only on the Team screen ("Connect your AI"). Claude Code, Codex and Hermes send the key in an `Authorization: Bearer` header (or `x-auth-token`) to `<OS_AUTOMATIONS_URL>/mcp/`. Claude on the web uses the `/mcp/s/` link, which Modal's log keeps. The database keeps only a scrambled copy. Every call, and every revoke, is in `mcp_audit`.
   - `db.read` and `db.write` run as the person (the database's rules), never with the secret key.
   - Check it: `python3 apps/os/automations/mcp_check.py`.
   - The connector reads the copy of `second-brain/` and `skills/` made at the last deploy. After any change to them, put the automations app live again: `python3 -m modal deploy apps/os/automations/app.py`.
2. In `CLAUDE.md`, under "Built so far", add: "AI connector: online on <date>, connected for <names>." `CLAUDE.md` stays at 50 lines or fewer, and `AGENTS.md` stays one line. Check with `python3 tests/agents_md_check.py`.
3. Add to `DECISIONS.md`, one line each (date, question, answer, why): who has a key, which AI tools they use, and that a key works like a password until it is revoked.
4. Run the checks: `python3 -m pytest apps/os/automations/tests`. All must pass.

## Step 8. Tell me we are done

Give me a short list: that the three checks in Step 3 passed, who is connected, and what "What is most urgent for me?" answered. Then commit everything (never `.env`) with the message "AI connector set up".
