# Cold Email Agency OS

A free operating system for a cold email agency: your team, your clients, your boards
(Tasks, Campaigns, Inbox set-ups), onboarding forms, calls and report numbers, in one place you own.

## What you need

- **Accounts (free to start):** GitHub, Supabase, Cloudflare, Slack (a workspace where you may add apps),
  Modal, logo.dev. Porkbun only if you buy a domain.
- **On your computer:** Python 3.9 or newer, Node 20 or newer, git, and an AI tool such as Claude Code or Codex.
- **Possible costs:** a domain (about the price of a lunch per year), and paid plans only if you outgrow
  the free ones.

## Set it up in five steps

Get the repo first: on this repo's GitHub page, press "Use this template" to make your own private copy, then
clone your copy (`git clone <your copy's address>`).
Open the folder in your AI tool (Claude Code, Codex, or another agent) and paste each tab in turn:

1. `docs/1-database.md`: makes your database.
2. `docs/2-os-setup.md`: puts the OS online on your own domain, or on a free address until you have one.
3. `docs/3-automations.md`: Slack alerts, a new-client post and a daily summary.
4. `docs/4-second-brain.md`: a second brain your AI reads before it works.
5. `docs/5-mcp.md`: the AI connector, so each person's AI works on their own cards.
6. `docs/6-build-an-automation.md`: the prompt to build any automation from the Agency Automation Menu.
7. `docs/7-github.md`: puts your OS in a private GitHub repo. Owner and developers only.

## Keys

Every key goes in `.env` (copy `.env.example`). Never commit `.env` and never paste a key into a chat.
The automations app reads its keys from one Modal secret named `agency-os` (tab 3, Step 7.5):
`SLACK_BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `OS_SHARED_SECRET`,
`SLACK_ICON_URL` and `MCP_TOKEN_PEPPER`.
`SUPABASE_PUBLISHABLE_KEY` is new in the Modal secret: the AI connector's `db.read` and `db.write` need it,
so each person's AI reads and writes with their own access. If you set up the automations before, store the
secret again with the tab 3 Step 7.5 command, then deploy again (Step 7.6).

## Use

This template is free to use and change in your own agency. You may not use it to make a product that
competes with it, such as selling or giving it away as your own template. See `LICENSE` and `NOTICE.md`.
