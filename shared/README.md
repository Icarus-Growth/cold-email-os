# shared/

Code used by two or more skills or apps lives here, so it is written once.

- One file per service or job (for example `slack_notify.py`, a Google Workspace client, an OpenRouter
  client, an image or video model client, a memory client).
- Before you write a new helper anywhere in the repo, look here first.
- Keys come from `.env`. Never write a key into a file here.
