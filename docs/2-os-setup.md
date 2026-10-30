# Tab 2: OS set-up (Cold Email agency OS)

**How to use this tab.** Do tab 1 first. Open this repo's folder in your AI tool and paste everything below the line. This tab needs an AI that can run terminal commands (for example Claude Code or Codex), because the OS is put live from the terminal. Never paste a key, token or password into the chat: the AI tells you which file to put it in.

---

You are putting a cold email agency's operating system live: the OS (the screens the team uses every day) and the onboarding form (the link each new client fills in). Both run on my own Cloudflare account. The database from tab 1 holds the data. The code is already in this repo. You set it up; you do not write new code.

Work through the steps below in order. After each step, tell me what you did in one or two short sentences, then go on. Stop and wait for me only where a step says **STOP**. If a command fails, show me the error in plain words and stop. Do not try a different, riskier way on your own.

## The rules (keep these for the whole job)

1. **Keys go in `.env` only**, never in the chat, a commit or a file in this repo. Do not open `.env` to check it: that would show you every key. The scripts read it and say what is missing.
2. **Never buy anything without my yes to the exact price.** A domain is bought only after I say yes to the name and the price you showed me.
3. **Never repeat a password.** When a command prints a temporary password, tell me to copy it from the output. Do not write it in your reply or in any file.
4. **Load `.env` into the terminal first**, in every new terminal: Mac or Linux `set -a; . ./.env; set +a`. Windows PowerShell: `Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }`.
5. **Every command here is safe to run again.** If a step stops half way, fix the cause and run the same command again.

## Step 1. Check what tab 1 left

1. `python3 apps/os/backend/db.py query "select full_name, email, access, can_sign_in from public.team where access = 'Owner'"`. It must show me as the Owner, with `can_sign_in` true. If not, **STOP** and tell me to finish tab 1, step 6.
2. `node --version`. It must be 20 or higher. If not, ask me to install Node.js LTS from nodejs.org, then check again.

## Step 2. Cloudflare

1. Ask me to make a free Cloudflare account at dash.cloudflare.com (if I do not have one).
2. Ask me to make an API token. It can do only what this OS needs, so it is safer than the Global API Key. Tell me these steps:
   - Click the person icon (top right) → Profile → API Tokens → **Create Token** → Custom token: **Get started**.
   - Token name: `Agency OS`.
   - Permissions, one row each (press "+ Add more" for the next row):
     - Account · Cloudflare Pages · Edit
     - Zone · DNS · Edit
     - Zone · Zone · Read
   - Zone Resources: Include · All zones from an account · my account.
   - Continue to summary → Create Token. Cloudflare shows the token once.
3. Ask me to put these two in `.env`. Do not ask me to paste them here.
   - `CLOUDFLARE_API_TOKEN`: the token from part 2.
   - `CLOUDFLARE_ACCOUNT_ID`: Account home → the three dots next to my account name → Copy account ID. (It is also the long code in the address bar after `dash.cloudflare.com/`.)
   If I already use the Global API Key and want to keep it, `CLOUDFLARE_API_KEY` and `CLOUDFLARE_EMAIL` work in place of the token. The scripts use the token whenever one is set.
4. Check them: `python3 apps/os/frontend/tools/domain.py keys`. It must say "Cloudflare: OK".

## Step 3. My main domain

1. Ask me: "What is your agency's main domain, the one your website is on? For example youragency.com. If you have none, or you do not want to use a domain now, say so."
   If I say I do not want a domain now, skip the rest of this step. In Step 4 the answer is "No domain for now".
   If I say I have none, skip the rest of this step. In Step 4 I can buy one (1) or choose "No domain for now" (3). A subdomain (2) needs a main domain. A domain I buy becomes my main domain.
2. Find where its records are kept: `python3 apps/os/frontend/tools/domain.py where <main domain>`. Tell me the answer in one line (Cloudflare, Porkbun or another company) and ask me if that is right. I may know better. The answer decides how records are added for the rest of this tab:
   - **Cloudflare:** the deploy scripts add the records for me.
   - **Porkbun:** the records are added through the Porkbun API. I need the Porkbun keys (Step 4, part "Porkbun keys").
   - **Another company:** you show me each record, I add it by hand, and you wait until it works.
3. When I use a domain (a new one or a subdomain in Step 4), the onboarding form is at `onboarding.<main domain>`. With no domain, the form is on its free `pages.dev` address too.

## Step 4. Where the OS lives

Ask me: **"Where do you want the OS to live? 1. A new domain you buy for it. 2. A subdomain of your main domain. 3. No domain for now: the OS and the form run on their free pages.dev addresses; add a domain later with this tab."** **STOP** and wait for my answer.

**Porkbun keys** (needed for a new domain, and when my main domain's records are on Porkbun):
1. Ask me to make a Porkbun account at porkbun.com if I do not have one, and to verify my email and phone there.
2. Ask me to make an API key at porkbun.com/account/api. It needs these permissions: read, domains (name servers and DNS) and, for a new domain, purchase. Then put `PORKBUN_API_KEY` and `PORKBUN_SECRET_KEY` in `.env`.
3. Check them: `python3 apps/os/frontend/tools/domain.py keys --porkbun`.

**If I said "a new domain"** (Porkbun only):
1. Get the Porkbun keys above.
2. Ask me for the name I want (for example `youragencyos.com`). Check it: `python3 apps/os/frontend/tools/domain.py check <name>`. Show me if it is free, the first-year price and the yearly renewal price. If it is taken, ask for another name.
3. Porkbun pays from account credit, not from a saved card. If `check` says the credit is too low, ask me to add credit at porkbun.com/account/credit, then check again.
4. Ask me: **"Buy <name> for <price>, renewing at <renewal price> a year?"** **STOP** and wait. Go on only if I say yes to that name and that price. Anything else: do not buy.
5. Buy it, with the cost number `check` printed: `python3 apps/os/frontend/tools/domain.py buy <name> --cost <number> --yes`. If it says the price changed, show me the new price and ask again.
6. Adding a domain to Cloudflare needs one more right on the token. Ask me to open Profile → API Tokens → `Agency OS` → Edit, and change the row Zone · Zone · Read to **Edit**. The token stays the same, so `.env` does not change. (With the Global API Key, skip this.)
   Then move it to Cloudflare: `python3 apps/os/frontend/tools/domain.py to-cloudflare <name>`. This adds the domain to my Cloudflare account and points Porkbun's name servers to Cloudflare.
7. Check it: `python3 apps/os/frontend/tools/domain.py zone-status <name>`. It says "active" when Cloudflare sees the change. That usually takes under an hour, at most a day. While it is "pending", go on with Step 5 and Step 6. Check again between steps.
8. If I have a main domain, the OS address is the new domain itself: `<name>`.
   If I had no main domain, the new domain is now my main domain, and its records are on Cloudflare. The OS address is `app.<name>`, and the form is at `onboarding.<name>` (Step 6).

**If I said "a subdomain"**:
1. Ask me: **"app or os?"** (app.youragency.com or os.youragency.com). The OS address is `<my answer>.<main domain>`.
2. If my main domain's records are on Porkbun, get the Porkbun keys above.

**If I said "no domain for now"**:
1. Nothing to buy and no keys to get. The OS and the form each get a free address from Cloudflare, like `https://agency-os.pages.dev`. Cloudflare adds a few letters when the name is already taken, so the exact address shows only when Step 5 and Step 6 run.
2. In Steps 5 to 11, do only the parts marked **No domain**. Leave out `--domain` in every command.
3. To add a domain later: open this tab again, start at Step 3, and choose 1 or 2 at Step 4. Every command is safe to run again. The OS and the form then move to the new addresses, and the sign-in address and the settings table follow.

Write the choice and the OS address in `DECISIONS.md` now (Step 10 adds the rest). With no domain, write "no domain for now"; Step 10 adds the pages.dev addresses.

## Step 5. Put the OS live

1. Run: `python3 apps/os/frontend/tools/deploy.py --domain <OS address>`
   It builds the OS, makes the Cloudflare Pages project, stores the Supabase values (the secret key as a Cloudflare secret, for the "Add team member" button), deploys, attaches the address, sets the OS address as the Supabase sign-in address, writes it in the settings table, and checks the live site. Show me the result of each of its 8 steps in a short list.
2. If step 5 of its output says the address is not on Cloudflare, add the record it prints:
   - main domain on Porkbun: `python3 apps/os/frontend/tools/domain.py record <OS address> <target> --dns porkbun`
   - main domain anywhere else: `python3 apps/os/frontend/tools/domain.py record <OS address> <target> --dns manual`. Show me the record. **STOP** until I say I added it.
   Then wait for it: `python3 apps/os/frontend/tools/domain.py wait <OS address> <target>`.
3. If I bought a new domain and it was still "pending" in step 1, wait until `zone-status` says "active", then run the deploy command in 1 again. It adds the record this time.
4. Finish with: `python3 apps/os/frontend/tools/deploy.py --verify-only --domain <OS address>`. Every check must say OK. When the address is active, this also saves it as the sign-in address and in the settings table. If a check fails, show me which one and stop.

**No domain:** run `python3 apps/os/frontend/tools/deploy.py`. Step 5 of its output says "no address given". The OS address is the `https://...pages.dev` address on its last line ("Live: ..."). Use that address everywhere this tab says `<OS address>`. Skip parts 2 and 3. Finish with `python3 apps/os/frontend/tools/deploy.py --verify-only`. Every check must say OK.

## Step 6. Put the onboarding form live

1. Run: `python3 apps/onboarding/tools/deploy.py --domain onboarding.<main domain>`. Show me the result of each of its 6 steps in a short list.
2. If it prints a record to add by hand (my main domain is not on Cloudflare), add it as in Step 5, part 2, with `onboarding.<main domain>` and the value it printed. Then `domain.py wait`.
3. When the record works, run the command in 1 again. It is safe to run twice, and this time it saves the form's own address in the settings table, so the OS "Copy form link" button uses it.
4. Finish with: `python3 apps/onboarding/tools/deploy.py --verify-only --domain onboarding.<main domain>`. Every check must say OK.

The form address is `onboarding.<main domain>`.

**No domain:** run `python3 apps/onboarding/tools/deploy.py`. Step 5 of its output says "no domain given". The form address is the `https://...pages.dev` address on the "Live: ..." line, without the `/form` at the end. It is already saved in the settings table, so "Copy form link" uses it. Skip parts 2 and 3. Finish with `python3 apps/onboarding/tools/deploy.py --verify-only`. Every check must say OK.

## Step 7. My own sign-in

Tab 1 put me on the team list as the Owner. Now I need a login with a password.

1. Ask me to run this in my own terminal, so the temporary password shows only on my screen:
   `python3 apps/os/frontend/tools/deploy.py --owner-login --domain <OS address>`
   (In Claude Code I can type it after a `!` at the prompt.) If I cannot, run it yourself and tell me to copy the password from the output. Never repeat it.
   **No domain:** the same command without `--domain <OS address>`. It reads the OS address from the settings table.
2. It prints a temporary password once. It is not saved anywhere.
3. Ask me to open the OS address, sign in with my email and that password, and choose my own password (at least 10 characters). The OS asks for it before it shows anything. **STOP** until I say I am in.
4. If I lose the password later: `python3 apps/os/frontend/tools/deploy.py --owner-login --reset --email <my email> --domain <OS address>` (no domain: without `--domain <OS address>`). (The Supabase dashboard's "Send password recovery" sends a sign-in link by email. This OS uses passwords only, so do not use that.)

## Step 8. Add the team

1. Ask me who is on my team: name, email, and access for each person. **Owner** and **Admin** can add people and change anyone's details. **Member** can change only their own name, job title, phone and Slack user ID.
2. I add each person myself, in the OS: Team → **Add team member**. The OS makes their login and shows me a message with the OS address, their email and a temporary password, once, with a Copy button. I send it to them. At their first sign-in, they choose their own password. (After tab 3, the same message also goes to them in Slack.)
3. Someone lost their password: their page in Team → **Resend access**. Someone leaves: untick **Can sign in** on their page.
4. **STOP** until I say I added everyone. Then show me the list: `python3 apps/os/backend/db.py query "select full_name, email, access, can_sign_in from public.team order by full_name"`.

## Step 9. Check it together

1. Ask me to open the OS and look at: My Work (the first screen: what waits on me), the Dashboard, the Tasks screen (one tab per board: **Tasks, Campaigns**), and Clients. The example rows from tab 1 must show. On Tasks, the Assignee filter starts on **Me**; I pick **Everyone** to see every example card.
2. Ask me to open an example client, press **Copy form link**, and open the link in a private browser window. The onboarding form must show, with the client's company name.
3. Show me the settings row: `python3 apps/os/backend/db.py query "select os_url, onboarding_url from public.settings"`. Both must be the live addresses (`https://...`), with no `pages.dev`.
   **No domain:** both must be the `https://...pages.dev` addresses from Step 5 and Step 6.

If anything does not show, **STOP** and tell me what I saw and what I should have seen.

## Step 10. Write DECISIONS.md

Under a heading with today's date, add:
- a new domain, a subdomain or no domain for now, and the OS address;
- the onboarding form address;
- where my main domain's records are kept (Cloudflare, Porkbun or another company);
- the two Cloudflare Pages project names (the OS: `agency-os` unless `OS_PROJECT` is set; the form: `onboarding-form` unless `ONBOARDING_PROJECT` is set);
- who is on the team, with their access (no emails or passwords).

## Step 11. Update CLAUDE.md and AGENTS.md

Add a short "OS" part to `CLAUDE.md`, then make `AGENTS.md` the same text, word for word:

- The screens are in `apps/os/frontend/`. The boards, stages and fields are in `apps/os/frontend/src/agency.config.ts`. Colours are in `apps/os/frontend/src/theme.css` only.
- After a change to a stage list, run `python3 tests/config_matches_db.py`. It must say PASS.
- Put the OS live again after any change: `python3 apps/os/frontend/tools/deploy.py --domain <OS address>`. The form: `python3 apps/onboarding/tools/deploy.py --domain <form address>`. (Write the addresses without `https://`.)
  **No domain:** write these two commands instead: `python3 apps/os/frontend/tools/deploy.py` and `python3 apps/onboarding/tools/deploy.py`, and add: "No domain yet. Do not add `--domain`. To add one, do tab 2 again from Step 3."
- `apps/os/frontend/src/ui/` holds the screen parts every screen uses. Change them with care: a change shows on every screen.

Under "Built so far", add one line: "OS: live at <OS address>, onboarding form at <form address>, set up on <date>."

Both files must stay under 150 lines. Check with `python3 tests/agents_md_check.py`.

## Step 12. Read back the check list

Read this list back to me. Put ✓ or ✗ in front of each line, from what you saw in this chat. Do not tick anything you did not see.

- Cloudflare keys work ("Cloudflare: OK").
- The OS is live at its address, and every check of `deploy.py --verify-only` says OK.
- The Supabase sign-in address is the OS address ("read back OK").
- The onboarding form is live at its address (`onboarding.<main domain>`, or its pages.dev address with no domain), and every check says OK.
- `settings.os_url` and `settings.onboarding_url` are the live addresses.
- I signed in and chose my own password.
- Every team member is added (list their names).
- An example client's form link opens the form.
- `DECISIONS.md`, `CLAUDE.md` and `AGENTS.md` are updated, and `agents_md_check.py` passes.

If any line is ✗, tell me what is left to do. If all are ✓, commit everything (never `.env`) with the message "OS set up", and tell me the next tab to open: **Tab 3, automations.**
