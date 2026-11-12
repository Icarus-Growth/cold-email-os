---
name: tam-mapper
description: Plans a client's total market for cold email - turns the ideal customer (industries, places, sizes) into the Google Maps searches to run, estimates how many businesses and fits there are, and counts per segment what the lead tables hold. Plans and counts only; it spends nothing. Use when the user says "map the TAM for <client>", "how big is the market", "plan the searches", "build the search grid" or "how far is the list".
area: fulfilment
agency: cold-email
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY, SLACK_BOT_TOKEN]
runs_on: either
---

# TAM mapper

The first step of the list-building chain. It plans. The google-maps-scraper skill does the
searches. It writes the plan to the `lead_searches` table, one row per search, and it counts
what is in `lead_searches`, `lead_companies` and `lead_contacts`.

The chain: **tam-mapper** (plan) → google-maps-scraper (find businesses) → website-classifier
(keep the ones that fit) → email-guesser (find and prove emails) → catch-all-verifier (deep check
on catch-all domains).

## What it needs

- `SUPABASE_URL` and `SUPABASE_SECRET_KEY`: Supabase, Project Settings (tab 1).
- `SLACK_BOT_TOKEN`: api.slack.com/apps, your app, OAuth & Permissions (tab 3).
- An ideal customer file for the client. Copy `references/icp_example.json` to
  `clients/<client-name>/icp.json` and change it:
  - `industries`: each with the words a person types into Google Maps to find one.
  - `locations`: the places, as Google Maps reads them ("Austin, TX").
  - `sizes`: the staff sizes the client wants. The website-classifier reads these.
  - `exclude` and `fit_rule`: the website-classifier reads these.

## Steps

1. Find the client (the search-client skill, if you are not sure of the name).
2. Make or open `clients/<client-name>/icp.json`. Ask the user for anything missing. Do not guess
   places or industries.
3. Show the plan first, without writing:
   `python3 skills/fulfilment/tam-mapper/scripts/run.py --client "Acme Dental" --icp clients/acme-dental/icp.json --dry-run`
4. Show the user the number of searches, the credits to finish, and the market estimate. Ask "go?".
5. Write the plan: the same command without `--dry-run`. It adds only the searches the client does
   not have yet, so it is safe to run again. It posts the plan in the daily-summary channel.
6. Tell the user the next step: the google-maps-scraper skill.
7. Later, to see how far the list is: `... --client "Acme Dental" --report`.

## The rules it follows

- A search is one keyword in one place. A segment is "<industry> | <place>".
- The estimate uses real numbers when it has them: new businesses per finished search, and the
  share of checked businesses that fit. Until then it uses `config.json`.
- Google Maps cannot search by size. Size is counted from what the website-classifier found.
- A plan above `max_searches_per_plan` stops with a plain message.

## On the automation server

The one automations app runs it by name: `run_skill("tam-mapper", {"client": "Acme Dental",
"icp": {...the file's contents...}})`. No new app, no schedule.
