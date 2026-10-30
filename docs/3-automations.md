# Tab 3: Automations (Cold Email agency OS)

**How to use this tab.** Do tabs 1 and 2 first. Open this repo's folder in your AI tool and paste everything below the line. This tab needs an AI that can run terminal commands (for example Claude Code or Codex), because Modal is set up from the terminal. Never paste a key, token or password into the chat: the AI tells you which file to put it in.

---

You are setting up the automations for a cold email agency's operating system: Slack alerts when a card moves, a post in new-tasks for every new client, and a daily summary. They run as one small app on my own Modal account. The code is already in `apps/os/automations/`. You set it up; you do not write new automation code.

Work through the steps below in order. After each step, tell me what you did in one or two short sentences, then go on. Stop and wait for me only where a step says **STOP**. If a command fails, show me the error in plain words and stop. Do not try a different, riskier way on your own.

## The rules (keep these for the whole job)

1. **Automated posts go only in channels made for them.** Never post in a channel where people talk. Nothing is ever posted in a client channel, and the OS never makes a client channel: the client channels already exist, and Step 4 only links them.
2. **Every post has four parts:** context (client, card, stage, due date), action (the one thing to do), notification (it tags one person) and navigation (a button that opens the card in the OS). Each kind of post has its own name and emoji.
3. **A failed automation posts once** in pipeline-errors (once a day at most for the same failure). If even that fails, it stays quiet: the team still has the board.
4. **Keys and tokens go in `.env` only**, never in a table, a commit, a file in this repo or the chat. The Modal address and the shared secret go in the database vault, not in a table.
5. **Do not change the rule files by guessing.** `apps/os/automations/alert_rules.json` says which stage move posts where. Change it only when I ask, and run the tests after (Step 10).
6. **Load `.env` into the terminal first**, in every new terminal: Mac or Linux `set -a; . ./.env; set +a`. Windows PowerShell: `Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }`. After Step 7 makes `.venv`, also turn it on in every new terminal: Mac or Linux `. .venv/bin/activate`, Windows PowerShell `.venv\Scripts\Activate.ps1`.

## Step 1. Check the settings

Run `python3 apps/os/backend/db.py query "select agency_name, os_url, onboarding_url, time_zone, daily_summary_hour, stuck_after_days from public.settings"` and show me the row.

- `os_url` must be the OS address from tab 2 (for example `https://app.youragency.com`), and `onboarding_url` the form address (for example `https://onboarding.youragency.com`). The buttons in Slack use them.
- Ask me for my agency's name, my time zone (for example Europe/London or America/New_York) and the hour for the daily summary (default 8, on weekdays).
- Fill in anything empty or wrong with one statement, for example:
  `python3 apps/os/backend/db.py query "update public.settings set agency_name = 'Your Agency', time_zone = 'Europe/London', daily_summary_hour = 8 where id = 1"`

## Step 2. The Slack app

If I have no Slack workspace yet, ask me to make a free one at https://slack.com/get-started. I must be allowed to install apps in it (in a workspace I made, I am).

1. Ask me to open https://api.slack.com/apps, press **Create New App → From a manifest**, pick my workspace, choose YAML, and paste all of `apps/os/automations/slack-app-manifest.yml`. Then **Install to Workspace** and allow it.
2. Ask me to copy the **Bot User OAuth Token** (OAuth & Permissions; it starts with `xoxb-`) into `SLACK_BOT_TOKEN` in `.env`. Not in the chat.
3. Check it: `python3 apps/os/automations/slack_setup.py check`. It must say PASS. If a permission is missing, ask me to paste the manifest again (App Manifest in the left menu) and reinstall.

## Step 3. The channels

The client channels already exist (for example `youragency-client1`). If I have no client channels yet, skip Step 4. Every other channel is made now, because automations do not belong in a channel where people talk. Show me this table:

| Channel | What is posted | Who is in it |
|---|---|---|
| new-tasks | A new card on any board, a new client, a new form submitted | Owner, managers |
| task-updates | A card is ready for its maker, blocked or rejected | Owner, makers |
| amendments | A card is sent back for changes, with the notes in the thread | Owner, makers |
| review | A card is ready for someone to check | Owner, managers |
| approved | A card reaches its last stage | Owner, makers, managers |
| daily-summary | The daily summary | Owner, managers |
| pipeline-errors | Any failed automation, once | Owner |
| needs-a-person | A card reaches a stage with nobody set to do it (once a day per card). A person with no Slack account linked is not posted here: the alert names them as plain text, and Step 5 links them | Owner |

1. Ask: "Do you want these names, or other names?" If I change a name, change only `"name"` in `apps/os/automations/channels.json` (keep the key on the left as it is).
2. Make them: `python3 apps/os/automations/slack_setup.py make-channels`. A channel that already has that name is used, not made again. It saves the channel ids in `channels.json`.
3. Who sits where follows the job, not rank. Ask me who are the makers (the people who do the work) and who are the managers (the people who check it). Then invite them by email, one channel at a time:
   `python3 apps/os/automations/slack_setup.py invite review owner@youragency.com manager@youragency.com`
   I add myself to every channel. The bot is already in each one.

## Step 4. Link the client channels

1. Show me the channels: `python3 apps/os/automations/slack_setup.py channels`.
2. Match them to the clients: `python3 apps/os/automations/slack_setup.py link-clients`. Show me the list. **STOP** and ask me to fix any wrong match. Fix one with `--set "Client name=channel-name"` (repeat it for more), then save with `--save`, for example:
   `python3 apps/os/automations/slack_setup.py link-clients --set "Example Client A=youragency-example-a" --save`
3. A client with no match keeps an empty channel field. Tell me which ones. I add the channel id later on the client page (the field says where to find it). Never make a channel for a client.

## Step 5. Link the team

`python3 apps/os/automations/slack_setup.py link-team`. Show me the list. Anyone "NOT FOUND" uses another email in Slack: ask me for it and fix their email on their team page in the OS, or skip them. Then save: `python3 apps/os/automations/slack_setup.py link-team --save`.

## Step 6. My logo on every post

Slack needs a web address for the picture, not the picture itself. So the logo is saved in the OS app (it is published with the OS) and its address goes in `.env`.

1. Ask me to make a free account at logo.dev and copy the **publishable key** (it starts with `pk_`) into `LOGO_DEV_PUBLISHABLE_KEY` in `.env`.
2. Ask me for my company's domain (for example `youragency.com`). Get the logo: `python3 apps/os/automations/logo.py fetch youragency.com`. It saves `apps/os/frontend/public/slack-logo.png`.
3. Open the file so I can see it. **STOP** and ask: "Is this your logo?" If not, ask me for a square PNG of my logo and save it at the same place.
4. Deploy the OS again, the same way as in tab 2, so the logo is published. Then check the address: `python3 apps/os/automations/logo.py check https://<my OS address>/slack-logo.png`. It must say PASS.
5. Put that address in `SLACK_ICON_URL` in `.env`.
6. Ask me to use the same PNG as the Slack app's own icon: the app page → Basic Information → Display Information → App icon.

## Step 7. Modal (my own account)

1. Ask me to make a free account at modal.com.
2. Install Modal on this computer, in a separate Python folder for this repo (`.venv`, which git ignores). Many computers refuse a plain `pip install` ("externally-managed-environment").
   - Mac or Linux: `python3 -m venv .venv`, then `. .venv/bin/activate`.
   - Windows PowerShell: `python -m venv .venv`, then `.venv\Scripts\Activate.ps1`.
   Then: `python3 -m pip install -r apps/os/automations/requirements.txt` (Windows: `python -m pip ...`). Turn `.venv` on in every new terminal (rule 6).
3. Log in once in the browser: `python3 -m modal token new`. Do not ask me for the token; Modal saves it on this computer.
4. Make the two secrets: `python3 apps/os/automations/connect_db.py secret`. `OS_SHARED_SECRET` is how the database and the OS prove who they are. `MCP_TOKEN_PEPPER` scrambles each person's AI connector key (tab 5). Both are made once and never shown. Never make the pepper again: a new one stops every AI key.
5. Load `.env` again (rule 6), then store the keys the app needs as one Modal secret called `agency-os`:
   - Mac or Linux: `python3 -m modal secret create agency-os --force SLACK_BOT_TOKEN="$SLACK_BOT_TOKEN" SUPABASE_URL="$SUPABASE_URL" SUPABASE_SECRET_KEY="$SUPABASE_SECRET_KEY" OS_SHARED_SECRET="$OS_SHARED_SECRET" SLACK_ICON_URL="$SLACK_ICON_URL" MCP_TOKEN_PEPPER="$MCP_TOKEN_PEPPER"`
   - PowerShell: the same, with `$env:SLACK_BOT_TOKEN` and so on in place of `$SLACK_BOT_TOKEN`.
   Do not print the values.
6. Deploy: `python3 -m modal deploy apps/os/automations/app.py`. The output shows a web address that ends in `-web.modal.run`. Put it in `OS_AUTOMATIONS_URL` in `.env`.
   **If the deploy fails with "reached limit of 5 scheduled functions"** (or any message about a limit on scheduled or cron functions), **STOP** and tell me in plain words: "Modal's free plan allows 5 scheduled jobs in your whole Modal account, and all 5 are used. This app needs one, for the daily summary. Stop one scheduled job you do not need, or upgrade your Modal plan. Then I deploy again." Show me my apps with `python3 -m modal app list`. Stop an app only when I name it: `python3 -m modal app stop <its name>`. Never take the daily summary's schedule out of the code to get round the limit.
7. Ask me to turn on the Slack buttons: the Slack app page → Interactivity & Shortcuts → On → Request URL: `<OS_AUTOMATIONS_URL>/slack/actions` → Save. Tell me the address to paste. (The buttons open the OS; this only stops Slack from showing a warning next to them.)
8. Two more apps call the automations: the OS (it sends a new team member their sign-in details in Slack) and the onboarding form (it posts each submitted form in new-tasks). Both deploy scripts take `OS_AUTOMATIONS_URL` and `OS_SHARED_SECRET` from `.env`. Load `.env` again (rule 6), then run both tab 2 deploy commands again (the OS, then the form).

After a change to `channels.json`, `alert_rules.json` or the code, deploy again (6). After a change to a key, run 5 and 6 again.

## Step 8. Connect the database to Modal

The database already has the two hooks (file `0008_automation_hooks.sql`, applied in tab 1): one when a card is added or moves, and one when a client is added. (A submitted onboarding form is sent by the form app itself: see Step 7.) They do nothing until they know the Modal address and the shared secret, which are kept in the database vault, not in a table.

1. Check the hooks are there: `python3 apps/os/backend/db.py query "select to_regprocedure('public.set_automation_hook(text,text)') is not null as ready"`. If it says false, apply the file once: `python3 apps/os/backend/db.py run <the file>`. It is in `apps/os/backend/supabase/migrations/`, or in `archive/migrations/` after the tab 1 tidy-up.
2. Store the address and the secret: `python3 apps/os/automations/connect_db.py connect`. It must say "Hooks on".
3. Test it: `python3 apps/os/automations/connect_db.py test`. All three lines must say PASS: a call without the secret is turned away, a call with it is let in, and the database itself reaches the Modal app.

## Step 9. Test it, then remove the test rows

1. **A card move.** Move one example card on the Tasks, Campaigns boards to a review stage (in the OS, or with a database update). Show me the post in the review channel: the client, the card, the stage, one person tagged, and an "Open the card" button that opens that card.
2. **A new client.** Add one test client: `python3 apps/os/backend/db.py query "insert into public.clients (client_name, is_example) values ('Example Test Client', true)"`. Within a minute, show me the post in new-tasks: the client, the account manager or "Nobody is the account manager yet", and an "Open the client" button. Check that no Slack channel was made.
3. **A form.** Open the test client's form link (on its page in the OS). Fill in every question marked * with test answers, then submit. Show me the post in new-tasks.
4. **The daily summary.** Run it once now: `python3 -m modal run apps/os/automations/app.py::summary_now`. Show me the post in daily-summary and its thread. Each person is tagged once.
5. **Errors.** Show me that pipeline-errors and needs-a-person are quiet, or tell me what each message there asks me to do.
6. Remove the test rows, form first: `python3 apps/os/backend/db.py query "delete from public.onboarding_forms where client_id in (select id from public.clients where client_name = 'Example Test Client')"`, then `python3 apps/os/backend/db.py query "delete from public.clients where client_name = 'Example Test Client'"`. Move the example card back.

If a step shows nothing: check pipeline-errors first, then the app's logs: `python3 apps/os/automations/logs.py` (Modal's log, with every AI connector link hidden; stop it with Ctrl+C). Do not read the log with `modal app logs` directly: Modal writes each request's address there, and an AI connector link (tab 5) is an address. **STOP** and tell me in plain words what you found.

## Step 10. Write it down

1. Run the checks: `python3 -m pytest apps/os/automations/tests tests/test_slack_notify.py`. All must pass. (If pytest is missing: `python3 -m pip install pytest`.)
2. Add a short "Automations" part to `CLAUDE.md`, then make `AGENTS.md` the same text, word for word:
   - The automations are one Modal app: `apps/os/automations/app.py`. Deploy with `python3 -m modal deploy apps/os/automations/app.py`.
   - Which stage move posts where: `apps/os/automations/alert_rules.json`. The channels: `apps/os/automations/channels.json`. After a change, run the tests, then deploy.
   - Every Slack post goes through `shared/slack_notify.py` and names itself. The database is read and written through `shared/supabase_client.py`.
   - A new board gets alerts when its table is added to `"boards"` and its stages to the rules in `alert_rules.json`.
   - Switch the database hooks off: `python3 apps/os/automations/connect_db.py off`.
   Under "Built so far", add: "Automations: Slack alerts, a new-client post in new-tasks and a daily summary at <hour> on weekdays, set up on <date>. The OS never makes or posts in client channels."
   Both files must stay under 150 lines. Check with `python3 tests/agents_md_check.py`.
3. Add to `DECISIONS.md`, under today's date: the channel names, who is in each channel, which clients have no linked channel yet, the summary hour and time zone, and anything under "Not built yet".

## Step 11. Tell me we are done

Give me a short list: the channels and who is in them, how many clients and team members are linked to Slack, the summary time, and that the three tests in Step 8 passed. Then commit everything (never `.env`) with the message "Automations set up", and tell me the next tab to open: **Tab 4, Second brain.**
