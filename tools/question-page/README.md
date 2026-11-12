# Question pages

A question page puts a set of questions on one page in the browser, instead of a long list in the chat.
Each question has choices or a text box, a "Skip / leave for now" button and a comment box.
The person presses **Copy answers** and pastes the text back into the chat.
Nothing is sent anywhere. The answers stay in that browser until they are copied.

## Use it (for the AI)

```
python3 tools/question-page/make.py business          # the business set-up
python3 tools/question-page/make.py second-brain      # the second brain set-up (tab 4)
python3 tools/question-page/make.py who-are-you       # one person: name, role, access, how to work with them
python3 tools/question-page/make.py second-brain --choices "areas=Sales;Offers;Delivery"   # your own choices for one question
python3 tools/question-page/make.py my-questions.json # any set you write yourself
```

It writes the page to `tools/question-page/out/` (git ignores that folder) and opens it.
If no browser opens, give the person the file path it prints. Then wait for the pasted answers.

When the answers come back:
- Write each fact where its line says `[goes to: ...]`. Facts go into `CLAUDE.md` "About the business" or
  "The team and roles": replace the line, never add a second one. `CLAUDE.md` stays at 50 lines or fewer.
- A choice goes into `DECISIONS.md`, one line each: date, question, answer, why.
- "SKIPPED: leave for now" and "NOT ANSWERED": do not guess. Write `<not answered yet>` and ask again later.

## Write your own set

Ask only what you cannot work out from the repo. A set is a JSON file:

```json
{
  "id": "slack-alerts",
  "title": "Slack alerts",
  "intro": "One line: what these answers decide.",
  "questions": [
    { "id": "channel", "text": "Which channel gets the new-task alerts?", "dest": "decision",
      "help": "One line of help under the question (optional).",
      "parts": [
        { "k": "pick", "type": "single", "opts": ["new-tasks", "team-updates"] },
        { "k": "other", "type": "text", "label": "Another channel" }
      ] }
  ]
}
```

- `parts` are the boxes to answer in: `single` (pick one), `multi` (pick any), `text` (one line), `textarea` (a few lines).
  `single` and `multi` need `opts`. Each part has its own `k`.
- `dest` says where the answer goes: `about` (CLAUDE.md, About the business), `team` (CLAUDE.md, The team and roles),
  `decision` (DECISIONS.md), `brain` (second-brain/INDEX.md and DECISIONS.md), or `chat` (only for this job).
- Never ask for a key, token or password on a page. Those go in `.env`.

Check the tool: `python3 tools/question-page/test_make.py`.
