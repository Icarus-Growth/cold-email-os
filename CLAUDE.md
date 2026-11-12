# Cold Email Agency OS

The working codebase for <agency name>, a cold email agency run by <owner name>. This holds the working skills, files and blueprints behind running <agency name>.

Every coding tool reads this file. `AGENTS.md` points here. This file holds no rules. Before you build, read:
- `OS_BUILD_RULES.md`: every build rule (screens, automations, skills, the AI connector, keys, plain words).
- `DATABASE_RULES.md`: every database rule (tables, columns, stages, change files).

Keep this file at 50 lines or fewer. Check with `python3 tests/agents_md_check.py`.
Facts about the business go under "About the business". Choices go in `DECISIONS.md` (one line each: date, question, answer, why).

## About the business

The business set-up question page fills this part (`tools/question-page/`). One fact per line. Replace a line; do not add a second one.
- Agency: <agency name>. Owner: <owner name>.
- What we sell: <not answered yet>
- Who we sell to: <not answered yet>
- How clients find us: <not answered yet>
- Clients now, and the goal: <not answered yet>

## The team and roles

One line per person: name, role, access (Owner, Admin or Member). Tab 2 and the "who are you" page fill it.
- <owner name>: owner, Owner.

## Where things live

- `ARCHITECTURE.md`: a map of this repo. `SCHEMAS.md`: every table and column. `DECISIONS.md`: every choice so far.
- `docs/`: the set-up tabs (1 database, 2 OS, 3 automations, 4 second brain, 5 AI connector, 6 build an automation, 7 GitHub) and the agency process.
- `apps/os/frontend/` the OS screens, `apps/os/backend/` the database, `apps/os/automations/` the automations and the AI connector, `apps/onboarding/` the client form.
- `skills/`: the team's skills (`fulfilment/`, `owner/`, `global/`). `docs/6-build-an-automation.md`: the prompt to build any automation.
- `second-brain/`: how the agency works. `clients/`: notes per client.
- `shared/`: code two or more parts use. `tools/`: helper scripts, such as `question-page/`. `archive/`: old files (never run them).

## Built so far

One line per tab when it is done.
- Nothing yet. Start with `docs/1-database.md`.
