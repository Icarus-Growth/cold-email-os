"""Every form of the connector's address answers 200, with or without the last "/" (plan item 1),
and the key works in each header a tool may send (plan item 2).

Claude on the web drops the last "/" of a link. Before the fix, /mcp/s/<key> (no "/") fell through
to /mcp and answered 404, and Claude then said the connector needs a sign-in.

The HTTP part needs fastmcp and fastapi (they are in the Modal image); without them it is skipped.
"""

import json

import pytest
from test_mcp import TOKENS, make

from mcp_server import link_token, with_slash

KEY = TOKENS["t-owner"]
ACCEPT = {"Accept": "application/json, text/event-stream"}
INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}


def test_with_slash_adds_the_last_slash_to_the_two_connector_addresses_only():
    assert with_slash("/mcp") == "/mcp/"
    assert with_slash("/mcp/s/abc") == "/mcp/s/abc/"
    for same in ("/mcp/", "/mcp/s/abc/", "/mcp/token", "/mcp/s/", "/mcpx", "/stage-change", "/", ""):
        assert with_slash(same) == same, same


def test_the_key_comes_from_each_header():
    assert link_token("", {}, "abc") == "abc"
    assert link_token("", {}, "  abc ") == "abc"
    assert link_token("Bearer one", {}, "two") == "one"  # Authorization wins when both are sent
    assert link_token("", {"token": "path"}, "head") == "head"  # a header wins over the address
    assert link_token("", {}, "") is None


def client():
    pytest.importorskip("fastmcp")
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from mcp_server import build_mcp_app, mount_connector

    db, conn = make()
    mcp_app = build_mcp_app(lambda: conn)
    api = FastAPI(lifespan=mcp_app.lifespan)

    @api.post("/mcp/token")
    async def token_route():  # the real app has this route; it must not be caught by the connector
        return {"route": "token"}

    mount_connector(api, mcp_app)
    return db, TestClient(api, follow_redirects=False)  # a redirect is not an answer


def rpc(c, path, headers, method, params=None, n=1):
    return c.post(path, headers=headers, json={"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}})


def queue(c, path, headers):
    r = rpc(c, path, headers, "tools/call", {"name": "run_read_action", "arguments": {"name": "my_queue"}}, 2)
    return r, json.loads(r.text)["result"]["structuredContent"] if r.status_code == 200 else None


@pytest.mark.parametrize(
    "path, headers",
    [
        ("/mcp/", {"Authorization": "Bearer " + KEY}),
        ("/mcp", {"Authorization": "Bearer " + KEY}),
        ("/mcp/", {"x-auth-token": KEY}),
        ("/mcp", {"X-Auth-Token": KEY}),
        ("/mcp/s/{0}/".format(KEY), {}),
        ("/mcp/s/{0}".format(KEY), {}),
    ],
)
def test_every_address_form_and_header_answers_200_and_knows_the_person(path, headers):
    db, c = client()
    with c:
        init = rpc(c, path, dict(ACCEPT, **headers), "initialize", INIT)
        assert init.status_code == 200, (path, init.status_code, init.text[:200])
        assert json.loads(init.text)["result"]["serverInfo"]["name"] == "Agency OS"
        r, out = queue(c, path, dict(ACCEPT, **headers))
        assert r.status_code == 200 and out["ok"] is True, (path, out)
    assert [a["team_id"] for a in db.tables["mcp_audit"]] == ["t-owner"]


def test_a_wrong_key_in_any_header_sees_nothing():
    db, c = client()
    with c:
        for headers in ({"x-auth-token": KEY + "x"}, {"Authorization": "Bearer " + KEY + "x"}):
            r, out = queue(c, "/mcp", dict(ACCEPT, **headers))
            assert r.status_code == 200 and out["ok"] is False and "does not work" in out["error"]


def test_the_slash_fix_leaves_the_other_routes_alone():
    db, c = client()
    with c:
        assert c.post("/mcp/token").json() == {"route": "token"}
        assert c.post("/nothing-here").status_code == 404
