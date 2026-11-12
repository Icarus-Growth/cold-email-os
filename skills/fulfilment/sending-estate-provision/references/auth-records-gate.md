# The auth gate (SPF, DKIM, DMARC, MX)

No warm-up starts until all four records answer. Code: `scripts/sending_dns.py`, `check_auth`.

| Record | Passes when | Where it looks |
|---|---|---|
| SPF | a `v=spf1` TXT record on the domain that **includes the inbox provider**: `include:_spf.google.com` (Google) or `include:spf.protection.outlook.com` (Microsoft 365) | `TXT <domain>` |
| DKIM | a key at the first selector that answers, in this order: `default`, `google`, `selector1`, `selector2`. A TXT with `v=DKIM1` or `p=` counts. A CNAME counts too: Microsoft 365 puts its key behind one. | `TXT` / `CNAME <selector>._domainkey.<domain>` |
| DMARC | a `v=DMARC1` TXT record (any policy) | `TXT _dmarc.<domain>` |
| MX | at least one MX record | `MX <domain>` |

Lookups use Google Public DNS over HTTPS (`https://dns.google/resolve?name=...&type=...`), so
nothing extra is installed.

## A missing record makes the domain wait, not fail

A brand-new domain often fails every check while DNS spreads. The skill checks again every 30
minutes. After 72 hours it tells a person in needs-a-person, with the missing records named,
and keeps checking.

## What the gate does not do

- **It is a set-up check, not the health check.** Records that pass do not mean mail lands in
  the inbox. After warm-up, reply rates are the health signal.
- **It does not change the DMARC policy.** A usual path is `p=none` at the start, then
  `p=quarantine` after about 14 days, then `p=reject` after 30 clean days. Some providers
  publish `p=reject` from day one. The provider owns the DNS, so the gate only notes it.
- **It does not end the warm-up.** Warm-up stays on for the life of every inbox. "Ready" means
  "warmed at least 14 days" (21 for big-company targets).
