---
name: catch-all-verifier
description: Runs the deep email check (BounceBan, an SMTP-level check) only on the contacts in lead_contacts whose domain came back catch-all, and writes the result with its evidence - valid, risky, none valid, invalid or unknown. Spends credits, so it asks for approval above a limit. Use when the user says "check the catch-all emails for <client>", "deep verify", "verify the catch-alls" or "clean the list before the campaign".
area: fulfilment
agency: cold-email
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY, SLACK_BOT_TOKEN, BOUNCEBAN_API_KEY]
runs_on: either
---

# Catch-all verifier

The last step of the list-building chain. It works on each contact with `email_status`
"catch-all" (the email-guesser sets it) and no `deep_checked_at`. It checks the contact's saved
candidates (`email_candidates`), or the contact's own email.

It writes: `email` (only when checked), `email_status`, `email_evidence`, `email_score`,
`deep_status`, `deep_credits`, `final_verdict` and `deep_checked_at`.

| Deep check says | email_status | final_verdict |
|---|---|---|
| deliverable, score at or above `send_score` | valid | send |
| deliverable below `send_score`, or risky | risky | risky |
| every checked candidate undeliverable | none (none valid) | (empty) |
| the contact's own email undeliverable | invalid | skip |
| unknown: the deep check cannot read this domain | unknown | risky for an own email, else (empty) |

`final_verdict` uses three words in every lead skill: **send** (ready for a campaign), **risky** (send only if the client accepts some bounces) and **skip** (never send). Empty means not decided yet.

## What it needs

- `BOUNCEBAN_API_KEY`: bounceban.com, sign in, API (left menu), API key.
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (tab 1) and `SLACK_BOT_TOKEN` (tab 3).

## Steps

1. Run the email-guesser skill first. It marks the catch-all contacts.
2. Dry run. It spends nothing and writes nothing:
   `python3 skills/fulfilment/catch-all-verifier/scripts/run.py --client "Acme Dental"`
3. Show the user the most it can cost. Ask "go?".
4. Run it: the same command with `--live`. Above `approval_above` credits it stops and asks for
   approval: a card in "30 - In Review" on the Tasks board and a post in the review channel. A
   person approves by moving the card to "100 - Complete". Then run step 4 again.
5. It posts the counts in the daily-summary channel.
6. The contacts with `final_verdict` "send" are ready for a campaign. "risky" ones go only if the
   client accepts them.

## The rules it follows

- A catch-all domain means the cheap verifier is guessing. So the deep check is aimed only at
  catch-all domains. Add "unknown" to `check_statuses` to also check what the cheap verifier could
  not answer. That spends more.
- The first check at a domain is the scout. If it comes back "unknown", the deep check cannot read
  the domain either. No more credits are spent there.
- One resolved colleague shows the company's pattern. It goes first for the others at the domain.
- An untested address is not an answer. On a domain the deep check can read, the candidates not
  checked (above `max_checks_per_person`) are never given as the email.
- "None valid" is a real result. It is written as one.
- At most 500 contacts a batch. Each answer is written at once, so a crash starts again at the
  next contact with no answer.
- If the deep check does not answer, those contacts stay for the next run, and the error goes once
  to the pipeline-errors channel.

## On the automation server

`run_skill("catch-all-verifier", {"client": "Acme Dental", "live": true})`. No new app, no schedule.
