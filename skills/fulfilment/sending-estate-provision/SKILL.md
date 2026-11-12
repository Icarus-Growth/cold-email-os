---
name: sending-estate-provision
description: Sets up an approved Inbox set-ups card - buys the planned sending domains, sets the DNS (SPF, DKIM, DMARC and the forward to the client's site), orders the inboxes, checks the records and starts the warm-up - and moves the card through "20 - Buying Domains", "30 - Setting Up Inboxes", "40 - Warming" and "100 - Ready To Send". Runs only after a person moved the card out of "10 - Approval Needed". A dry run unless --live. Never spends more than was approved. Use when the user says "set up the inboxes for <client>", "buy the approved domains", "provision the card" or "where is the inbox set-up?".
area: fulfilment
agency: cold-email
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY, SLACK_BOT_TOKEN, PORKBUN_API_KEY, PORKBUN_SECRET_KEY, INBOXING_API_KEY, INBOXING_REGISTRAR_CREDENTIAL_ID, SCALEDMAIL_API_KEY, SCALEDMAIL_ORGANIZATION_ID, REGISTRAR_WEB_USERNAME, REGISTRAR_WEB_PASSWORD, PLUSVIBE_API_KEY, PLUSVIBE_LOGIN_EMAIL, PLUSVIBE_LOGIN_PASSWORD]
runs_on: either
daily: true
---

# Sending estate provision

Step 2 of 2 for a new client's sending set-up. Step 1 is the sending-estate-plan skill. It
writes the card, the domain rows and the inbox rows, and asks for approval.

This skill spends money. It buys domains and starts monthly inbox subscriptions.

## Before it does anything

1. **A person approved the card.** The stage log must show a person (not an automation) moved
   the card out of "10 - Approval Needed". With no approval it stops with a plain message. It
   asks no vendor, writes nothing and spends nothing.
2. **A dry run unless `--live`.** A dry run sends nothing to any vendor. It writes only one note
   on each domain row: what a live run would do ("would buy tryacme.com for 11.08 USD").
3. **The spend guard.** It buys only the domains on the card. It stops before any call if the
   card has more domain rows or inbox rows than the plan approved. It never pays above a domain's
   approved price (`price_tolerance_usd`, 0 by default) or above the approved total. It checks
   the registrar credit before the first buy.

## What it needs

Only the keys for the vendors on the card are checked. A Google card does not need the Inboxing key.

| Key | Where to get it |
|---|---|
| `PORKBUN_API_KEY`, `PORKBUN_SECRET_KEY` | porkbun.com, Account, API Access. Turn on "Opt In All Domains" there too. |
| `INBOXING_API_KEY` | Inboxing, Settings, API (Outlook inboxes) |
| `INBOXING_REGISTRAR_CREDENTIAL_ID` | Optional. Inboxing, Settings, Registrars. Then Inboxing sets the nameservers itself. |
| `SCALEDMAIL_API_KEY`, `SCALEDMAIL_ORGANIZATION_ID` | ScaledMail, Settings, API (Google inboxes) |
| `REGISTRAR_WEB_USERNAME`, `REGISTRAR_WEB_PASSWORD` | Your registrar website sign-in. ScaledMail's staff use it to connect each domain. |
| `PLUSVIBE_API_KEY` | PlusVibe, Settings, API Access. Use the account key, not a workspace key. |
| `PLUSVIBE_LOGIN_EMAIL`, `PLUSVIBE_LOGIN_PASSWORD` | Your PlusVibe sign-in. The inbox providers upload the inboxes as you. |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SLACK_BOT_TOKEN` | tabs 1 and 3 |

Do the one-time registrar steps in `../sending-domain-names/references/registrar-porkbun.md`
before the first buy.

## Steps

1. Get the card's id from the approval post (the button opens the card).
2. Dry run:
   `python3 skills/fulfilment/sending-estate-provision/scripts/provision_estate.py --batch <card id>`
3. Read what it would do. Show the user. Ask "go?".
4. Run it live: the same command with `--live`. It buys, orders and sets the DNS. Then it stops
   at the first wait for each domain. It never sleeps.
5. The daily job carries it on. Or run step 4 again any time. Each domain goes on from its own
   status, so a second run never buys or orders twice.
6. The card moves forward on its own. Each move posts in task-updates. At "100 - Ready To Send"
   every inbox has warmed for the planned days.

Options: `--domains a.com,b.com` works on only those domains. `--now` checks again now, even if
a domain's next check is later.

## The ladder each domain climbs

Each `sending_domains` row has its own status. A run moves each domain as far as it can, then
stops at the first thing it must wait for.

| Status | Done | Next step | Card stage |
|---|---|---|---|
| planned | nothing yet | buy the domain (spends) | 20 - Buying Domains |
| bought | the domain is ours | order the inboxes (spends) | 30 - Setting Up Inboxes |
| ordered | the inbox provider has the order | set the DNS: point the nameservers, or the provider's staff do it | 30 |
| nameservers_set | DNS points at the provider | wait for the inboxes to be made | 30 |
| inboxes_active | the inboxes exist | the auth gate: SPF, DKIM, DMARC and MX all answer | 30 |
| dns_verified | the records pass | upload to the warm-up tool and start warm-up | 30 |
| warming | warm-up is on | wait the warm days (Google steps down to 30 a day on day 14) | 40 - Warming |
| ready | warmed | nothing | 100 - Ready To Send |

The card's stage follows the domain that is furthest behind. It only moves forward.
At the end it sets `warmup_started_on` and `ready_on` on the card, and adds the new domains to the
client's `sending_domains`.

## When something waits or fails

- A wait is normal. The note on the domain row says what it waits for and when it checks again.
- A wait past `give_up_hours` (config.json) posts once in needs-a-person. It keeps checking.
- A failure stops only that domain. It writes `last_error` on the row and posts once in
  pipeline-errors. Fix the cause, then run it again.
- A price above the approved price is a failure: nothing is bought. Plan again for a new price.

## The daily job

The existing daily job runs `scripts/daily.py`. It has no schedule of its own. For each card in
stage 20, 30 or 40 it runs live but **never buys or orders**: it checks the nameservers, the
inboxes and the records, starts the warm-up and marks domains ready. A buy or an order waits
with the note "A person must run the live set-up (--live) to ...". A card with no approval is
left alone.

## On the automation server (on demand)

`run_skill("sending-estate-provision", {"batch": "<card id>", "live": true})`, or a POST to
`/skill/sending-estate-provision` with the same body. One call moves the card as far as it can
now and returns. It does not wait for DNS or warm-up, so it never runs long. No new app, no
schedule.

## Vendors

Each vendor is a small class behind one interface. The card's `domain_registrar` and
`inbox_provider` pick the class.

| Job | Built in | File |
|---|---|---|
| Registrar | Porkbun | `../sending-domain-names/scripts/sending_registrars.py` |
| Outlook inboxes | Inboxing | `scripts/sending_providers.py` |
| Google inboxes | ScaledMail | `scripts/sending_providers.py` |
| Warm-up | PlusVibe | `scripts/sending_warmup.py` |

To add one, copy a class, list its keys and where to get them, and add it to the list at the end
of the file. Then set it in the plan's `config.json`. `references/` has each vendor's API shapes
and lessons.
