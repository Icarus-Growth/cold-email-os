# The second brain set-up prompt

The same text as tab 4 (`docs/4-second-brain.md`). To run it, tell your AI: "Follow `second-brain/PROMPT.md`".

---

You are building my second brain: a folder of plain notes that you, the AI, read before you do any work for my agency, so you do not start from nothing each time. It lives in `second-brain/` in this repo. The notes are plain markdown files with `[[links]]` between them. There is no database, no app and no special editor.

Ask me 4 questions, on one question page (Step 1). Then build it to the end without stopping again, except where a step says **STOP**. After each step, tell me what you did in one or two short sentences, then go on. If you cannot run commands, do each check by hand and say so.

## The rules (keep these for the whole job, and every time you add a note later)

1. **Plain files.** Each note is one markdown file. A link is `[[File_Name]]`: the file name without `.md`. Every file name in `second-brain/` is used once only, so each link points to one file.
2. **One idea per note.** A note is one thought: a way of working, a rule we learned, a checklist, a prompt that works. It is not a long document. Split a long document into notes.
3. **The links are the map, not the folders.** Every note links to its area map, and its area map lists it. Link a note to other notes only when the other note really helps. Never add a link only to make the map look full.
4. **Keep what lasts.** Keep how we do things and why. A one-time event ("the call on Tuesday") is not a note, unless it taught us a rule.
5. **File a note by what it is**, not by the job that uses it. File it once. If you are not sure where it goes, put it in `unsorted/`.
6. **Use my words.** You are a librarian, not a writer. Keep my words and put the title, links and tags around them. Fix only spelling.
7. **The source first.** Before you write a note, save the whole source in `raw/`: the whole transcript, the whole document or the whole brain dump, word for word. The note says where it came from and links to its raw file. A note with no raw file is only an idea: mark it `Raw: none (an idea, not proven)`. Never use an idea note as the reason for how the OS or a process works. Get the source first.
8. **What does not go in.** The brain holds what works across clients. Anything about one client goes in `clients/<client-name>/`, not here. Anything about one lead or one person stays only in its raw file. No keys, passwords or private details about people. The notes are saved with this repo, so the repo must stay private. Never fill a file with made-up text to make it look done.
9. **At most two folder levels** inside `second-brain/`.

## Step 1. Ask me (one question page)

Read `docs/process.md`, `CLAUDE.md` and `DECISIONS.md` first if they are there, so you know my agency. Pick 5 to 10 areas my thinking falls into, from what you read (for example sales, offers, delivery, copy and creative, client results, team and hiring, tools and automations). Then open the second brain question page, with your areas as the choices:

```
python3 tools/question-page/make.py second-brain --choices "areas=<area 1>;<area 2>;<area 3>"
```

It asks me 4 things: whose thinking this is (mine alone or the whole team's), which areas, where my notes are now (I put them, or an export of them, in `second-brain/inbox/`), and how strict to be with my old notes (about 20%, 40% or 60% become notes; a clear rule about how we work is always kept). If no browser opens, give me the file path it prints. Wait until I paste the answers back. Never ask for a password.

Then show me the areas as a short list, each with one line on what goes in it. **STOP** and wait for one "yes" (or my changes). After that, do not stop again until Step 7.

## Step 2. Make the folders

```
second-brain/
  INDEX.md            the map of maps (Step 3)
  PROMPT.md           this prompt (already here)
  check.py            the check (already here)
  inbox/              things to sort later
  raw/                every source, word for word
  unsorted/           notes you are not sure where to file
  <area>/             one folder per area, with its map: <area>/<area>_map.md
```

Use lower case and dashes for folder names (for example `copy-and-creative`). Make every folder now, even if it stays empty for a while: put a file named `.keep` in an empty folder so it is saved. Leave `PROMPT.md` and `check.py` as they are.

## Step 3. Write INDEX.md (the map of maps)

Replace `second-brain/INDEX.md` with:

- **The goal:** the goal line from `CLAUDE.md`, "About the business", in my words (if it says `<not answered yet>`, write that).
- **Areas:** one line per area: `[[<area>_map]]`, what goes in it, and how many notes it has.
- **Sources:** a table with one row per raw file: the raw file, where it came from, the date it is from, and the notes made from it.
- **Notes with problems:** the problems `check.py` finds (none, at the end of this job).
- **How to add a note:** "Follow `skills/global/add-note/SKILL.md`."

Write it now with 0 notes in each area. Fill in the counts and the Sources table in Step 6, from what `check.py` prints, not from memory. From then on, every time you add a note, update INDEX.md in the same go.

Make each area map now (`<area>/<area>_map.md`): a title, one line on what the area is for, its notes as `[[links]]` under short bold headings (none yet), and a last line: `Back to [[INDEX]]`.

## Step 4. The rule for every AI that works in this repo

Add this part at the end of `OS_BUILD_RULES.md`, under "Parts added by the set-up tabs", unless it is already there. Rules never go in `CLAUDE.md`:

```
## Second brain

**Second brain first.** Before any work that needs judgment (sales, offers, copy, process, planning, a client plan), read `second-brain/INDEX.md`, open the area map, read the notes it links to, and name the notes you used. If no note covers it, say "the second brain has nothing on <subject>" and offer to add a note. Never name a note you did not open. When we decide something or learn something that will last, add a note with `skills/global/add-note/SKILL.md`. If the AI connector (tab 5) is set up, put the automations app live again after any change to the notes, so everyone's AI reads them: `python3 -m modal deploy apps/os/automations/app.py`.
```

Check with `python3 tests/agents_md_check.py`. It must say PASS.

## Step 5. The add-note skill

Make `skills/global/add-note/SKILL.md` with this text, so any AI (Claude Code, Codex or another agent) can add notes the same way later. Then run `python3 tools/sync_skills.py` so Claude Code sees it:

```
---
name: add-note
description: Adds a note to the second brain. Use when I say "add this to the brain", "remember this", "make a note of this", or after we decide or learn something that will last.
area: global
agency: all
needs: []
runs_on: local
---

# Add a note to the second brain

1. Save the whole source in second-brain/raw/ first, word for word: the transcript, document, message
   or my own words. Name it <date the source is from>_<short-name>.md (for example
   2026-03-04_pricing-call.md). The date is the date of the source, not today. If the source has no
   date, use today's date and say so at the top. At the top, write where it came from and who said it. If there is no source, the note is an idea
   (step 3).
2. Read second-brain/INDEX.md and the area map. Look for a note that already says this. If one does,
   add to that note instead of making a new one.
3. Write the note in the right area folder (not sure: unsorted/). The format:

   # A Title That Says The Point (a claim, not a topic, in Title Case)
   > One line that sums it up.

   One to four short paragraphs, in the source's own words where you can. One idea only. No headings.
   Never add words the source does not support.

   Source: where it came from, who, and the date
   Raw: [[the raw file name, without .md]]   (or: none (an idea, not proven))
   Related: [[<area>_map]], and [[other notes]] only if they really help
   Tags: 5 to 10 tags, lower case with dashes

   The file name is the title with underscores: A_Title_That_Says_The_Point.md
4. Add the note to its area map, and add a line for the raw file in the Sources table in INDEX.md.
   Update the note count.
5. Run python3 second-brain/check.py (if you can run commands). It must say PASS. If you cannot run
   commands, check by hand that every [[link]] in the note points to a file that exists.
6. Tell me the note's title and which notes it links to.
```

## Step 6. Fill it from my notes

1. Sort what is in `inbox/`. For each item: save it whole in `raw/` (Step 5, point 1), then delete it from `inbox/` (the whole copy is in `raw/`). Then decide what to keep, at the strictness from question 4. Keep the parts that say how we work and why. A clear rule about how we work is always kept.
2. Make the notes with the add-note skill, area by area. Each note links to its map and to the notes it really relates to.
3. If `inbox/` is empty, use my answers from Step 1 as the first raw file (`raw/<today>_setup-answers.md`) and make the first notes from them.
4. Leave an item in `inbox/` only if you need me to explain it. List these for me at the end.
5. Run `python3 second-brain/check.py`. Fix every problem it shows and run it again until it says PASS. Then put its note counts in INDEX.md. (An area with no notes yet is fine.)

## Step 7. Prove it works, then tell me we are done

1. Show me one worked example: one raw file, three notes made from it, their area map, and the line in INDEX.md for that raw file.
2. Prove the source rule: follow the add-note skill for a test idea that has no source. The note must say `Raw: none (an idea, not proven)`, not an invented source. Then change its Raw line to `Raw: made up`, run `check.py`, and show me that it says FAIL. Then delete the test note, take it out of its area map, and run `check.py` again: PASS.
3. Prove the rule in Step 4: ask me to open a new chat in this folder and ask "How do we handle a client who is unhappy?". The AI there must open `second-brain/INDEX.md` first, then name the notes it used or say the second brain has nothing on it. Ask me what it did.
4. In `CLAUDE.md`, under "Built so far", add: "Second brain: `second-brain/` with <number> areas and <number> notes, set up on <date>." If that list says "Nothing yet. Start with `docs/1-database.md`." and tab 1 is not done, keep "Start with `docs/1-database.md`." `CLAUDE.md` stays at 50 lines or fewer. Run `python3 tests/agents_md_check.py`: it must say PASS.
5. Add to `DECISIONS.md`, one line each (date, question, answer, why): the areas, the strictness, whose thinking it is, what was left out on purpose (for example a note about one lead), and anything left in `inbox/`.
6. Give me a short list: the areas, how many notes and raw files there are, what is left in `inbox/`, and that `check.py` says PASS. Then commit everything (never `.env`) with the message "Second brain set up".
7. If the AI connector (tab 5) is already set up, put the automations app live again so everyone's AI reads the new notes: `python3 -m modal deploy apps/os/automations/app.py`. Do this after every change to the notes. If it fails with "reached limit of 5 scheduled functions", stop and tell me: the free Modal plan allows 5 scheduled jobs, so I stop one or upgrade (tab 3 Step 7.6). If tab 5 is not done yet, skip this: tab 5 does it.
8. Tell me the next tab to open: Tab 5, The AI connector.
