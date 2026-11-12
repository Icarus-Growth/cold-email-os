# 6. Build an automation

Use this when you want a new automation in your cold email OS. Pick one from the Agency Automation
Menu, or describe your own.

Before you start:

1. Finish tabs 1 to 3 first. The database, the automation server and Slack must all work.
2. Open this repo in Claude Code, Codex or Grok.
3. Copy the prompt below. Put the automation you want under "THE AUTOMATION I WANT".
4. Paste it into the chat and send it.

The AI builds the automation as a skill in `skills/` (read `skills/README.md`). It uses the
`scaffold` skill to make the folder. It asks its questions on one question page. It shows you the
proof before it says it is done.

## The prompt

```text
You are building one automation inside my agency's operating system (this repo).

THE AUTOMATION I WANT:
<name it from the Agency Automation Menu, or describe it in a few lines>

BEFORE YOU BUILD
1. Read CLAUDE.md, OS_BUILD_RULES.md, DATABASE_RULES.md, SCHEMAS.md, DECISIONS.md and ARCHITECTURE.md.
2. Check the foundation. The database must exist (SCHEMAS.md lists the tables), the automation server must be set up
   (Modal, or the server named in DECISIONS.md), and Slack must be connected. If one is missing, stop and tell me
   which tab of the set-up guide to finish first. Do not build around a missing foundation.
3. Write down in plain words: what starts it (the trigger), what it reads, what it does, what it writes back, and
   who is told. Use only tables and columns that exist in SCHEMAS.md. If it needs a new column, add it to the
   parent table. Add a new table only when one parent record can have many of the thing.
4. List every outside tool and key it needs. Check each key is in .env (names only; never print a value).
   If a key is missing, tell me where to get it and the exact name to use in .env.
5. Ask me your questions as ONE question page: choices where you can, a text box where you must, and
   "Skip / leave for now" and a comment box on every question. I paste the answers back. Ask only what you
   cannot work out from the repo.

WHEN YOU BUILD
6. Build it as a skill: skills/fulfilment/ if the team uses it to deliver work, skills/owner/ if it helps the
   owner sell or run the business, skills/global/ if everyone uses it.
7. It runs on the automation server, not on my laptop. It must still work when the laptop is closed.
8. Any step that spends money or sends something to a client or prospect stops and asks for approval in Slack first.
9. Large lists are done in batches of at most 500 rows, and a crash picks up where it stopped.
10. Every automated Slack post goes through the shared Slack sender and only to channels made for automations.
    Never post in a client channel. Each message says what happened, what to do and where to click.
11. When something fails, post it once to pipeline-errors, with the record and the error.
12. Add the skill to the team connector so each person's AI can run it, with the right role.

WHEN YOU ARE DONE
13. Run it once on real or example data. Show me what it wrote, read back from the database (not the "OK" from the
    write). Then try one bad input and show that it fails cleanly.
14. Tell me where to look to see it worked: the Slack channel, the screen, the record, and what I should see.
15. Add one line to DECISIONS.md (what you chose and why) and update SCHEMAS.md if the database changed.
16. Give me a short summary in plain words: what it does, how to start it, how to stop it, and what it costs to run.
```

## After it is built

- Run `python3 tools/sync_skills.py` after a pull, so Claude Code sees the new skill.
- To stop an automation, ask the AI: "turn off the <name> skill". It takes `daily: true` out of the skill's header and puts the automation server live again. The folder stays, so you can turn it on again.
