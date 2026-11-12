# Skills

A skill is one job your AI can do the same way every time. It is a folder with a `SKILL.md`
(the steps, in plain words) and, when it needs code, a `scripts/` folder. Every coding tool
can use one: Claude Code, Codex, Grok or another agent reads the `SKILL.md` and follows it.

## The three folders

| Folder | What goes in it | Who can run it from the team connector |
|---|---|---|
| `skills/fulfilment/` | The skills the team uses to deliver client work | Everyone on the team |
| `skills/owner/` | Sales, deals, money and the business itself | Owners and Admins only |
| `skills/global/` | Skills everyone uses, whatever their job | Everyone on the team |

The connector checks the person's role on every call. A skill file is never the lock.

## The skill format

```
skills/<fulfilment|owner|global>/<skill-name>/
├── SKILL.md       the header (below), then the steps
├── scripts/       optional: the code the steps run
├── references/    optional: longer notes the steps point to
└── tests/         one test with example data, one with bad input
```

The header at the top of `SKILL.md`:

```
---
name: skill-name                 # small letters and dashes, the same as the folder name
description: What it does, and when to use it (the words a person would say).
area: fulfilment                 # fulfilment, owner or global: the folder it is in
agency: all                      # all, cold-email, ads, content or email-marketing
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY]   # every .env key it reads ([] for none)
runs_on: modal                   # modal (the automation server), local, or either
daily: true                      # optional: the daily job runs scripts/daily.py once a day
---
```

## Rules every skill follows

- A missing key stops the skill. It says which key and where to get it. It never prints a key.
- A step that spends money, or sends something to a client or a prospect, stops first. It asks
  for approval in Slack, and a person approves it in the OS.
- Long lists go in batches of at most 500 rows. A crash picks up where it stopped.
- Slack posts go only through `shared/slack_notify.py`, and only to the automation channels.
- A failure is posted once to `pipeline-errors`, with the record and the error.
- A skill that runs on Modal is one more function in the ONE automations app. No new app.
  No new schedule: a daily skill runs inside the daily job.

## Make Claude Code see the skills

Claude Code reads skills from `.claude/skills/`. Run this after a clone or a pull, and after
you add, rename or remove a skill:

```
python3 tools/sync_skills.py
```

It puts a link in `.claude/skills/` for each skill (a copy on Windows). It is safe to run
again. `python3 tools/sync_skills.py --check` changes nothing and fails if a link is missing.

## Make a new skill

Use the `scaffold` skill: "make a new skill that ...". It asks where the skill runs (the
automation server, Grok, or your own server or computer) and builds the folder in this format.

## Helpers

`skills/_kit/skillkit.py` holds what every skill shares: the keys check, Slack posts, the
batches, the spend gate and the daily hook. `skills/_kit/skill_fakes.py` holds the fake database
and fake Slack for the tests. Run every skill test: `python3 -m pytest skills`.
