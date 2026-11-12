"""The AI connector (MCP): each person's AI works on their own cards in the OS.

It runs inside the automations' Modal app, in the same web address:

    <OS_AUTOMATIONS_URL>/mcp/               with "Authorization: Bearer <token>" or "x-auth-token: <token>"
                                            (kept out of logs)
    <OS_AUTOMATIONS_URL>/mcp/s/<token>/     the same, for tools that take only an address. Modal's
                                            request log keeps this address, token and all.
    Both answer with or without the last "/" (SlashFix).
    POST <OS_AUTOMATIONS_URL>/mcp/token     the OS's "Connect your AI" and "Revoke" buttons;
                                            "issue" answers {server, key, url} (see issued())

The AI sees five fixed tools, and every ability is an action in mcp_actions.py:

    list_actions(query="")          what this person may run
    describe_action(name)           one action's parameters, in full
    run_read_action(name, params)   an action that only reads
    run_write_action(name, params)  an action that changes something
    get_run_status(run_id)          long jobs (there are none yet; every action answers at once)

Who is calling
--------------
The link is the password. The token in it is never stored: the team row keeps only
HMAC-SHA256(MCP_TOKEN_PEPPER, token) in mcp_token_hash. Each call hashes the token and
finds the one team row with that hash, which must be Active and able to sign in. The
answer is kept for 60 seconds, so a revoked link stops within a minute. An unknown link
sees no actions and can run nothing.

The role checks are here, in code: an action's "roles" decide who sees it in
list_actions AND who may run it. The tool hints (read only, changes things) only describe.

Every call writes one mcp_audit row: who, which action, the parameters (long text cut
short), whether it worked, and the error. A failed audit write never fails the call.

Nothing here imports Modal or FastMCP until build_mcp_app() runs, so the tests run on
a laptop with a fake database.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import traceback
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from common import Config
from mcp_actions import ActionError, Context, Registry, load_spec

IDENTITY_TTL_SECONDS = 60
AUDIT_VALUE_MAX = 500
UUID_LEN = 36
NO_ACCESS = (
    "This connector key does not work: it was revoked or replaced, or its owner cannot sign in. "
    "Ask an Owner or Admin for a new key (Team, your page, Connect your AI)."
)
TEAM_IDENTITY = "id,full_name,email,access,status,can_sign_in"


ROLE_ORDER = ("Owner", "Admin", "Member")
NO_PUBLISHABLE = (
    "The database actions are not set up: SUPABASE_PUBLISHABLE_KEY is missing from the agency-os Modal "
    "secret. Tab 3 Step 7.5 stores it. Then deploy the automations again."
)
SESSION_SPARE_SECONDS = 300


class Sessions:
    """Each caller's own database sign-in, for db.read and db.write: the database's rules for
    their access level apply, never the server's key. One sign-in per person is kept until five
    minutes before it runs out (Supabase gives an hour), so a busy AI does not make a session per
    call. A change to someone's access works at once anyway: the rules read the team table."""

    def __init__(
        self,
        url: str,
        secret_key: str,
        publishable_key: str,
        clock: Callable[[], float] = time.time,
        sign_in: Optional[Callable[..., Dict[str, Any]]] = None,
        make_db: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.url, self.secret_key, self.publishable_key = url, secret_key, publishable_key
        self.clock = clock
        self._sign_in = sign_in
        self._make_db = make_db
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def db_for(self, me: Dict[str, Any]) -> Any:
        if not self.publishable_key:
            raise ActionError(NO_PUBLISHABLE)
        email = (me.get("email") or "").strip().lower()
        if not email:
            raise ActionError("Your team row has no email, so the database cannot tell who you are.")
        now = self.clock()
        hit = self._cache.get(email)
        if hit and now < hit[0]:
            return hit[1]
        from shared.supabase_client import Supabase, signed_in_as

        session = (self._sign_in or signed_in_as)(email, self.url, self.secret_key)
        db = (self._make_db or Supabase)(self.url, self.publishable_key, bearer=session["access_token"])
        life = int(session.get("expires_in") or 3600)
        self._cache[email] = (now + max(60, life - SESSION_SPARE_SECONDS), db)
        return db



def not_for_you(registry: Registry, name: str, role: Optional[str]) -> str:
    """Why a known caller may not use `name`: the action does not exist, or it is for other
    roles. Naming the roles lets the AI say "this is for Owners and Admins". Pure."""
    may = ", ".join(registry.visible_to(role))
    entry = registry.get(name)
    if entry is None:
        return "No action called '{0}'. You may run: {1}.".format(name, may)
    roles = " and ".join(r + "s" for r in ROLE_ORDER if r in entry["roles"])
    you = {"Owner": "an Owner", "Admin": "an Admin"}.get(role or "", "a {0}".format(role))
    return "Refused: '{0}' is for {1} only; you are {2}. You may run: {3}.".format(name, roles, you, may)


def token_hash(token: str, pepper: str) -> str:
    """The only form of a token that is ever stored."""
    if not pepper:
        raise RuntimeError("MCP_TOKEN_PEPPER is not set in the agency-os Modal secret")
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def shrink(value: Any) -> Any:
    """Parameters for the audit row: long text cut short, long lists cut at 20."""
    if isinstance(value, str) and len(value) > AUDIT_VALUE_MAX:
        return value[:AUDIT_VALUE_MAX] + "...[cut, {0} letters]".format(len(value))
    if isinstance(value, dict):
        return {k: shrink(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shrink(v) for v in value[:20]]
    return value


def coerce_params(params: Any) -> Dict[str, Any]:
    if params in (None, ""):
        return {}
    if isinstance(params, dict):
        return params
    if isinstance(params, str):
        try:
            loaded = json.loads(params)
        except ValueError:
            raise ActionError('params must be an object, for example {"board": "tasks"}.')
        if isinstance(loaded, dict):
            return loaded
    raise ActionError('params must be an object, for example {"board": "tasks"}.')


class Connector:
    """Everything the five tools and the token route do, with no web framework in it."""

    def __init__(
        self,
        db: Any,
        registry: Registry,
        config: Config,
        pepper: str,
        clock: Callable[[], float] = time.time,
        today: Any = None,
        sessions: Optional[Sessions] = None,
    ) -> None:
        self.db = db
        self.sessions = sessions
        self.registry = registry
        self.config = config
        self.pepper = pepper
        self.clock = clock
        self.today = today
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    @classmethod
    def from_env(cls) -> "Connector":
        from shared.supabase_client import Supabase

        sessions = Sessions(
            os.environ.get("SUPABASE_URL", "").rstrip("/"),
            os.environ.get("SUPABASE_SECRET_KEY", ""),
            os.environ.get("SUPABASE_PUBLISHABLE_KEY", ""),
        )
        return cls(
            Supabase(), Registry(load_spec()), Config.load(), os.environ.get("MCP_TOKEN_PEPPER", ""), sessions=sessions
        )

    # ------------------------------------------------------------------ identity

    def identity(self, token: Optional[str]) -> Dict[str, Any]:
        """{known, me, role, reason}. Never raises: a database fault is "unknown", never "allowed"."""
        token = (token or "").strip()
        if not token:
            return {"known": False, "me": None, "role": None, "reason": "no token in the link"}
        try:
            digest = token_hash(token, self.pepper)
        except RuntimeError as e:
            return {"known": False, "me": None, "role": None, "reason": str(e)}
        now = self.clock()
        cached = self._cache.get(digest)
        if cached and now - cached[0] < IDENTITY_TTL_SECONDS:
            return cached[1]
        try:
            rows = self.db.select("team", {"mcp_token_hash": "eq." + digest}, columns=TEAM_IDENTITY, limit=1)
        except Exception as e:  # noqa: BLE001
            return {"known": False, "me": None, "role": None, "reason": "could not read the team table: {0}".format(e)}
        me = rows[0] if rows else None
        if not me:
            who = {
                "known": False,
                "me": None,
                "role": None,
                "reason": "no team row has this link (revoked or replaced)",
            }
        elif me.get("status") != "Active" or not me.get("can_sign_in"):
            who = {
                "known": False,
                "me": None,
                "role": None,
                "reason": "the link's owner is not Active or cannot sign in",
            }
        else:
            who = {"known": True, "me": me, "role": me.get("access"), "reason": ""}
            try:
                self.db.update("team", me["id"], {"mcp_last_seen_at": self._iso(now)})
            except Exception:  # noqa: BLE001 - last seen is a nicety, never a failure
                traceback.print_exc()
        self._cache[digest] = (now, who)
        return who

    def forget(self, team_id: str) -> None:
        """Drop a revoked person from this container's 60-second memory at once."""
        for digest, (_, who) in list(self._cache.items()):
            if (who.get("me") or {}).get("id") == team_id:
                del self._cache[digest]

    @staticmethod
    def _iso(epoch: float) -> str:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(epoch, timezone.utc).isoformat()

    # ------------------------------------------------------------------ audit

    def audit(self, who: Dict[str, Any], action: str, args: Any, ok: bool, error: Optional[str] = None) -> None:
        """One mcp_audit row. Never raises into a call."""
        try:
            self.db.insert(
                "mcp_audit",
                {
                    "team_id": (who.get("me") or {}).get("id"),
                    "action": action,
                    "args": shrink(args if isinstance(args, dict) else {"value": args}),
                    "ok": bool(ok),
                    "error": (str(error)[:1000] if error else None),
                },
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def revoked(self, caller: Dict[str, Any], target: Dict[str, Any], reason: str) -> None:
        """One "revoked" row in the connector log for every key that stops working: the Revoke
        button, or a new key that replaces an old one. The row is the key owner's (team_id), like
        every other row of theirs; "by" says who pressed the button."""
        self.audit(
            {"me": target},
            "revoked",
            {"team_id": target.get("id"), "name": target.get("full_name"), "by": caller.get("full_name"),
             "by_id": caller.get("id"), "reason": reason},
            True,
        )  # fmt: skip

    # ------------------------------------------------------------------ the five tools

    def list_actions(self, token: Optional[str], query: str = "") -> Dict[str, Any]:
        who = self.identity(token)
        names = self.registry.visible_to(who["role"]) if who["known"] else []
        needle = (query or "").strip().lower()
        if needle:
            names = [
                n for n in names if needle in n.lower() or needle in self.registry.entries[n]["description"].lower()
            ]
        out: Dict[str, Any] = {
            "actions": [
                {
                    "name": n,
                    "kind": self.registry.entries[n]["kind"],
                    "description": self.registry.entries[n]["description"],
                }
                for n in names
            ]
        }
        if who["known"]:
            out["you"] = {"name": who["me"].get("full_name"), "access": who["role"]}
            if not names:
                out["message"] = "No action matches '{0}'. Call list_actions with no query to see all.".format(query)
        else:
            out["message"] = NO_ACCESS
        self.audit(who, "list_actions", {"query": query}, who["known"], None if who["known"] else who["reason"])
        return out

    def describe_action(self, token: Optional[str], name: str) -> Dict[str, Any]:
        who = self.identity(token)
        name = (name or "").strip()
        visible = self.registry.visible_to(who["role"]) if who["known"] else []
        if name in visible:
            out = dict(self.registry.summarise(name), ok=True)
            error = None
        else:
            error = (
                NO_ACCESS
                if not who["known"]
                else not_for_you(self.registry, name, who["role"])
            )
            out = {"ok": False, "error": error}
        self.audit(who, "describe_action", {"name": name}, error is None, error if who["known"] else who["reason"])
        return out

    def run(self, kind: str, token: Optional[str], name: str, params: Any) -> Dict[str, Any]:
        """Both run tools. One path, so the checks cannot differ: known caller, the action
        exists for them, the right tool, the role, the parameters, then the action."""
        who = self.identity(token)
        name = (name or "").strip()
        args: Any = params

        def finish(ok: bool, payload: Dict[str, Any], error: Optional[str] = None) -> Dict[str, Any]:
            self.audit(who, name or "run_{0}_action".format(kind), args, ok, error)
            return payload

        try:
            args = coerce_params(params)
        except ActionError as e:
            return finish(False, {"ok": False, "error": str(e)}, str(e))
        if not who["known"]:
            return finish(False, {"ok": False, "error": NO_ACCESS}, who["reason"])
        role = who["role"]
        entry = self.registry.get(name)
        if entry is None or name not in self.registry.visible_to(role):
            msg = not_for_you(self.registry, name, role)
            return finish(False, {"ok": False, "error": msg}, msg)
        if entry["kind"] != kind:
            msg = "'{0}' {1}, so run it with {2}.".format(
                name,
                "changes things" if entry["kind"] == "write" else "only reads",
                "run_write_action" if entry["kind"] == "write" else "run_read_action",
            )
            return finish(False, {"ok": False, "error": msg}, msg)
        if not self.registry.allowed(name, role, kind):
            msg = "Refused: '{0}' is for {1}; you are {2}.".format(name, " and ".join(sorted(entry["roles"])), role)
            return finish(False, {"ok": False, "error": msg}, msg)
        try:
            args = self.registry.validate(name, args)
            me = who["me"]
            caller_db = (lambda: self.sessions.db_for(me)) if self.sessions else None
            ctx = Context(self.db, me, self.registry.spec, self.config, today=self.today, caller_db=caller_db)
            result = entry["handler"](ctx, **args)
        except ActionError as e:
            return finish(False, {"ok": False, "error": str(e)}, str(e))
        except Exception as e:  # noqa: BLE001 - the AI gets one plain line, the log gets the rest
            traceback.print_exc()
            msg = "The action failed: {0}".format(str(e)[:300])
            return finish(False, {"ok": False, "error": msg}, "{0}: {1}".format(type(e).__name__, e))
        return finish(True, {"ok": True, "action": name, "result": result})

    def run_status(self, token: Optional[str], run_id: str) -> Dict[str, Any]:
        who = self.identity(token)
        if not who["known"]:
            out: Dict[str, Any] = {"ok": False, "error": NO_ACCESS}
        else:
            out = {
                "ok": True,
                "run_id": run_id,
                "status": "not_applicable",
                "message": "There are no long jobs yet: every action gives its answer at once.",
            }
        self.audit(who, "get_run_status", {"run_id": run_id}, who["known"], None if who["known"] else who["reason"])
        return out

    # ------------------------------------------------------------------ the token route

    def token_request(
        self, body: Dict[str, Any], caller_email: Optional[str], base_url: str
    ) -> Tuple[int, Dict[str, Any]]:
        """POST /mcp/token {team_id, action: issue|revoke}, already past the shared secret.
        caller_email is the signed-in Supabase user's email (None when the sign-in is not
        valid). Returns (HTTP status, body)."""
        if not caller_email:
            return 401, {"error": "Your sign-in has run out. Sign in to the OS again, then try again."}
        rows = self.db.select("team", {"email": "eq." + caller_email.strip().lower()}, columns=TEAM_IDENTITY, limit=1)
        caller = rows[0] if rows else None
        if not caller or caller.get("status") != "Active" or not caller.get("can_sign_in"):
            return 403, {"error": "You are not on the team, so you cannot do this."}
        if caller.get("access") not in ("Owner", "Admin"):
            return 403, {"error": "Only an Owner or Admin can connect or revoke an AI."}
        who = {"me": caller}
        team_id = str(body.get("team_id") or "").strip()
        action = body.get("action")
        if len(team_id) != UUID_LEN or action not in ("issue", "revoke"):
            return 400, {"error": "Pick a person and an action first."}
        target = self.db.get("team", team_id, columns=TEAM_IDENTITY + ",mcp_token_hash")
        if not target:
            return 404, {"error": "That person is not on the team list."}
        if action == "revoke":
            self.db.update("team", team_id, {"mcp_token_hash": None})
            self.forget(team_id)
            self.revoked(caller, target, "Revoke button" if target.get("mcp_token_hash") else "Revoke button (no key)")
            return 200, {"revoked": True}
        if target.get("status") != "Active" or not target.get("can_sign_in"):
            return 400, {
                "error": "{0} cannot sign in, so they cannot connect an AI. Set them to Active and tick "
                '"Can sign in" first.'.format(target.get("full_name") or "This person")
            }
        if not self.pepper:
            return 500, {"error": "The AI connector is not set up: MCP_TOKEN_PEPPER is missing. Do tab 5 first."}
        token = secrets.token_urlsafe(32)
        self.db.update("team", team_id, {"mcp_token_hash": token_hash(token, self.pepper)})
        self.forget(team_id)
        if target.get("mcp_token_hash"):
            self.revoked(caller, target, "replaced by a new key")
        self.audit(who, "token.issue", {"team_id": team_id}, True)
        return 200, issued(base_url, token)


def issued(base_url: str, token: str) -> Dict[str, str]:
    """What "Connect your AI" shows, once. server + key: the address and the header
    ("Authorization: Bearer <key>") for Claude Code, Codex and Hermes, kept out of Modal's
    log. url: the address link for claude.ai, which takes only an address. Pure."""
    base = base_url.rstrip("/")
    return {"server": base + "/mcp/", "key": token, "url": "{0}/mcp/s/{1}/".format(base, token)}


def signed_in_email(supabase_url: str, api_key: str, bearer: str) -> Optional[str]:
    """The email of the signed-in Supabase user who owns this access token, or None."""
    token = (bearer or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token or not supabase_url or not api_key:
        return None
    req = urllib.request.Request(
        supabase_url.rstrip("/") + "/auth/v1/user", headers={"apikey": api_key, "Authorization": "Bearer " + token}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            user = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, ValueError):
        return None
    return (user.get("email") or "").lower() or None


def public_base(url: str) -> str:
    """The app's own address for the link: https, unless it runs on this computer."""
    url = url.rstrip("/")
    if url.startswith("http://") and not any(h in url for h in ("://localhost", "://127.0.0.1")):
        url = "https://" + url[len("http://") :]
    return url


# --------------------------------------------------------------------------- the web part


INSTRUCTIONS = (
    "The agency's operating system: its boards and cards, clients, team, calls, onboarding forms, report "
    "numbers and its second brain (the agency's own notes on how it works). You act as the person who owns "
    "this link, with their access.\n\n"
    "Call list_actions first.\n"
    "1. My work: for 'what should I do?' or 'what is most urgent for me?', run run_read_action('my_queue').\n"
    "2. The second brain first: before any work that needs judgment (sales, offers, copy, process, planning, "
    "a client plan), read it: brain.index, then brain.map for the area, then brain.read for the notes "
    "(brain.search finds a note by its words). Name the notes you used. If no note covers it, say "
    "'the second brain has nothing on <subject>'. Never name a note you did not open. If it is not set up, "
    "say so plainly.\n"
    "3. Changes go through run_write_action and work as in the app: a moved card writes the stage log and "
    "posts the same Slack alert. Nothing can be deleted here.\n"
    "Each read gives at most 100 rows; ask for 'next_page' when there are more. Give the card's link when "
    "you talk about a card."
)


def link_token(authorization: str, path_params: Dict[str, Any], auth_token: str = "") -> Optional[str]:
    """The person's key: from "Authorization: Bearer <key>", or from "x-auth-token: <key>" (for tools
    that let you add a header but not "Authorization"), or from an /mcp/s/<key>/ address. With a
    header the address is plain /mcp/, so the request log that Modal keeps never holds the key.
    Never from the query string: a query string is logged too. Pure."""
    scheme, _, value = (authorization or "").strip().partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    if (auth_token or "").strip():
        return auth_token.strip()
    found = path_params.get("token")
    return str(found) if found else None


#: The connector's addresses without their last "/": "/mcp" and "/mcp/s/<key>".
_NO_SLASH = re.compile(r"^/mcp(/s/[^/]+)?$")


def with_slash(path: str) -> str:
    """'/mcp' -> '/mcp/', '/mcp/s/<key>' -> '/mcp/s/<key>/'. Every other path is left as it is.
    Claude on the web drops the last "/" of a link, and the bare form used to answer 404. Pure."""
    return path + "/" if _NO_SLASH.match(path or "") else path


class SlashFix:
    """Lets the connector answer the same at /mcp and /mcp/, and at /mcp/s/<key> and /mcp/s/<key>/.
    It changes the path before routing, so there is no redirect: a redirect drops the body of a
    POST in some AI tools, and behind Modal it can point at http:// instead of https://."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            fixed = with_slash(scope.get("path", ""))
            if fixed != scope.get("path"):
                scope = dict(scope, path=fixed, raw_path=fixed.encode("latin-1"))
        await self.app(scope, receive, send)


def mount_connector(api: Any, mcp_app: Any) -> None:
    """Put the connector on the web app. The token goes in the "Authorization: Bearer" header to
    /mcp/, so it is never in the address Modal writes in its request log. /mcp/s/<token>/ is for
    tools that take only an address. The longer path goes first, or /mcp would take it. SlashFix
    makes both addresses work with or without their last "/"."""
    api.mount("/mcp/s/{token}", mcp_app)
    api.mount("/mcp", mcp_app)
    api.add_middleware(SlashFix)


def build_mcp_app(connector: Callable[[], Connector]):
    """The FastMCP app, put on the web app by mount_connector. `connector` makes the Connector once."""
    from anyio import to_thread
    from fastmcp import FastMCP
    from fastmcp.server.dependencies import get_http_request

    mcp = FastMCP(name="Agency OS", instructions=INSTRUCTIONS)

    def token() -> Optional[str]:
        try:
            request = get_http_request()
        except Exception:  # noqa: BLE001
            return None
        return link_token(
            request.headers.get("authorization", ""),
            getattr(request, "path_params", None) or {},
            request.headers.get("x-auth-token", ""),
        )

    async def call(fn: Callable[..., Dict[str, Any]], *args: Any) -> Dict[str, Any]:
        # The database calls block, so they run off the event loop.
        return await to_thread.run_sync(lambda: fn(*args))

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_actions(query: str = "") -> dict:
        """Every action you may run, with what it does. Call this first.

        For my own work, run my_queue. Before work that needs judgment, read the second brain
        (brain.index, brain.map, brain.read), name the notes you used, or say "the second brain
        has nothing on <subject>".

        Args:
            query: Optional words to filter the actions by name or description.
        """
        return await call(connector().list_actions, token(), query)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def describe_action(name: str) -> dict:
        """One action in full: who may run it, its parameters, and which tool runs it.

        Args:
            name: The action's name, for example 'my_queue' or 'cards.move'.
        """
        return await call(connector().describe_action, token(), name)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def run_read_action(name: str, params: Optional[dict] = None) -> dict:
        """Run an action that only reads, for example my_queue, cards.search, clients.get or brain.read.

        Read the second brain (brain.*) before work that needs judgment, and name the notes you used.

        Args:
            name: The action's name.
            params: Its parameters, as describe_action lists them.
        """
        return await call(connector().run, "read", token(), name, params)

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": False})
    async def run_write_action(name: str, params: Optional[dict] = None) -> dict:
        """Run an action that changes the OS, for example cards.move or cards.note. Nothing can be deleted.

        Args:
            name: The action's name.
            params: Its parameters, as describe_action lists them.
        """
        return await call(connector().run, "write", token(), name, params)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_run_status(run_id: str) -> dict:
        """The state of a long job. There are none yet: every action answers at once.

        Args:
            run_id: The id a long job gave.
        """
        return await call(connector().run_status, token(), run_id)

    # Plain JSON answers (no event stream): every AI client reads them, and so does mcp_check.py.
    return mcp.http_app(path="/", stateless_http=True, json_response=True)
