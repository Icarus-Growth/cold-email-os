# The OS app

The screens the team uses every day: My Work (the home page: what waits on you), Dashboard, Tasks
(one tab per board), Clients, Team and Onboarding forms. It is a React app that reads and writes the Supabase database directly, with
each person's own sign-in. The database rules (RLS) decide what each person can see and change.

## Run it

```
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check, then build into dist/
npm test         # tests: Team server steps (no network), My Work (who acts next, View as), the copy editor, the page loads
```

The app reads two values from the `.env` file at the top of the repo (or from the Cloudflare
Pages build settings):

| Name | What it is |
| --- | --- |
| `SUPABASE_URL` | The project address. |
| `SUPABASE_PUBLISHABLE_KEY` | The publishable key. It is safe in a browser. The build stops if you put the secret key here. |

## Put it live

Tab 2 (`docs/2-os-setup.md`) walks you through it. The two scripts:

```
python3 apps/os/frontend/tools/domain.py --help                       # buy a domain, move it, add records
python3 apps/os/frontend/tools/deploy.py --domain app.youragency.com  # build, deploy, attach, check
python3 apps/os/frontend/tools/deploy.py --dry-run --domain app.youragency.com   # show every call, make none
```

Run them from the top of the repo. They read the keys from `.env` and never print one.

## Change it for your agency

- `src/agency.config.ts` holds your boards, their stages, their fields and the dashboard numbers.
- `src/core.config.ts` holds the parts every agency has: tasks, clients, team, calls.
- `src/theme.css` is the only file with colours.
- `src/ui/` holds the screen parts every screen uses (buttons, tables, boards, panels). Change them with care: a change shows on every screen.
- A field with `type: 'document'` is a copy document (change 0013): written in the app's own editor,
  with `link` naming the column for "paste a link instead". `check` adds the agency type's line:
  `cold-email`, `ad-script`, `caption` or `email-copy`.
- The cold email checks follow one file per sending tool in `src/lib/senders/` (Instantly, Smartlead,
  PlusVibe). When a tool changes how it writes spintax or merge fields, change that file.

The stage lists must match the database exactly. After you change a stage in a migration, run
`python3 tests/config_matches_db.py` from the top of the repo. It tells you what to change.

## Copy documents

"Open editor" on a card or a client page opens the document over it, at its own address
(`?doc=copy_doc`). It saves 1 second after typing stops and on close. When someone else saved first,
it stops saving, keeps your text on screen and says so; Reload shows their version. History holds the
last 20 saves. The Readability switch (top right, remembered in this browser) shows the grade, the
counts and the marks. All checks run in the browser: no text is sent anywhere.

## The server steps

"Add team member" and "Resend access" must make logins, which needs the Supabase secret key. They
run on Cloudflare next to the app (`functions/api/team/`), so the key never reaches a browser.
They only work on the deployed app, not on `npm run dev`.

`python3 apps/os/frontend/tools/deploy.py` sets them for you from `.env` (tab 2). By hand, they are in
Cloudflare Pages > Settings > Variables and Secrets:

| Name | What it is |
| --- | --- |
| `SUPABASE_URL` | The project address. |
| `SUPABASE_SECRET_KEY` | The secret key. Add it as a secret, never as a plain variable. |
| `OS_AUTOMATIONS_URL` | Optional (tab 3). The address of the automations app. When set, the access message is also sent to the person on Slack. |
| `OS_SHARED_SECRET` | Needed with `OS_AUTOMATIONS_URL`. The same value the automations app has. |

"Connect your AI" and "Revoke" (`functions/api/team/ai.js`) pass the call on to the automations app's
`/mcp/token` (tab 5), which makes or kills the person's private AI link. They need `OS_AUTOMATIONS_URL`
and `OS_SHARED_SECRET`. The box shows, once, the server address (`/mcp/`, not secret), the key, and the lines
for each AI tool from tab 5, Step 4 (`src/lib/ailink.ts`). Claude Code, Codex and Hermes send the key in
an `Authorization: Bearer` header, so it stays out of Modal's request log. Claude on the web takes only
an address: it gets the `/mcp/s/<key>/` link, with tab 5's warning.

Only an Active Owner or Admin with "Can sign in" ticked can use them. Only an Owner can add
another Owner. Each person gets a random temporary password and must choose their own the first
time they sign in.
