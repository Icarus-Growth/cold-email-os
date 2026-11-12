# Build rules for the Cold Email Agency OS

Every rule for building and changing this OS, except the database rules. Those are in `DATABASE_RULES.md`.
`CLAUDE.md` links here. Read this file before you build anything. Each set-up tab adds its own part at the end.

## Rules for every change

1. **Plain words.** Explain what you did in short sentences. One fact per sentence. No jargon.
2. **Keys, tokens and passwords never go in a table, a commit or the chat.** They go in `.env` only.
   Never print a key's value: say its name. A line in `.env` has no space before or after "=".
3. **Never commit `.env`.** It is in `.gitignore`. Check `git status` before every commit.
4. **No step waits for a keyboard.** An AI cannot type into a question. Use `--yes` (for example
   `supabase db push --linked --yes`) and `< /dev/null` where a command could ask.
5. **Shared code lives in `shared/`.** Code that two or more skills or apps use (for example
   `slack_notify.py` and `supabase_client.py`) goes in `shared/`. Look there before you write a new helper.
6. **Every automated Slack post goes through `shared/slack_notify.py`,** and only to the channels made for
   automations. Nothing is ever posted in a client channel, and the OS never makes a client channel.
7. **Questions go on one question page.** When you need more than two answers from the owner, make a
   question page (`tools/question-page/`), not a list in the chat. Facts go into `CLAUDE.md` "About the
   business"; choices go into `DECISIONS.md` (one line each: date, question, answer, why).
8. **Keep `CLAUDE.md` at 50 lines or fewer.** Rules go here or in `DATABASE_RULES.md`, never in `CLAUDE.md`.
   `AGENTS.md` is one line that points to `CLAUDE.md`. Check with `python3 tests/agents_md_check.py`.
9. **`archive/`** holds old files. Never run or change anything in it.
10. **Clients.** Notes about one client go in `clients/<client-name>/`. A new client folder starts as a copy
    of `clients/_template/` (the `create-client` skill does it). These notes are not linked to the database.

## Skills

11. **Skills** live in `skills/<fulfilment|owner|global>/<name>/SKILL.md` (format: `skills/README.md`). Any AI can
    use one: read the `SKILL.md` and follow it. `skills/fulfilment/` is the team's delivery work, `skills/global/`
    is for everyone, and `skills/owner/` is for Owners and Admins only.
12. Claude Code reads the skills through links in `.claude/skills/`: run `python3 tools/sync_skills.py` after a
    clone or pull, and after you add or remove a skill. Make a new skill with the `scaffold` skill.
13. **A skill that runs on its own** (on a timer or from a button) runs on the automation server, not on a
    laptop. It adds a function to the one Modal app. No new Modal app and no new scheduled job: the free
    plan has 5 scheduled jobs.

## The OS screens

14. The screens are in `apps/os/frontend/`. The boards, stages and fields are in
    `apps/os/frontend/src/agency.config.ts`. Colours are in `apps/os/frontend/src/theme.css` only.
15. A card shows its name and three fields at most. Only a "100 - ..." stage counts as finished.
    A live stage (a live campaign) stays open and stays on My Work.
16. `apps/os/frontend/src/ui/` holds the screen parts every screen uses. A change there shows on every screen.
17. Put the OS live again after a change: `python3 apps/os/frontend/tools/deploy.py` (add `--domain <OS address>`
    if the OS has its own domain; `--dry-run` shows every call first).
18. `apps/os/frontend/tools/domain.py` buys domains and sets DNS records. Never buy a domain without the
    owner's yes to the price.

## A new board

19. A new board needs: its table and stages (see `DATABASE_RULES.md`), its entry in `agency.config.ts`,
    its table in `apps/os/automations/alert_rules.json` ("boards"), and its entry in
    `apps/os/automations/mcp_actions.json` (name column, stages, people, work link, fields).
    Then run `python3 tests/config_matches_db.py` and the tests, and put the OS and the automations live again.
    My Work reads `alert_rules.json` to say who acts next on a card.

## The AI connector

20. The AI connector is `apps/os/automations/mcp_server.py` (five fixed tools, the key check, the log in
    `mcp_audit`). Every action is in `mcp_actions.py`. Which actions and board fields this type has is in
    `mcp_actions.json`. A new ability is one action plus its name in `mcp_actions.json`. The five tools never change.
21. It reads `second-brain/` and `skills/` from the copy made at each deploy, never `inbox/`. After a change to
    the notes or the skills, put the automations app live again: `python3 -m modal deploy apps/os/automations/app.py`.

## Parts added by the set-up tabs

Each tab adds its part below, under its own heading. Keep each part short.
