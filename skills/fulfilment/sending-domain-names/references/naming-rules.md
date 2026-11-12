# Naming rules for sending domains

The lists live in `config.json`. This note says why each rule exists.

## Never the client's own domain

Cold email goes out from extra domains that look like the client's brand. The client's own
domain is never used. If the extra domains get a bad name with mail providers, the client's own
email still works. The skill reads the client's website and contact email, and never proposes
those domains.

## The three tiers

Short names look like real brands and get fewer spam marks. So the skill tries them in order:

| Tier | Shape | Example |
|---|---|---|
| 1 | prefix + brand | `tryacme.com`, `getacme.com` |
| 2 | brand + suffix | `acmehq.com`, `acmehub.com` |
| 3 | prefix + brand + suffix | `tryacmehq.com` (only when tiers 1 and 2 cannot fill the count) |

Inside a tier, shorter names go first. Tiers 1 and 2 give about 76 names for one brand word.
Most clients need 10 to 40 domains.

## Endings

- `.com` first. It has the most trust.
- `.co` second, often free when `.com` is taken.
- Never `.info`, `.xyz`, `.click`, `.top`, `.buzz` or `.loan`. Some people and filters see them
  as spam.

## What is left out

- Longer than 40 characters. Aim for under 20.
- The parts `mega`, `ultra` and `grp`. They look like spam.
- A blocked word anywhere in the name, also across the join. Example: "the" + "rapist" makes
  "therapist". The list of blocked words is in `config.json` (`blocked_parts`). A safe word can
  cover a blocked word ("skill" has "kill" in it). Those are in `safe_words`.
- A name another client already uses, or any name in the agency's registrar account. Never use
  one domain for two clients.
- A premium name, or a name over the price limit (`max_first_year_price_usd`). The registrar
  says the price when it says the name is free.

## Branded, generic or mix

- **Branded**: built from the client's brand. The domains show who sends.
- **Generic**: built from neutral root words (`cedar`, `basalt`, `juniper` ...). The domains can
  be used again for another client after this client leaves. At most 2 domains for one root
  word, and at most 3 domains with the same prefix or suffix, so the domains do not look like one
  family.
- **Mix**: half each, generic first.

## Timing (for the set-up that comes after)

- After a nameserver change, wait at least 15 minutes, then check. Some domains take hours.
- New inboxes take hours (Outlook) or days (Google) to be ready. Never send to a warm-up tool
  before the provider says they are active.
- Check SPF, DKIM and DMARC, then warm at least 14 days before any cold email. Warm-up never
  stops while the inbox is in use.
