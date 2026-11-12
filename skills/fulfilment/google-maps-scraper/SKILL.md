---
name: google-maps-scraper
description: Finds local businesses on Google Maps (through the Serper API) for a client's planned searches, keyword by place, and saves each one once in the lead_companies table. Spends Serper credits, so it asks for approval above a limit. Picks up where it stopped after a crash. Use when the user says "scrape Google Maps for <client>", "find dentists in Austin", "run the searches", "resume the scrape" or "how is the scrape going".
area: fulfilment
agency: cold-email
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY, SLACK_BOT_TOKEN, SERPER_API_KEY]
runs_on: either
---

# Google Maps scraper

Runs the searches in `lead_searches` (planned by the tam-mapper skill, or added here with `--add`)
and saves the businesses it finds in `lead_companies`.

## What it needs

- `SERPER_API_KEY`: serper.dev, sign in, Dashboard, API Key. Add it to `.env`.
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (tab 1) and `SLACK_BOT_TOKEN` (tab 3).
- A missing key stops the skill. The message says which key and where to get it.

## Steps

1. Find the client. Check that it has searches: `--status` (below). If it has none, use the
   tam-mapper skill, or add some here: `--add "dentist" --in "Austin, TX" --in "Dallas, TX"`.
2. Dry run first. It spends nothing and writes nothing:
   `python3 skills/fulfilment/google-maps-scraper/scripts/run.py --client "Acme Dental"`
3. Show the user the searches and the credits. Ask "go?".
4. Run it: the same command with `--live`.
   - Under `approval_above` credits (config.json), it runs.
   - Above it, it stops. It makes a card "Approve spend: google-maps-scraper for <client> (up to N
     credits)" in "30 - In Review" on the Tasks board, and asks in the review channel. A person
     approves by moving the card to "100 - Complete". Then run step 4 again.
5. It posts the result in the daily-summary channel: searches run, businesses found, new ones
   saved, credits used, searches still to do.
6. Searches still to do: run step 4 again. It starts at the next search that is not done.
7. Next: the website-classifier skill.

See the progress: `... --client "Acme Dental" --status`.

## The rules it follows

- Each search row has a status: "to do", "done" or "failed". A row is marked "done" as soon as its
  businesses are saved. A crash loses at most the search in hand.
- A search that fails is tried once more on the next run (`max_attempts`). Then it stays
  "failed" and the run goes on.
- A business is saved once per client. The same Google place id, or the same web domain, is
  skipped. A business with no website is not saved (`keep_without_website`), because cold email
  needs a domain.
- At most 500 searches a batch, and `max_batches_per_run` batches a run.
- The approval covers up to the approved credits. The skill counts what it spent since the
  approval. When that is used up, it asks again.

## On the automation server

`run_skill("google-maps-scraper", {"client": "Acme Dental", "live": true})`. No new app, no schedule.
