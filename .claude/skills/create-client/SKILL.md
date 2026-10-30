---
name: create-client
description: Makes a new folder of notes for one client, clients/<client-name>/, from clients/_template/, and fills in what the user knows (contacts, emails, domains, other names). Notes only, not linked to the OS, the database or Slack. Use when the user says "add a client folder", "create a client", "set up notes for <client>" or "new client".
---

# Create client

Makes `clients/<client-name>/`: the place for everything specific to one client that is not in the
OS (who they are, the onboarding answers, their own data, the judgment calls made on them). Any agent
can follow these steps: they are plain commands, run from the repo root.

This skill does not add the client to the OS. A client is added to the OS on the Clients screen.
The OS never makes a client channel; link the existing one on the client page.

## What gets made

```
clients/<client-name>/
├── about.md        The company, the contacts, and every other name they go by
├── onboarding.md   The onboarding answers, raw call notes and action items
├── schemas.md      The client's own data outside the OS (their sheets, tools, connections)
├── decisions.md    Judgment calls made on this client, newest at the top
├── AGENTS.md       A short index of the files above (same text as CLAUDE.md)
├── CLAUDE.md
└── .env.example    Keys for this client's own tools go in .env (never committed)
```

## Steps

1. Ask for the client's name, as it should read in the notes (for example "Acme Corp").
2. Show what will be made, and check the folder does not exist yet:
   `python3 .claude/skills/create-client/scripts/create_client.py --name "Acme Corp" --dry-run`
   The folder name is made from the name (`acme-corp`). If the user wants another, add
   `--folder <name>`. If the folder already exists, stop and say so: open the existing folder instead.
3. Make it: the same command without `--dry-run`.
4. Ask what the user knows now. Every answer is optional; "don't know" is fine:
   - the company's legal name, industry and website;
   - the key contacts (name, role, email);
   - every other way the company's name is written (short names, old names, sub-brands);
   - their email domains and links.
5. Write the answers into `clients/<client-name>/about.md`, in the matching sections. Keep the
   headings as they are. Leave a section empty rather than guess.
6. Tell the user, in two or three short lines: the folder that was made, what is filled in, and that
   `onboarding.md` is for the onboarding call. Do not commit `.env`.

## Keep about.md growing

When any work turns up a new name, email, domain or short form for a client that is not in its
`about.md` yet, add it to the matching section under "Other names for this client". The
search-client skill uses these to find the client.
