"""The OS's automations: one Modal app on the agency's own Modal account.

    Deploy:   modal deploy apps/os/automations/app.py      (from the repo root)
    Secret:   agency-os  (SLACK_BOT_TOKEN, SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_PUBLISHABLE_KEY,
                          OS_SHARED_SECRET, SLACK_ICON_URL, MCP_TOKEN_PEPPER)
    Address:  printed by the deploy, ends in "-web.modal.run". It goes in .env as
              OS_AUTOMATIONS_URL and in the database vault (connect_db.py).

What calls what:

    POST /stage-change    the database, after every stage log row (a card added or moved)
    POST /new-client      the database, after a client is added (one post in new-tasks;
                          the OS never makes or posts in a client channel)
    POST /form-submitted  the form app's server, after a form is submitted:
                          {"onboarding_form_id": "...", "client_id": "..."}
    POST /team-invite     the OS, after "Add team member" or "Resend access"
    POST /ping            connect_db.py, to prove the database can reach this app
    POST /slack/actions   Slack, when someone presses a button (only says "got it")
    POST /mcp/token       the OS's "Connect your AI" and "Revoke" buttons (an Owner or Admin):
                          {"team_id": "...", "action": "issue" | "revoke"}, with the caller's
                          sign-in in the Authorization header. Answers {"server", "key", "url"} or {"revoked"}.
    /mcp/                 the AI connector (mcp_server.py), with "Authorization: Bearer <key>"
    /mcp/s/<key>/         the same, for claude.ai, which takes only an address (Modal logs it)
    POST /summary-now     a button (or any timer) that sends the daily summary now, whatever the hour
    every hour            the daily summary (posts only at the hour in the settings table), unless
                          schedule.json says "off" (Modal's free plan: 5 scheduled jobs per account)

Every call except /slack/actions and the AI connector must carry the header
X-OS-Secret = OS_SHARED_SECRET. The connector checks each person's own key instead.
A call without it is turned away. The database calls return at once; the work runs in
the background, so a slow Slack never holds up a card move.
"""

import sys
from pathlib import Path

import modal

app = modal.App("agency-os-automations")

# The code is Python 3.9 syntax throughout; Modal runs it on 3.11. The folder of this
# file goes to /app, and the repo's shared/ folder to /app/shared. (Inside Modal this
# file sits at /root/app.py, where the local folders are not read.)
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2] if len(HERE.parents) > 2 else HERE
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi[standard]==0.115.12", "fastmcp==3.4.0", "tzdata==2025.2")
    .add_local_dir(str(HERE), remote_path="/app", ignore=["tests", "__pycache__", "*.pyc"])
    .add_local_dir(str(REPO / "shared"), remote_path="/app/shared", ignore=["__pycache__", "*.pyc", "tests"])
)
# The second brain goes in the app too, so the AI connector can read it (brain.* actions).
# Change a note, then deploy again so people's AIs read the new version. inbox/ and raw/
# (whole transcripts, word for word) stay out: every Member's AI can read what is shipped.
# (The repo always has second-brain/; before tab 4 it holds only the "not built yet" INDEX.)
image = image.add_local_dir(
    str(REPO / "second-brain"),
    remote_path="/app/second-brain",
    ignore=["inbox", "inbox/**", "raw", "raw/**", "check.py", "PROMPT.md", "**/__pycache__", "**/.keep"],
)

# The team's skills go in the app too: the AI connector serves them (skills.list, skills.read) and
# skills that run on Modal run here. Deploy again after a skill changes. (Before any skill exists the
# repo may have no skills/ folder: then there is nothing to ship.)
if not modal.is_local() or (REPO / "skills").is_dir():
    image = image.add_local_dir(
        str(REPO / "skills"),
        remote_path="/app/skills",
        ignore=["**/__pycache__", "*.pyc", "**/tests", "**/tests/**", "**/.env*", "**/node_modules"],
    )

SECRETS = [modal.Secret.from_name("agency-os")]


def summary_schedule() -> "modal.Cron | None":
    """schedule.json: "hourly" (the default) or "off". Read from the same file here and inside Modal
    (/app is this folder), so the deploy and the running app agree."""
    import json

    for folder in (HERE, Path("/app")):
        f = folder / "schedule.json"
        if f.is_file():
            choice = str(json.loads(f.read_text()).get("daily_summary", "hourly")).strip().lower()
            if choice not in ("hourly", "off"):
                raise ValueError('schedule.json: daily_summary must be "hourly" or "off"')
            return None if choice == "off" else modal.Cron("0 * * * *")
    return modal.Cron("0 * * * *")
seen = modal.Dict.from_name("agency-os-once", create_if_missing=True)


def _setup():
    """Put /app on the path and build the three things every job needs."""
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from common import Config, Slack
    from shared.supabase_client import Supabase

    return Supabase(), Slack(), Config.load()


# --------------------------------------------------------------------------- background jobs


@app.function(image=image, secrets=SECRETS, timeout=120, retries=0)
def stage_change(row: dict):
    db, slack, config = _setup()
    from alerts import handle_stage_change

    return handle_stage_change(db, slack, config, seen, row)


@app.function(image=image, secrets=SECRETS, timeout=180, retries=0)
def new_client(client_id: str):
    db, slack, config = _setup()
    from new_client import handle_new_client

    return handle_new_client(db, slack, config, seen, client_id)


@app.function(image=image, secrets=SECRETS, timeout=120, retries=0)
def form_submitted(form_id: str):
    db, slack, config = _setup()
    from alerts import handle_form_submitted

    return handle_form_submitted(db, slack, config, seen, form_id)


@app.function(image=image, secrets=SECRETS, timeout=600, retries=0, schedule=summary_schedule())
def daily_summary():
    """Runs every hour (unless schedule.json says "off"). Posts only at the summary hour on a weekday."""
    db, slack, config = _setup()
    from daily_summary import run_daily_summary

    return run_daily_summary(db, slack, config, seen, scheduled=True)


@app.function(image=image, secrets=SECRETS, timeout=600, retries=0)
def summary_now():
    """Post the daily summary now, whatever the hour: modal run apps/os/automations/app.py::summary_now"""
    db, slack, config = _setup()
    from daily_summary import run_daily_summary

    result = run_daily_summary(db, slack, config, seen, scheduled=False)
    print(result)
    return result


@app.function(image=image, secrets=SECRETS, timeout=900, retries=0)
def run_skill(name: str, args: str = "{}"):
    """Run one skill from skills/ on Modal. Every skill uses this one function (no new function,
    no new schedule): modal run apps/os/automations/app.py::run_skill --name <skill> --args '{}'
    The web address POST /skill/<name> starts it too."""
    import json

    db, slack, config = _setup()
    from skills_runner import run_skill as start

    result = start(name, json.loads(args or "{}") if isinstance(args, str) else args, db, slack, config, seen)
    print(json.dumps(result, default=str)[:4000])
    return result


# --------------------------------------------------------------------------- web


@app.function(image=image, secrets=SECRETS, timeout=60)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def web():
    import hmac
    import json
    import os

    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool

    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from mcp_server import Connector, build_mcp_app, mount_connector, public_base, signed_in_email

    made: dict = {}

    def connector() -> Connector:
        # One per container, made on the first call, so its 60-second memory of who owns
        # which link is shared by every call that container serves.
        if "c" not in made:
            made["c"] = Connector.from_env()
        return made["c"]

    mcp_app = build_mcp_app(connector)
    # The connector's app only works inside its own lifespan, so the outer app runs it.
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=mcp_app.lifespan)
    expected = os.environ.get("OS_SHARED_SECRET", "")

    def allowed(request: Request) -> bool:
        got = request.headers.get("x-os-secret", "")
        return bool(expected) and hmac.compare_digest(got.encode(), expected.encode())

    def denied() -> JSONResponse:
        return JSONResponse({"ok": False, "error": "not allowed"}, status_code=401)

    @api.post("/stage-change")
    async def on_stage_change(request: Request):
        if not allowed(request):
            return denied()
        row = await request.json()
        await stage_change.spawn.aio(row)
        return {"ok": True}

    @api.post("/new-client")
    async def on_new_client(request: Request):
        if not allowed(request):
            return denied()
        body = await request.json()
        await new_client.spawn.aio(str(body.get("id", "")))
        return {"ok": True}

    @api.post("/form-submitted")
    async def on_form_submitted(request: Request):
        if not allowed(request):
            return denied()
        body = await request.json()
        await form_submitted.spawn.aio(str(body.get("onboarding_form_id") or body.get("id") or ""))
        return {"ok": True}

    @api.post("/team-invite")
    async def on_team_invite(request: Request):
        if not allowed(request):
            return denied()
        body = await request.json()
        if not body.get("team_id") or not body.get("temp_password"):
            return {"sent": False, "reason": "team_id and temp_password are both needed"}
        try:
            db, slack, config = _setup()
        except Exception:  # noqa: BLE001 - a missing key is an answer, not a crash
            return {"sent": False, "reason": "The automations are missing a key. Check the agency-os secret on Modal."}
        from team_invite import handle_team_invite

        return await run_in_threadpool(handle_team_invite, db, slack, config, seen, body)

    @api.post("/summary-now")
    async def on_summary_now(request: Request):
        # The third choice when the free plan's 5 scheduled jobs are used: a button sends it.
        if not allowed(request):
            return denied()
        await summary_now.spawn.aio()
        return {"ok": True, "started": True}

    @api.post("/skill/{name}")
    async def on_skill(name: str, request: Request):
        # Starts one skill on Modal. The JSON body is the skill's input. The answer comes at once;
        # the skill posts its own result in Slack (or once to pipeline-errors when it fails).
        if not allowed(request):
            return denied()
        from skills_runner import check

        problem = check(name)
        if problem:
            return JSONResponse({"ok": False, "error": problem}, status_code=404 if "No skill" in problem else 400)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - an empty body means no input
            body = {}
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "The body must be a JSON object (the skill's input)."}, status_code=400)
        await run_skill.spawn.aio(name, json.dumps(body))
        return {"ok": True, "started": True, "skill": name}

    @api.post("/ping")
    async def on_ping(request: Request):
        if not allowed(request):
            return denied()
        return {"ok": True, "pong": True}

    @api.post("/mcp/token")
    async def on_mcp_token(request: Request):
        if not allowed(request):
            return JSONResponse({"error": "This call is not allowed."}, status_code=401)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        email = await run_in_threadpool(
            signed_in_email,
            os.environ.get("SUPABASE_URL", ""),
            os.environ.get("SUPABASE_SECRET_KEY", ""),
            request.headers.get("authorization", ""),
        )
        try:
            status, out = await run_in_threadpool(
                connector().token_request,
                body if isinstance(body, dict) else {},
                email,
                public_base(str(request.base_url)),
            )
        except Exception:  # noqa: BLE001 - one plain sentence for the person, the rest in the log
            import traceback

            traceback.print_exc()
            status, out = 500, {"error": "The automations app could not make the link. Try again in a minute."}
        return JSONResponse(out, status_code=status)

    @api.post("/slack/actions")
    async def on_slack_action():
        # The "Open the card" buttons are links. Slack still tells the app about the
        # press; answering 200 stops Slack from showing a warning next to the button.
        return {"ok": True}

    mount_connector(api, mcp_app)
    return api
