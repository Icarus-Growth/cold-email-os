# ScaledMail API (the built-in Google Workspace provider)

Official docs: https://api.scaledmail.com/ (index: https://api.scaledmail.com/llms.txt).
Help centre: https://helpcenter.scaledmail.com. Read in 2026. The docs show example answers but
empty schemas, so field names in answers are likely, not certain. Check `llms.txt` again before
you change this code: endpoints have come and gone.

Labels: VERIFIED = in the official API docs. SECONDARY = help centre. UNVERIFIED = not found.

## Basics

| Item | Fact | Label |
|---|---|---|
| Base URL | `https://server.scaledmail.com/api/v1` | VERIFIED |
| Auth | Header `Authorization: Bearer <key>` (Settings, API Token; admins only) | VERIFIED |
| Workspace | Every call takes `organization_id` as a query value. Get it from `GET /organizations`. | VERIFIED |
| Rate limit | 5 requests a second | VERIFIED |
| Billing | A card on file. Every order charges it at once and starts a monthly subscription. No balance call. | VERIFIED |
| Webhooks | None. Poll. | UNVERIFIED |

## The calls this skill uses

| Call | Kind | Answer |
|---|---|---|
| `GET /domains?organization_id=` | read | `{domains: [{id, domain, status, order_id, total_mailboxes, ...}]}`. Only domains on a live order. Used before every order, so a domain is never ordered twice. |
| `POST /create-custom-order?organization_id=&provider=other` | **SPENDS** | See below. |
| `GET /mailboxes/{domain_id}?organization_id=` | read | `{mailboxes: [{email, first_name, last_name, alias, status}]}`. Empty until the inboxes are made. Never add `password=true` in this skill: it returns passwords in plain text. |
| `POST /calculate-package` | read (a free quote) | `{volume, period: "month", providers: ["google"], tier}`. No charge. Use it to check the price in config.json. |

## Ordering Google inboxes

```json
{
  "tag": "agency-acmedental",
  "providers": {"google": {"mailboxes_per_domain": 2, "domains": [
    {"domain": "tryacme.com", "redirect": "https://acme.example.com",
     "aliases": [{"first_name": "Jane", "last_name": "Doe", "alias": "jane"},
                 {"first_name": "Jane", "last_name": "Doe", "alias": "jane.doe"}]}]}},
  "sequencer": {"provider": "PlusVibe", "username": "<sign-in email>", "password": "<password>",
                "link": "https://app.plusvibe.ai", "workspace": "<client workspace name>"},
  "hosting": {"provider": "Porkbun", "username": "<registrar sign-in>", "password": "<password>",
              "link": "https://porkbun.com"}
}
```

| Field | Rule |
|---|---|
| `tag` | Up to 20 characters. |
| `mailboxes_per_domain` | Google: 2, 3 or 4. |
| `aliases` | One per inbox: the part before the @. The count must equal `mailboxes_per_domain`. This is how the plan's exact addresses are kept. |
| `redirect` | The forward to the client's site. Cannot be empty when sent. |
| `provider=other` | You own the domain at another registrar. Then `hosting` is required: the registrar's **website sign-in**, not its API key. ScaledMail's staff sign in and set the DNS. |
| `sequencer` | Staff upload the inboxes into the sending tool with this sign-in. There is no API to check it: the skill checks in the warm-up tool. |
| One order, many domains | Up to 100 Google domains an order. Any used or taken domain fails the whole order. The skill places one order for the run; if it is refused, it orders each domain on its own so one bad domain stops only itself. |

## DNS

There is no DNS or nameserver call. ScaledMail's staff connect the domain at the registrar
(SPF, DKIM, DMARC, the forward). The skill waits until the domain's nameservers move away from
the registrar's own, then checks the records itself (the auth gate).

- Staff publish DMARC `p=reject` from day one, with reports to their own mailbox (SECONDARY).
  The auth gate notes it. Ask ScaledMail if you want reports sent to you.
- If the registrar asks for a two-step code, staff email you and the order stops until you
  answer. An order in "New Order" for 3 days or more is usually waiting for this (SECONDARY).
  Turn off the code for the shared registrar sign-in, or watch your email.
- A domain once used with another Google or Microsoft account fails set-up (SECONDARY).

## Status and timing

Order: `Pending Form` → `New Order` (staff waiting for something) → `Active`. Cancelled path:
`Pending Cancellation` → `Cancelled`. The skill calls a domain ready when `GET /domains` says
`Active` AND `GET /mailboxes` lists its inboxes. Typical time: 1 to 3 days. After 7 days the
skill tells a person.
