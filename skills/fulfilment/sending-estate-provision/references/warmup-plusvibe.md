# PlusVibe API (the built-in warm-up tool)

Official docs: https://developer.plusvibe.ai (index: https://developer.plusvibe.ai/llms.txt).
Help centre: https://help.plusvibe.ai. Read in 2026.

Labels: VERIFIED = in the official spec. SECONDARY = help centre. UNVERIFIED = not stated.

## Basics (VERIFIED)

| Item | Fact |
|---|---|
| Base URL | `https://api.plusvibe.ai/api/v1` |
| Auth | Header `x-api-key: <key>` (not Bearer). The API needs the Business plan. |
| Which key | The **account** key reaches every workspace. A workspace key reaches one. Use the account key: the skill makes one workspace per client. |
| `workspace_id` | On every call: a query value on GET, a body field on the rest. Not on `GET /authenticate`. |
| Rate limit | 5 requests a second |
| Ids | 24 hex characters. Read both `_id` and `id`. |

## The calls this skill uses

| Call | Kind | Body / answer |
|---|---|---|
| `GET /authenticate` | read | `{workspaces: [{_id, name}]}`. The key check and the workspace list. |
| `POST /workspaces/add` | changes | `{workspace_id: <any workspace you have>, workspace_name}` → `{_id}`. There is no find-by-name and no rename. Not safe to repeat: always list first, match the name, and only then add. |
| `GET /account/list` | read | `workspace_id, skip, limit` → `{accounts: [{_id, email, status, warmup_status, ...}]}`. No total: read pages until one is short. |
| `PUT /account/bulk-update` | changes | `{workspace_id, ids: [...], <fields>}`. Only the fields sent change. 100 ids a call in this skill. |
| `PATCH /account/bulk-update-warmup` | changes | `{workspace_id, ids: [...], warmup_status: "ACTIVE"}` |

## Warm-up fields (`PUT /account/bulk-update`)

| Field | Meaning |
|---|---|
| `warmup_max_daily_limit` | the most warm-up emails a day |
| `warmup_initial_daily_limit` | where the climb starts |
| `warmup_pace_increment` | how many more each day while it climbs (1 or more, even when the climb is off) |
| `bulk_warmup_is_slow_rampup` | "yes" = climb, "no" = flat |

The rules in `sending-estate-plan/config.json` map to these fields:

| Rule | Fields |
|---|---|
| Google: 5 a day, +5 a day up to 50 | max 50, initial 5, increment 5, slow ramp-up "yes" |
| Google: 30 a day after 14 days | max 30, slow ramp-up "no". PlusVibe cannot do this by age, so the skill sends it on day 14. |
| Outlook: 2 a day, flat | max 2, initial 2, increment 1, slow ramp-up "no" |

## Lessons

- There is no "keep warm-up on for ever" switch. Warm-up stays on unless someone turns it off.
  Check `warmup_status` if inboxes go quiet.
- The daily limit is a guide. PlusVibe may send fewer (SECONDARY). That is not a fault.
- Google Workspace and Microsoft 365 inboxes connect by sign-in, not by a plain API call. That is
  why the inbox providers upload them: ScaledMail's staff with the sign-in in the order, and
  Inboxing's workers through a platform connection. The skill then checks every inbox arrived.
- `POST /dfy/place-order` buys domains and inboxes from PlusVibe with no dry run. This skill
  never calls it.
