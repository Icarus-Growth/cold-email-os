---
name: scaffold
description: Makes a new skill folder in this repo's skill format, ready to fill in - the steps, the code, the keys it needs, the tests and the link for Claude Code. The skill can run on the automation server (Modal), in the Grok coding tool, or on your own server or computer. Use when someone says "make a new skill", "build a skill that...", "turn this into a skill", "automate this" or "start a new automation".
area: global
agency: all
needs: []
runs_on: local
---

# Scaffold

Makes a new skill from a short description. Every new skill starts here, so every skill has the
same shape: `SKILL.md` with the header, `config.json` for the rules a person may change, `scripts/`
for the code, `tests/` with one example test and one bad-input test. Read `skills/README.md` for
the format and the rules.

## Step 1: Ask only what you cannot work out

Read the request, `CLAUDE.md`, `SCHEMAS.md` and `DECISIONS.md` first. Work out what you can. Then
ask the rest in ONE question page (choices where you can, "Skip / leave for now" on each):

1. **The name.** Small letters and dashes, for example `review-reminder`.
2. **What it does and when to use it.** One or two sentences, with the words a person would say.
3. **Who runs it** (the folder):
   - `fulfilment`: the team uses it to deliver client work. Everyone can run it.
   - `owner`: sales, deals, money, the business. Only Owners and Admins can run it.
   - `global`: everyone uses it, whatever their job.
4. **Where it runs:**
   - `modal`: the automation server. It runs when the laptop is closed. Pick this by default.
   - `grok`: the Grok coding tool (or any AI) follows the steps. It runs while the tool is open.
   - `server`: your own server or computer, from a terminal or a cron line.
   - `either`: the automation server and a computer.
5. **What kind:**
   - `rows`: it reads rows that are not done yet, does each one, and writes the result back.
   - `job`: it does one job each time (a check, a post, a report).
   - `steps`: no code. Numbered steps an AI follows.
6. **The table it reads** (from `SCHEMAS.md`), and the keys it needs from `.env`.
7. **Does it run every day?** It then runs inside the daily job. It never gets its own schedule.
8. **Does it spend money, or send anything to a client or a prospect?** Then it gets the spend
   gate: it asks in Slack and waits until a person approves it in the OS.

Also ask, if the request does not say: the limit on spend, the Slack channel for its posts (only
the automation channels), and one example of a good result. These are the facts and the taste the
code cannot guess. Do not ask anything at run time: the skill must run with nobody there.

## Step 2: Make the folder

Show what it will make first:

```
python3 skills/global/scaffold/scripts/scaffold_skill.py \
  --name <name> --description "<what it does. Use when ...>" \
  --area <fulfilment|owner|global> --agency <all|cold-email|ads|content|email-marketing> \
  --kind <rows|job|steps> --runs-on <modal|grok|server|either> \
  --needs <KEY_ONE,KEY_TWO> --table <table> [--daily] [--spends] --dry-run
```

Then run the same command without `--dry-run`. It stops, and changes nothing, if the name is
taken, the folder exists or an input is wrong. It links the new skill for Claude Code at the end
(`tools/sync_skills.py`).

## Step 3: Fill in each TODO

- `scripts/run.py`: `check()` stops bad input before anything is written. `do_one()` (rows) or
  `run()` (job) does the work. Keep the work in small functions that take the database and Slack,
  so the tests can pass fakes.
- An outside tool: one small function per tool, so a test can replace it. Name its key in the
  header's `needs`, and say where to get it in `SKILL.md`.
- An AI judgement (classify, score, rewrite): `skillkit.ask_ai(prompt, schema=...)`. It needs
  `ANTHROPIC_API_KEY`.
- A rows skill needs a column that stays empty until the row is done (`config.json`,
  `done_column`). If the table has none, add it to the table (read `DATABASE_RULES.md`).
- The spend gate: write what it buys and the cost estimate in `spend_gate()`.
- `config.json`: the rules a person may change (limits, days, channel, prompt).
- `tests/`: make both tests test the real logic. Keep one with example data that reads back what
  was written, and one with bad input that shows nothing was written.

## Step 4: Prove it

1. `python3 -m pytest skills/<area>/<name> -q` passes.
2. Run it once with `--dry-run`, then once for real on example data. Read the result back from the
   database. Do not trust the "OK" from the write.
3. Run it once with bad input. It must stop with a plain message and write nothing.
4. `python3 tools/sync_skills.py --check` passes.
5. Add one line to `DECISIONS.md`: what you chose and why.

## Step 5: Put it live (only for `modal` and `either`)

The ONE automations app already has a `run_skill` entry, so a new skill needs no new app, no new
function and no new schedule:

1. Put each key in the `agency-os` secret on Modal (names only in chats, never values).
2. `python3 -m modal deploy apps/os/automations/app.py`
3. Run it once there: `python3 -m modal run apps/os/automations/app.py::run_skill --name <name>`
4. Tell the person where to look: the Slack channel, the screen or the record, and what they
   should see there.

The Modal free plan has 5 scheduled jobs. Never add a `schedule=` for a skill. Use `--daily`.

## Rules every new skill keeps

- A missing key stops the skill with the key name and where to get it. It never prints a value.
- Money or a message to a client or a prospect: it asks in Slack first, and a person approves.
- Batches of at most 500 rows. A crash picks up at the next row not done.
- Slack only through `shared/slack_notify.py`, only to automation channels, never a client channel.
- One post in `pipeline-errors` on a failure, with the record and the error.
