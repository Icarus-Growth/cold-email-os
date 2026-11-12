---
name: website-classifier
description: Reads the home page of each business in lead_companies and asks the AI if it fits the client's ideal customer, with a confidence, a reason and a quote from the page. Writes fit, not fit, unsure or error on the row. Uses AI credits, so it asks for approval above a limit. Use when the user says "classify the websites for <client>", "which of these businesses fit", "qualify the list" or "check the sites".
area: fulfilment
agency: cold-email
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY, SLACK_BOT_TOKEN, ANTHROPIC_API_KEY]
runs_on: either
---

# Website classifier

Checks each business in `lead_companies` that has no answer yet. It writes `fit_status`,
`fit_confidence`, `fit_reason`, `fit_evidence` (a quote from the page), `fit_method` and
`fit_checked_at`. When the page shows the staff size, it also writes `size_band`.

## What it needs

- `ANTHROPIC_API_KEY`: console.anthropic.com, Settings, API Keys. Optional: `AI_MODEL` in `.env`
  for a smaller model that costs less on big lists.
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (tab 1) and `SLACK_BOT_TOKEN` (tab 3).
- The rule, in one sentence. The skill takes the first it finds:
  1. `--rule "An independent dental practice that treats patients"`;
  2. `fit_rule` in the client's ideal customer file (`--icp clients/<client-name>/icp.json`);
  3. the client's "target market" in the OS.

## Steps

1. Find the client. Check that the rule is right. Ask the user if it is not clear.
2. Dry run first. It spends nothing and writes nothing:
   `python3 skills/fulfilment/website-classifier/scripts/run.py --client "Acme Dental" --icp clients/acme-dental/icp.json`
3. Show the user the number of AI checks and the cost. Ask "go?".
4. Run it: the same command with `--live`. Above `approval_above` AI checks it stops and asks for
   approval: a card in "30 - In Review" on the Tasks board and a post in the review channel. A
   person approves by moving the card to "100 - Complete". Then run step 4 again.
5. It posts the counts in the daily-summary channel.
6. Show the user the "unsure" rows. A person decides those.
7. Sites that could not be read: run again later with `--retry-errors`.
8. Next: add the people at the businesses that fit, then the email-guesser skill.

## The rules it follows

- Free checks first, with no AI cost: no website, an excluded word in the name or category, a
  site that does not answer, a parked domain, a page with almost no text.
- A site that cannot be read is "error", never "not fit".
- The AI gives a quote from the page as proof. With no proof it says "unsure". Below
  `min_confidence` the answer is "unsure", for a person to check.
- How to judge is in `references/judge.md`. Change that file to change how every site is judged.
- The home page is read with a short timeout and only the first part of it (`fetch_max_bytes`).
- At most 500 businesses a batch. Each answer is written at once, so a crash starts again at the
  next business with no answer. A run that has nothing to do costs nothing.
- If the AI call fails (a bad key, no credits), the run stops, those rows stay for the next run,
  and the error goes once to the pipeline-errors channel.

## On the automation server

`run_skill("website-classifier", {"client": "Acme Dental", "live": true, "icp": {...}})`. No new app,
no schedule.
