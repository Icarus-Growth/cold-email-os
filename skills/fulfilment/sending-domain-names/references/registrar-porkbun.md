# Porkbun API (the built-in registrar)

Official docs: https://porkbun.com/api/json/v3/documentation and the full spec at
https://porkbun.com/api/json/v3/spec. Machine-readable notes: https://porkbun.com/llms-full.txt.
Read in 2026. Docs change: check the spec before you rely on a detail.

Labels: VERIFIED = in the official spec. UNVERIFIED = not stated; test it first.

## Basics

| Item | Fact | Label |
|---|---|---|
| Base URL | `https://api.porkbun.com/api/json/v3`. HTTPS only. | VERIFIED |
| IPv4-only base | `https://api-ipv4.porkbun.com/api/json/v3`. Use it when the key has an IP allowlist. | VERIFIED |
| Auth | JSON body `{"apikey": "...", "secretapikey": "..."}` (the field is `secretapikey`). Or the headers `X-API-Key` and `X-Secret-API-Key`, used only when the body has no keys. | VERIFIED |
| Sandbox | Keys that start `pk1_sb_` / `sk1_sb_`. Same base URL. Buys, DNS and nameserver changes are simulated with fake credit. Prices are real. | VERIFIED |
| Dry run | `dryRun: true` on `domain/create`, `dns/create`, `dns/edit*`, `dns/delete*`, `domain/updateNs`. It checks and returns `wouldSucceed`, and changes nothing. | VERIFIED |
| Idempotency | Header `Idempotency-Key` (up to 255 characters) on any POST. Kept 24 hours. Same key + same body = the first answer again, nothing bought twice. Same key + other body = 409. | VERIFIED |
| Errors | `{"status": "ERROR", "message": "...", "code": "INVALID_DOMAIN", "next_action": {...}}`. Use `code`, never the message (messages change). A 200 with `status: ERROR` is also an error. | VERIFIED |
| Rate limits | Single check: 10 per 10 seconds. Bulk check: 25 names a call, 200 names a minute. Buy: 1 try a second. Over the limit: HTTP 429 with `Retry-After`. | VERIFIED |

## The calls this skill set uses

| Call | Kind | Body / answer |
|---|---|---|
| `POST /domain/checkDomain` | read | `{domains: [up to 25]}` → `{domains: {name: {avail, price, premium, minDuration}}, unresolved: [...]}`. `avail` and `premium` are the strings "yes"/"no". `price` is a USD string for one year. A name in `unresolved` is unknown, not free. |
| `POST /domain/checkDomain/{domain}` | read | → `{response: {avail, price, premium, minDuration}}`. The price to pay right before a buy. |
| `POST /domain/listAll` | read | `{start: 0}` → `{domains: [...]}`, 1000 a page. Stop when a page has fewer than 1000. |
| `POST /domain/get/{domain}` | read | → `{domain: {...}}`, or 404 `DOMAIN_NOT_FOUND`. |
| `GET /account/balance` | read | Header auth. → `{balance: <cents>}`. Buying pays from this credit, not a card. |
| `POST /domain/create/{domain}` | **SPENDS** | `{cost: <cents>, agreeToTerms: "yes", whoisPrivacy: true}` + `Idempotency-Key`. `cost` is whole cents and must equal the quote for the shortest term (`price x minDuration`). There is no `years` field. |
| `POST /domain/updateNs/{domain}` | changes | `{ns: ["ns1...", "ns2..."]}`. Compare nameservers as a set: the order means nothing. |
| `POST /dns/create/{domain}` | changes | `{name, type, content, ttl, prio}`. `name` is the part before the domain ("" = the domain itself, "_dmarc"). A record that is already there gives `DUPLICATE_RECORD`: treat as done. A `warnings` list means Porkbun is not the DNS host, so the record will not work. |
| `POST /domain/addUrlForward/{domain}` | changes | `{subdomain: "", location, type: "permanent", includePath: "no", wildcard: "no"}`. Gives no id: read back with `getUrlForwarding`. |

## Before the first buy (one time, by a person)

1. Verify the account email and phone at Porkbun.
2. Buy one domain by hand. The API cannot buy on an account with no buy before.
3. Turn on **Opt In All Domains** at porkbun.com, Account, API Access. Without it, a new domain
   may refuse API changes (there is no API call to turn it on).
4. Add credit to the account. The skill checks the credit before it buys anything.

## Lessons

- New domains come back locked for transfer and with WHOIS privacy on.
- Premium names cannot be bought by API. The naming step leaves them out.
- A key with a domain allowlist may not be able to buy new names. Use a key with no domain
  allowlist for buying. (UNVERIFIED)
- A new domain has parking records. They can block a URL forward until they are removed.
