"""Check the AI connector is online and locked, from the repo root. Reads .env; never prints a key.

    python3 apps/os/automations/mcp_check.py

It needs OS_AUTOMATIONS_URL in .env (tab 3). It uses no real link, so no one's access is
shown or used. Three checks, each PASS or FAIL:
  1. the connector answers at <OS_AUTOMATIONS_URL>/mcp/ with its five tools (a made-up token in the
     "Authorization: Bearer" header, the form that keeps tokens out of Modal's request log);
  2. that made-up token sees no actions and is told to ask for a link;
  3. a call to /mcp/token without the shared secret is turned away.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from shared.supabase_client import load_dotenv  # noqa: E402

TOOLS = {"list_actions", "describe_action", "run_read_action", "run_write_action", "get_run_status"}


def post(url: str, body: Dict[str, Any], headers: Dict[str, str]) -> Tuple[int, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:200]


def rpc(link: str, method: str, params: Dict[str, Any]) -> Tuple[int, Any]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer not-a-real-link",
    }
    return post(link, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers)


def main() -> int:
    import os

    load_dotenv(str(REPO / ".env"))
    base = (os.environ.get("OS_AUTOMATIONS_URL") or "").rstrip("/")
    if not base:
        print("FAIL: OS_AUTOMATIONS_URL is empty in .env. Do tab 3 Step 7 first.")
        return 1
    link = base + "/mcp/"
    bad = 0
    init = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "mcp_check", "version": "1"}}
    status, out = rpc(link, "initialize", init)
    status, out = rpc(link, "tools/list", {})
    names = {t["name"] for t in ((out or {}).get("result") or {}).get("tools", [])} if isinstance(out, dict) else set()
    if status == 200 and names == TOOLS:
        print("PASS: the connector answers with its five tools.")
    else:
        bad += 1
        print(
            "FAIL: the connector did not answer as expected ({0}). Deploy again: "
            "python3 -m modal deploy apps/os/automations/app.py".format(status)
        )
    status, out = rpc(link, "tools/call", {"name": "list_actions", "arguments": {}})
    answer = (((out or {}).get("result") or {}).get("structuredContent") or {}) if isinstance(out, dict) else {}
    if status == 200 and answer.get("actions") == [] and "does not work" in str(answer.get("message")):
        print("PASS: a made-up link sees no actions.")
    else:
        bad += 1
        print("FAIL: a made-up link was not refused ({0}). Stop and tell the person.".format(status))
    status, _ = post(base + "/mcp/token", {"team_id": "x", "action": "issue"}, {"Content-Type": "application/json"})
    if status == 401:
        print("PASS: making a link without the shared secret is turned away.")
    else:
        bad += 1
        print("FAIL: /mcp/token answered {0} without the shared secret. Stop and tell the person.".format(status))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
