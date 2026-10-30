"""The connector token never reaches a log line, an error text or the audit table.

Modal writes every request's address in its own log, outside this code. So the token goes in the
"Authorization: Bearer" header to /mcp/, and nothing this app prints may hold it either.

The HTTP part needs fastmcp and fastapi (they are in the Modal image). On a laptop without
them it is skipped; the rest runs everywhere.
"""

import contextlib
import io
import json
import logging

import pytest
from test_mcp import TOKENS, make

from mcp_server import link_token

TOKEN = TOKENS["t-owner"]


def test_the_token_comes_from_the_header_first_never_the_query():
    assert link_token("Bearer abc", {"token": "xyz"}) == "abc"
    assert link_token("bearer  abc ", {}) == "abc"
    assert link_token("", {"token": "xyz"}) == "xyz"
    assert link_token("Basic abc", {}) is None and link_token("Bearer ", {}) is None
    assert link_token("", {}) is None


@contextlib.contextmanager
def every_log_line():
    """Everything the app prints or logs, at every level. The test client's own request log
    (logger "httpx") is the caller's side, not the app's, so it is left out."""
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.addFilter(lambda r: not r.name.startswith(("httpx", "httpcore")))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            yield out
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def test_no_log_line_error_or_audit_row_holds_the_token():
    pytest.importorskip("fastmcp")
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from mcp_server import build_mcp_app, mount_connector

    db, conn = make()
    # One action that fails inside, so its traceback is printed too.
    conn.registry.entries["boards"] = dict(conn.registry.entries["boards"], handler=lambda ctx: 1 / 0)
    mcp_app = build_mcp_app(lambda: conn)
    api = FastAPI(lifespan=mcp_app.lifespan)
    mount_connector(api, mcp_app)
    accept = {"Accept": "application/json, text/event-stream"}
    bearer = dict(accept, Authorization="Bearer " + TOKEN)

    def call(path, headers, method, params=None, n=1):
        return c.post(path, headers=headers, json={"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}})

    def tool(path, headers, name, params=None, n=2):
        return call(path, headers, "tools/call", {"name": "run_read_action", "arguments": {"name": name, "params": params or {}}}, n)  # fmt: skip

    bodies = []
    with every_log_line() as log, TestClient(api) as c:
        init = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
        for path, headers in (("/mcp/", bearer), ("/mcp/s/{0}/".format(TOKEN), accept)):
            bodies.append(call(path, headers, "initialize", init))
            bodies.append(tool(path, headers, "my_queue"))
            bodies.append(tool(path, headers, "boards"))  # fails inside: traceback printed
            bodies.append(tool(path, headers, "cards.get", {"board": "tasks", "id": None}))
            bodies.append(call(path, headers, "no/such/method"))
            bodies.append(c.post(path, headers=headers, content=b"{not json"))
        bodies.append(c.post("/mcp/s/{0}".format(TOKEN), headers=accept, json={}))  # no slash
        bodies.append(tool("/mcp/", dict(accept, Authorization="Bearer " + TOKEN + "x"), "my_queue"))  # wrong token

    mine = json.loads(bodies[1].text)["result"]["structuredContent"]
    assert mine["ok"] is True, mine  # the header link works
    assert "my_queue" == db.tables["mcp_audit"][0]["action"] and db.tables["mcp_audit"][0]["team_id"] == "t-owner"
    text = log.getvalue()
    assert "ZeroDivisionError" in text  # the capture works: the failing action's traceback is in it
    assert TOKEN not in text
    for r in bodies:
        if r.status_code != 307:  # a redirect's Location is the caller's own address
            assert TOKEN not in r.text, r.text[:300]
    assert TOKEN not in json.dumps(db.tables["mcp_audit"])


def test_the_log_reader_hides_every_link():
    from logs import mask

    line = 'POST /mcp/s/{0}/ -> 200 OK  Authorization: Bearer {0}, "bearer {0}"'.format(TOKEN)
    assert TOKEN not in mask(line) and mask(line).count("***") == 3
    assert mask("POST /mcp/ -> 200 OK") == "POST /mcp/ -> 200 OK"
    assert mask("GET /mcp/s/{0}?x=1".format(TOKEN)) == "GET /mcp/s/***?x=1"


def test_the_tabs_never_send_anyone_to_the_raw_log():
    """Tab 3's troubleshooting and tab 5 read Modal's log only through logs.py."""
    from fakes import AUTOMATIONS

    docs = AUTOMATIONS.parents[2] / "docs"
    for tab in sorted(docs.glob("*.md")):
        text = tab.read_text()
        assert "python3 -m modal app logs" not in text, tab.name
    assert "python3 apps/os/automations/logs.py" in (docs / "3-automations.md").read_text()
    tab5 = (docs / "5-mcp.md").read_text()
    assert "python3 apps/os/automations/logs.py" in tab5 and "never paste log lines" in tab5


def test_tab_5_sends_the_key_in_a_header_and_warns_about_the_claude_ai_link():
    """Claude Code, Codex and Hermes send the key in a header; only
    Claude on the web uses the /mcp/s/ link, with one plain warning. Each line was tried
    against a local copy of the connector (Claude Code, Hermes) or Codex's own header code."""
    from fakes import AUTOMATIONS

    tab5 = (AUTOMATIONS.parents[2] / "docs" / "5-mcp.md").read_text()
    step4 = tab5.split("## Step 4.")[1].split("## Step 5.")[0]
    lines = {line.split(":**")[0].strip(" -*"): line for line in step4.splitlines() if ":**" in line}
    assert set(lines) == {"Claude Code", "Codex", "Hermes", "Claude on the web (claude.ai)"}
    for tool in ("Claude Code", "Codex", "Hermes"):
        assert '"<server>"' in lines[tool] and "Bearer <key>" in lines[tool] and "/mcp/s/" not in lines[tool], tool
    assert '--header "Authorization: Bearer <key>"' in lines["Claude Code"]
    assert 'http_headers = { "Authorization" = "Bearer <key>" }' in lines["Codex"]
    assert "headers:" in lines["Hermes"] and 'Authorization: "Bearer <key>"' in lines["Hermes"]
    assert lines["Claude on the web (claude.ai)"].endswith(
        "use Claude Code, Codex or Hermes instead."
    )
    assert "Modal's log keeps this link. Use it only if nobody else can open your Modal account." in tab5
    assert "<my link>" not in tab5
