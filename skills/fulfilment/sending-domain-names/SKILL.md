---
name: sending-domain-names
description: Proposes domain names to send cold email from for one client - brand variants such as tryacme.com, or generic names - and checks each name is free and not premium at the registrar. Never uses the client's main domain or a domain any client already has. Reads only, writes nothing, spends nothing. Use when the user says "suggest sending domains for <client>", "what domains can we buy for <client>?" or "check these names are free".
area: fulfilment
agency: cold-email
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY, PORKBUN_API_KEY, PORKBUN_SECRET_KEY]
runs_on: either
---

# Sending domain names

Cold email must not go out from the client's main domain. A bad week of sends can hurt the
domain the client uses for real mail. So we buy other domains that look like the brand.

This skill makes the list of names. The sending-estate-plan skill uses it to fill a plan. You can
also run it alone. It reads only. It writes nothing and buys nothing.

## What it needs

- `PORKBUN_API_KEY` and `PORKBUN_SECRET_KEY`: porkbun.com, sign in, Account, API Access, Create
  API Key. Read `references/registrar-porkbun.md` before the first buy.
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (tab 1).

## Steps

1. Give the client's name. The skill reads the client's website from the client row.
2. Run it:
   `python3 skills/fulfilment/sending-domain-names/scripts/propose_domains.py --client "Acme Dental" --count 10`
3. It prints the names, the price for one year and the style of each name.
4. Show the user the list. Names it could not check are marked "not checked".

Options:

| Option | What it does |
|---|---|
| `--style branded` | brand variants: get, try, use, hey + the brand (the default in config.json) |
| `--style generic` | names with no tie to the brand, for clients who want no link to their name |
| `--style mix` | both, about half each |
| `--website` / `--brand` | use this website or brand word in place of the one on the client row |
| `--offline` | do not ask the registrar. The names are not checked. For a quick look only. |
| `--json` | print JSON, for another script |

## The rules it follows

- **Never the main domain.** It also leaves out every domain that any client already has: their
  websites, their contact email domains, their sending domains and every row in
  `sending_domains`.
- **Free means free at the registrar now.** A name the registrar cannot answer for is "not
  checked", never "free".
- **No premium names.** They cannot be bought by API and cost much more.
- **A price ceiling per ending.** A name above `max_first_year_price_usd` is left out.
- **Short and clean.** At most `max_name_length` characters: letters, numbers and dashes only. No word from
  `blocked_parts`, unless it is part of a word in `safe_words` (for example "scrap").
- **Spread.** Generic names use each root word and each prefix or suffix only a few times.
- If it cannot find enough free names, it stops with a plain message. Add prefixes or suffixes in
  `config.json`, or allow one more ending in `tlds`.

`references/naming-rules.md` says why each rule exists.

## Change the rules

All rules are in `config.json`: the prefixes, suffixes, endings, price ceilings, banned parts and
the default style. To use another registrar, add a class next to `Porkbun` in
`scripts/sending_registrars.py` and set `registrar` in `config.json`.

## On the automation server

`run_skill("sending-domain-names", {"client": "Acme Dental", "count": 10})`. It returns the list.
No new app, no schedule.
