"""Connect the database to the Modal app, from the repo root. Reads .env; never prints a key.

    python3 apps/os/automations/connect_db.py secret
        Make OS_SHARED_SECRET and MCP_TOKEN_PEPPER in .env, each only if it is empty. The
        values are never shown. (MCP_TOKEN_PEPPER scrambles the AI connector keys, tab 5.
        A new one kills every link, so it is never made again once set.)
    python3 apps/os/automations/connect_db.py connect
        Store OS_AUTOMATIONS_URL and OS_SHARED_SECRET in the database vault, so the
        database calls the Modal app when a card moves or a client is added.
    python3 apps/os/automations/connect_db.py test
        Prove it: a call with no secret is turned away, a call with it is let in, and the
        database itself can reach the Modal app.
    python3 apps/os/automations/connect_db.py off
        Switch every database call off (the Modal app stays deployed).

It uses the database helper (apps/os/backend/db.py) and its personal access token.
"""

from __future__ import annotations

import importlib.util
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ENV = REPO / ".env"


def db_helper():
    spec = importlib.util.spec_from_file_location("db_helper", str(REPO / "apps/os/backend/db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def read_env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def need(env: Dict[str, str], *names: str) -> None:
    missing = [n for n in names if not env.get(n)]
    if missing:
        sys.exit("Missing in .env: {0}. Fill them in, then run this again.".format(", ".join(missing)))


def cmd_secret() -> None:
    env = read_env()
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    for name in ("OS_SHARED_SECRET", "MCP_TOKEN_PEPPER"):
        if env.get(name):
            print("{0} is already set. Nothing changed.".format(name))
            continue
        value = secrets.token_urlsafe(32)
        for i, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == name:
                lines[i] = name + "=" + value
                break
        else:
            lines.append(name + "=" + value)
        print("Made {0} in .env (not shown).".format(name))
    ENV.write_text("\n".join(lines) + "\n")


def cmd_connect() -> None:
    env = read_env()
    need(env, "OS_AUTOMATIONS_URL", "OS_SHARED_SECRET")
    db = db_helper()
    rows = db.query(
        "select public.set_automation_hook({0}, {1}) as result".format(
            db.sql_text(env["OS_AUTOMATIONS_URL"].rstrip("/")), db.sql_text(env["OS_SHARED_SECRET"])
        )
    )
    print(rows[0]["result"] if rows else "No answer from the database.")


def cmd_off() -> None:
    db = db_helper()
    rows = db.query("select public.set_automation_hook('', '') as result")
    print(rows[0]["result"] if rows else "No answer from the database.")


def ping(url: str, secret: str) -> int:
    req = urllib.request.Request(
        url.rstrip("/") + "/ping",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json", "X-OS-Secret": secret, "User-Agent": "agency-os-connect"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def cmd_test() -> int:
    env = read_env()
    need(env, "OS_AUTOMATIONS_URL", "OS_SHARED_SECRET")
    url = env["OS_AUTOMATIONS_URL"]
    results: List[str] = []
    ok = True

    no_secret = ping(url, "wrong")
    results.append(
        "{0}: a call without the secret is turned away ({1})".format("PASS" if no_secret == 401 else "FAIL", no_secret)
    )
    ok = ok and no_secret == 401
    with_secret = ping(url, env["OS_SHARED_SECRET"])
    results.append(
        "{0}: a call with the secret is let in ({1})".format("PASS" if with_secret == 200 else "FAIL", with_secret)
    )
    ok = ok and with_secret == 200

    db = db_helper()
    rows = db.query("select public.call_automation('/ping', '{}'::jsonb) as id")
    req_id = rows[0]["id"] if rows else None
    status = None
    if req_id is None:
        results.append("FAIL: the database did not call (run connect first)")
        ok = False
    else:
        for _ in range(20):
            time.sleep(2)
            got = db.query("select status_code from net._http_response where id = {0}".format(int(req_id)))
            if got:
                status = got[0]["status_code"]
                break
        results.append(
            "{0}: the database reaches the Modal app ({1})".format(
                "PASS" if status == 200 else "FAIL", status or "no answer in 40 seconds"
            )
        )
        ok = ok and status == 200
    print("\n".join(results))
    return 0 if ok else 1


def main(argv: List[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "secret":
        cmd_secret()
    elif cmd == "connect":
        cmd_connect()
    elif cmd == "off":
        cmd_off()
    elif cmd == "test":
        return cmd_test()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
