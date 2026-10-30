# The onboarding form

The form your new clients fill in. It runs on your own Cloudflare account and saves into your own
Supabase project.

## How it works

- **One link per client:** `https://onboarding.youragency.com/form/<code>?email=&company_name=`.
  The code is the client's `form_code` in the clients table. It is random, so nobody can guess it.
  The OS has a "Copy form link" button on each client.
- **The team at the client fills it in together.** The answers are saved on the server as people
  type. Everyone who opens the link sees the same answers, on any computer. The browser keeps nothing.
- `?email=` and `?company_name=` in the link fill those answers, but only when they are still empty.
- **No code in the link** (`/form`): the form asks for the company name, makes a new client at
  onboarding stage "0 - Paid", and then carries on as that client's link.
- **Submit works once per client.** It saves one row in `onboarding_forms` and sets the client's
  `form_received_at`. After that, the link shows "This form is already in".
- A question that is hidden (its `show_if` does not match) is never checked and never saved.
- The form never asks for a password or a key. Access questions ask the client to invite you instead,
  with a "Not yet" answer that you sort out on the onboarding call.

## The files

```
apps/onboarding/
├── questions.json          THE QUESTIONS. Change the form here, and only here.
├── worker/worker.js        The server: saves drafts and answers in Supabase with the secret key.
├── site/
│   ├── index.html          The start page at /
│   └── form/               The form page: index.html, app.js, styles.css, config.js
├── tools/
│   ├── validate_questions.py   Checks questions.json. deploy.py runs it first.
│   └── deploy.py               Puts the form live on your Cloudflare account.
└── tests/                  Offline tests (no Supabase, no Cloudflare needed)
```

## Change a question

1. Edit `questions.json`. Each question has a `step` (its page), an `id` (lower case, never change
   it once clients have answered), a `label`, a `type` and `required`.
   Types: `short_text`, `long_text`, `email`, `url`, `single_select`, `multi_select`, `checkbox`
   (Yes, this is done / Not yet).
   Extras: `help`, `placeholder`, `options`, `show_if`, `none_option` (a tick under a text box, for
   example "We do not have a website yet"), `info`, `links`, `chips`, `prefill`.
2. Check it: `python3 apps/onboarding/tools/validate_questions.py`
3. Put it live: `python3 apps/onboarding/tools/deploy.py`

`full_name`, `email` and `company_name` must stay on page 1: the form uses them to say who sent it.
The thank-you page is the `done` block. Put your booking link in `done.links[0].url` to show a
"Book the call" link (an empty url hides it). `intro` is the grey box on page 1.

To use your own colours, change `--brand` at the top of `site/form/styles.css`. The agency name at the
top of the form comes from `agency_name` in the settings table.

## Test it on your computer

Needs Node 18 or later. From `apps/onboarding`:

```
npm install
npm test              the server tests, on a throwaway copy of your database tables
npm run dev           the form at http://127.0.0.1:8787, on a throwaway database with the example clients
npm run test:browser  the form in a real browser (needs: npm install --no-save playwright && npx playwright install chromium)
```

## Put it live

`deploy.py` reads these from `.env` at the top of the repo. Put the values in the file, never in the chat.

| Name | What it is |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Your Cloudflare API token (tab 2, Step 2: Cloudflare Pages Edit, DNS Edit, Zone Read) |
| `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare account ID |
| `CLOUDFLARE_API_KEY`, `CLOUDFLARE_EMAIL` | Only with no token: the global API key and the email you sign in with |
| `SUPABASE_URL` | Your Supabase project address |
| `SUPABASE_SECRET_KEY` | Your Supabase secret key. It is stored as a Cloudflare secret and never reaches the browser |
| `ONBOARDING_DOMAIN` | Optional: `onboarding.youragency.com` |
| `ONBOARDING_PROJECT` | Optional: the Pages project name (default `onboarding-form`) |
| `OS_AUTOMATIONS_URL`, `OS_SHARED_SECRET` | Optional, from the automations set-up: a new form is then posted in the new-tasks channel |

```
python3 apps/onboarding/tools/deploy.py --domain onboarding.youragency.com
```

It makes the Pages project, saves the settings, deploys, adds the DNS record (when the domain is on
Cloudflare; if not, it prints the record to add by hand), writes the form address into
`settings.onboarding_url`, and checks the live form. When the domain is still pending, run it again
later with `--verify-only`.

## What is saved

- `onboarding_form_drafts`: one row per client while the form is being filled in. Only the form's
  server can read it.
- `onboarding_forms`: one row per submitted form. `answers` holds one entry per question:
  `{"n": 1, "step": 1, "label": "Your name", "type": "short_text", "value": "..."}`. Sort by `n` to
  show the answers in form order. `"none": true` marks a ticked "none" box.
- `clients.form_received_at`: the date the form came in.

When `OS_AUTOMATIONS_URL` is set, each Submit also sends
`POST <OS_AUTOMATIONS_URL>/form-submitted` with the header `X-OS-Secret` and
`{"onboarding_form_id": "...", "client_id": "..."}`. A failed call never stops a Submit.
