---
name: email-guesser
description: Finds and proves the work email of each contact in lead_contacts that has a name and a company domain. Tests the likely address patterns with the cheap verifier (MillionVerifier), learns each company's pattern from one resolved colleague, and writes the email only when a check proved it, with the status and the evidence beside it. Spends credits, so it asks for approval above a limit. Use when the user says "find the emails for <client>", "guess their emails", "fill the emails" or "what is this person's email".
area: fulfilment
agency: cold-email
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY, SLACK_BOT_TOKEN, MILLIONVERIFIER_API_KEY]
runs_on: either
---

# Email guesser

Works on each contact in `lead_contacts` with no `guess_checked_at`. It needs the person's name
and a company domain (the contact's own `domain`, else its company's). A contact that already has
an email gets one check of that email.

It writes: `email` (only when proved), `email_status`, `email_evidence`, `email_pattern`,
`email_candidates`, `catch_all`, `guess_credits`, `final_verdict` and `guess_checked_at`.

| email_status | What it means | final_verdict |
|---|---|---|
| valid | A check proved this address | send |
| catch-all | The domain accepts any address. The candidates wait for the catch-all-verifier | (empty) |
| unknown | No check could say yes or no. The candidates are saved | (empty) |
| none | Every likely address came back invalid. None valid | (empty) |
| invalid | The contact's own email came back invalid | skip |
| skipped | No name, no domain, or a free mail domain | (empty) |

`final_verdict` uses three words in every lead skill: **send** (ready for a campaign), **risky** (send only if the client accepts some bounces) and **skip** (never send). Empty means not decided yet.

## What it needs

- `MILLIONVERIFIER_API_KEY`: app.millionverifier.com, sign in, API (left menu), API key.
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (tab 1) and `SLACK_BOT_TOKEN` (tab 3).

## Steps

1. Find the client. Check that its contacts have names and domains.
2. Dry run first. It spends nothing and writes nothing:
   `python3 skills/fulfilment/email-guesser/scripts/run.py --client "Acme Dental"`
3. Show the user the most it can cost. Most contacts cost far less: the checks stop at the first
   good address. Ask "go?".
4. Run it: the same command with `--live`. Above `approval_above` credits it stops and asks for
   approval: a card in "30 - In Review" on the Tasks board and a post in the review channel. A
   person approves by moving the card to "100 - Complete". Then run step 4 again.
5. It posts the counts in the daily-summary channel.
6. Next: the catch-all-verifier skill, for the "catch-all" contacts.

## The rules it follows

- An untested address is not an answer. The email column is filled only when a check proved it.
  The evidence says which check, and what it said.
- "None valid" is a real result. It is written as one, so nobody pays to check the same person
  again.
- One resolved colleague shows the company's pattern. A pattern already proved at a domain goes
  first. Else the first person at the domain is the pathfinder: the patterns are tried from the
  most common, and the first good one sets the pattern for the others at that domain.
- A catch-all domain means the cheap verifier is guessing. One test address that cannot exist is
  checked first at each domain. If it comes back good, the domain is catch-all: no more cheap
  checks are spent there. The best candidates are saved for the deep check.
- A domain with no mail server (no MX record) costs nothing: no address there can work.
- At most 500 contacts a batch. Each answer is written at once, so a crash starts again at the
  next contact with no answer.
- If the verifier does not answer, those contacts stay for the next run, and the error goes once
  to the pipeline-errors channel.

## On the automation server

`run_skill("email-guesser", {"client": "Acme Dental", "live": true})`. No new app, no schedule.
