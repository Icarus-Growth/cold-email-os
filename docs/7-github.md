# Tab 7: GitHub, a private home for your OS (Cold Email agency OS)

**Who this tab is for.** The owner, and any developer the owner lets work on the code. Nobody else on the team needs GitHub: they use the OS in the browser.

**How to use this tab.** Do it after tabs 1 to 5. Open this repo's folder in your AI tool and paste everything below the line. Never paste a key, token or password into the chat.

---

You are giving my agency's OS a safe home on GitHub. The repo holds my agency's process, my second brain and how the OS is built, so it must be **private**. You check that it is private, put my work there, show me how to invite a developer, and make sure the key file (`.env`) is never sent.

Work through the steps in order. After each step, tell me in one or two short sentences what you did and what I should see. Stop and wait for me only where a step says **STOP**. If a command fails, show me the error in plain words and stop.

## The rules (keep these for the whole job)

1. **`.env` never goes to GitHub.** It holds every key. It stays on the computers of the people who run the OS.
2. **The repo is private.** If you find it is public, stop and tell me before you send anything.
3. **Never ask for my GitHub password.** I sign in to GitHub myself, in the browser or with GitHub's own sign-in tool.
4. **Only the owner invites people.** Invite only the people I name.

## Step 1. Check the key file is kept out

1. Run `git check-ignore .env`. It must print `.env`. That means git leaves the key file out.
   If it prints nothing, add a line `.env` to `.gitignore`, then run it again.
2. Run `git ls-files | grep -E '(^|/)\.env$'`. It must print nothing. If it prints a file name, the key file was sent before. **STOP** and tell me: every key in it must be made new (each key's page in tab 1, 2, 3 and 5 says where), and then the file is taken out with `git rm --cached .env`.
3. Run `python3 tests/no_keys_committed.py`. It must say PASS.

What I should see: three short results, all clean.

## Step 2. Find or make the private repo

1. Run `git remote -v`.
   - It shows an `origin` address on github.com: tab 1 made my private copy. Ask me to open that address in the browser. Next to the repo name I must see the word **Private**. **STOP** until I say what I see. If it says **Public**: ask me to open Settings, scroll to "Danger Zone", press "Change visibility" and pick "Private". Then go on.
   - It shows nothing: ask me to open github.com/new, type a name (for example `<agency name>-os`), pick **Private**, leave every box below unticked, and press "Create repository". Ask me for the address it shows (it ends in `.git`). Run `git remote add origin <the address>`.
2. If `git remote -v` shows an address that is not mine (for example the public template), run `git remote rename origin template`, then do the "shows nothing" way above.

What I should see: my repo on GitHub, with the word **Private** next to its name.

## Step 3. Send my work to GitHub

1. Run `git status`. Read the list to me in one line. `.env` must not be in it.
2. Save the work: `git add -A`, then `git commit -m "OS set up"` (skip it if git says there is nothing to commit).
3. Send it: `git push -u origin HEAD`. If it asks me to sign in, I sign in to GitHub in the browser window it opens. If it fails with "permission denied" or "authentication", ask me to install GitHub's sign-in tool (cli.github.com), run `gh auth login` in my own terminal (in Claude Code: type `! gh auth login`), and then push again.

What I should see: on the repo page in the browser, my folders (`apps`, `docs`, `skills`, `second-brain` and the others), and the files `CLAUDE.md` and `DECISIONS.md`. There is no `.env` file.

## Step 4. Invite a developer

Do this only if I name a developer. Ask me for their GitHub user name (not their password).

1. Ask me to open the repo on GitHub: Settings → Collaborators → **Add people**. I type their GitHub user name and press "Add to repository".
2. They get an email from GitHub and press **Accept invitation**.
3. On the Collaborators page I see their name with "Pending invite" until they accept, then their name alone.

What I should see: the developer's name on the Collaborators page.

## Step 5. What the developer does on their own computer

Give me these steps to send to the developer, as they are:

1. Get the code: `git clone <the repo address>` and open the folder in your AI tool.
2. Get the keys from the owner by a password manager, never by chat or email. Put them in a file named `.env` at the top of the folder. Never commit it.
3. Run `python3 tools/sync_skills.py`, so Claude Code finds the team's skills.
4. Read `CLAUDE.md`, `OS_BUILD_RULES.md` and `DATABASE_RULES.md` before you change anything.
5. Work on a branch, not on `main`: `git switch -c <short name of the change>`. Push the branch and ask the owner to look at it before it goes into `main`.

## Step 6. Write it down

1. Add one line to `DECISIONS.md` for each (date, question, answer, why): the repo address, that it is private, and who has access.
2. In `CLAUDE.md`, under "Built so far", add: "GitHub: private repo at <address>, set up on <date>." `CLAUDE.md` stays at 50 lines or fewer. Run `python3 tests/agents_md_check.py`: it must say PASS.
3. Save and send: `git add -A`, `git commit -m "GitHub set up"`, `git push`.

## Step 7. Tell me we are done

Give me a short list: the repo address, that it says **Private**, that `.env` is not on GitHub, and who is invited.
From now on, after each change: `git add -A`, `git commit -m "<what changed>"`, `git push`. Check `git status` first: `.env` must never be in the list.
