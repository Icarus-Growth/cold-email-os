---
name: sending-estate-plan
description: Works out how many sending domains and inboxes one client needs from the emails they send a month - inboxes per domain, sends per inbox per day, warm-up days and a spare buffer - picks the domain names and the inbox addresses, writes one card per inbox provider on the Inbox set-ups board in "10 - Approval Needed", and asks for approval in the review channel with a cost estimate. Buys nothing. Use when the user says "plan the inboxes for <client>", "how many domains does <client> need?" or "size the sending set-up".
area: fulfilment
agency: cold-email
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY, SLACK_BOT_TOKEN, PORKBUN_API_KEY, PORKBUN_SECRET_KEY]
runs_on: either
---

# Sending estate plan

Step 1 of 2 for a new client's sending set-up. It plans and asks. It buys nothing.
Step 2 is the sending-estate-provision skill. It runs only after a person approves the plan.

## What it needs

- The client's monthly send volume: the `monthly_send_volume` column on the client row (emails a
  month). If it is empty, give `--volume`. The `--volume` option always wins.
- Who the emails come from: `--senders "Jane Doe, Sam Lee"`. With no option, it reads the
  onboarding form answer `sender_names`, then the contact's name.
- `PORKBUN_API_KEY` and `PORKBUN_SECRET_KEY`: the names are checked at the registrar (see the
  sending-domain-names skill).
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (tab 1) and `SLACK_BOT_TOKEN` (tab 3).

## Steps

1. Look at the plan first. It writes nothing and posts nothing:
   `python3 skills/fulfilment/sending-estate-plan/scripts/plan_estate.py --client "Acme Dental" --senders "Jane Doe" --preview`
2. Show the user the counts, the names and the cost estimate. Ask "go?".
3. Run it again with no `--preview`. It writes the cards and posts the approval ask in the review
   channel. The post has a button that opens each card.
4. A person reads the ask. To approve, the person moves the card from "10 - Approval Needed" to
   "20 - Buying Domains" on the Inbox set-ups board. A move made by an automation does not count.
5. Then run the sending-estate-provision skill on the card. The post gives the command.

Run it again for the same client while a card is still in "10 - Approval Needed": it fills only
what is missing. It never makes a second card or a second set of domains.

## The sum

All numbers come from `config.json`. Example: 21,000 emails a month.

| Step | Google inboxes | Outlook inboxes |
|---|---|---|
| Emails a day: 21,000 / 21 sending days = 1,000 | 60% = 600 | 40% = 400 |
| Inboxes: emails a day / sends per inbox a day | 600 / 20 = 30 | 400 / 5 = 80 |
| Plus a 10% spare buffer (rounded up) | 33 | 88 |
| Domains: inboxes / inboxes per domain (rounded up) | 33 / 2 = 17 | 88 / 49 = 2 |
| Inboxes bought | 34 | 98 |

Every step rounds up, so the set-up always sends at least the volume asked for.

- **Sends per inbox a day** is the cold email a warmed inbox sends, not counting warm-up mail.
- **The spare buffer** covers inboxes that get flagged or paused.
- **Warm-up.** No inbox sends cold email until it has warmed for `warm_days_before_sending`
  days (`warm_days_enterprise` with `--enterprise`). The ready date on the card = today +
  `setup_days` + the warm days.
- **Warm-up per day.** Google: start at 5, add 5 a day up to 50, then 30 a day after day 14.
  Outlook: 2 a day, flat. The provision skill sets this in the warm-up tool.

## What it writes

| Where | What |
|---|---|
| Inbox set-ups board (`inbox_batches`) | One card per inbox provider, in "10 - Approval Needed": `batch_name`, `domain_count`, `inbox_count`, `inbox_provider`, `domain_registrar`, `due_date` (the ready date) and `notes` (the sum, in words). |
| `sending_domains` | One row per domain, status "planned", with its planned price, the forward address (the client's website), how many inboxes it gets and its warm days. |
| `sending_inboxes` | One row per inbox, status "planned", with the exact address and the sender's name. Google: one sender per domain. Outlook: every sender, then numbered names, to fill each domain. |
| The review channel | One approval ask per card: what it buys, the cost estimate, why this size, the domains, the ready date and the command to run after approval. |

Rows are written in batches of at most 500.

## The cost estimate

The domain price comes live from the registrar. The inbox price comes from
`cost_estimate` in `config.json`. Those are example list prices: check each vendor's price page
and change them to your own. The approved domain prices are the most the provision skill may pay.

## Change the rules

`config.json`: sending days, buffer, the Google and Outlook split, sends per inbox, inboxes per
domain, the provider for each kind, warm-up, warm days and the cost estimate. Inboxing allows only
25, 49, 50 or 99 inboxes a domain: the plan stops if another number is set.

## On the automation server

`run_skill("sending-estate-plan", {"client": "Acme Dental", "volume": 21000, "senders": "Jane Doe"})`.
It is quick and safe to run there. No new app, no schedule.
