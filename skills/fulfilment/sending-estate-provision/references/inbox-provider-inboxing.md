# Inboxing API (the built-in Outlook / Microsoft 365 provider)

Official spec: https://v2.inboxing.com/openapi-v2.json. Summary: https://v2.inboxing.com/llms.txt.
Read in 2026. Do not mix it up with other products that have "inbox" in the name.

Labels: VERIFIED = in the official spec. UNVERIFIED = not stated; test it on one domain first.

## Basics (VERIFIED)

| Item | Fact |
|---|---|
| Base URL | `https://v2.inboxing.com/api/v2` |
| Auth | Header `X-API-Key: <key>` (Inboxing, Settings, API) |
| Rate limit | 120 requests a minute per key |
| Errors | `{"error": "<message>"}` |
| Domain id | The domain name works in place of the id in every `/domains/{id}` path |
| Webhooks | None. Poll. |

## The calls this skill uses

| Call | Kind | Body / answer |
|---|---|---|
| `GET /slots` | read | `{slots: {total, used, remaining}, system: {can_provision}}`. Each domain uses one prepaid slot. `can_provision: 0` = no free slot. |
| `GET /domains/{domain}` | read | The domain, or 404. Use it before every create: `POST /domains` has no idempotency key, so a retry after a timeout could make the domain twice. |
| `POST /domains` | **uses a paid slot** | See below. Answer: `{id, status, nameservers: [...]}` (`nameservers` can be empty at first). 400 `Domain slot limit exceeded` with no free slot. |
| `GET /domains/{id}/status` | read | `{status, failure_reason, nameservers, nameservers_auto_updated, ...}` |
| `GET /platform-connections` | read | The links to sending tools. The list view has no secrets. |
| `POST /platform-connections` | changes | Once per client workspace in the warm-up tool. See below. |
| `POST /domains/{id}/upload` | changes | `{platform_connection_id, enable_warmup: true, sync_tags: true, skip_verified: true}`. 400/403/409 while the domain is not active yet = wait. `skip_verified` makes a second upload safe. |

**Never log** `GET /registrars/{id}`, `GET /cloudflare-credentials/{id}` or
`GET /platform-connections/{id}`: they return passwords and keys in plain text.

## Ordering: one call makes the domain and its inboxes

```json
{
  "domain": "tryacme.com",
  "user_count": 49,
  "names": [{"first_name": "Jane", "last_name": "Doe", "email_prefix": "jane.doe"}, "... 49 in all"],
  "redirect_type": "REGULAR",
  "redirect_url": "https://acme.example.com",
  "registrar_credential_id": "optional: Inboxing then sets the nameservers itself"
}
```

- `user_count` is 25, 49, 50 or 99 only. The plan skill checks this.
- With an `email_prefix` on every name, `names` must have exactly `user_count` items, each
  prefix different. That is the only way to know every address before you pay, so the plan
  skill makes all 49 names itself and the approval shows them.
- `redirect_url` is the forward: web visits to the sending domain go to the client's site.

## How the domain connects: a nameserver takeover

1. `POST /domains` makes a DNS zone at Inboxing. Inboxing writes SPF, DKIM, DMARC and the
   forward in that zone itself. There is no "add these records yourself" mode.
2. Set the domain's nameservers at the registrar to the ones Inboxing gives. Or save the
   registrar login in Inboxing (Settings, Registrars) and send `registrar_credential_id`: then
   Inboxing sets them.
3. Wait at least 15 minutes, then check the nameservers resolve.

## Status

`pending` → `dns_setup` → `update_nameservers` → `queued` → `setting_up` → `active`.
Also `failed` (read `failure_reason`), `updating_names`, `deleting`, `deleted`.
Most domains are active in 1 to 6 hours. The inbox passwords file comes 24 hours after active.

## The sending tool link

`POST /platform-connections` for PlusVibe needs: `platform: "plusvibe"`, `name`, `username`
(your PlusVibe sign-in email), `password` (your PlusVibe password), `api_key`, `workspace_id`,
and optional `daily_limit` (1 to 5, default 2) and `warmup_daily_limit` (1 to 8, default 2).
Inboxing's workers sign in to PlusVibe as you, so the password is needed. Other tools it can
upload to: Instantly, Smartlead, Email Bison (each has its own fields).

## Open questions (UNVERIFIED)

- Does deleting a domain give the slot back?
- Does the 24-hour wait for the passwords file also block the upload?
- The exact DMARC policy it writes. The auth gate reads it and notes it.
