"""Which Modal app holds each scheduled job, from the repo root. Reads only; changes nothing.

    python3 apps/os/automations/schedules.py

Modal's free plan allows 5 scheduled jobs in the whole account (every app together). This
lists each deployed app, its scheduled jobs and their timing, and the total out of 5, with
two Modal commands: `modal app list --json` (the apps) and `modal app info <app> --json`
(each app's functions, with their schedule). Needs Modal 1.6 or newer for `app info`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Callable, Dict, List

FREE_LIMIT = 5
OURS = "agency-os-automations"


def run_modal(args: List[str]) -> Any:
    out = subprocess.run(
        [sys.executable, "-m", "modal"] + args + ["--json"], capture_output=True, text=True, timeout=120
    )
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[-400:] or "modal {0} failed".format(" ".join(args)))
    return json.loads(out.stdout or "null")


def timing(schedule: Dict[str, Any]) -> str:
    """{"cron": {"cron_string": "0 * * * *", "timezone": "UTC"}} -> "cron 0 * * * * (UTC)". Pure."""
    if "cron" in schedule:
        c = schedule["cron"]
        return "cron {0} ({1})".format(c.get("cron_string", "?"), c.get("timezone") or "UTC")
    if "period" in schedule:
        return "every " + ", ".join("{0} {1}".format(v, k) for k, v in schedule["period"].items())
    return json.dumps(schedule)


def scheduled_jobs(apps: List[Dict[str, Any]], info: Callable[[str], Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{app, app_id, jobs: [(function, timing)]}] for every deployed app. Pure apart from `info`."""
    out = []
    for app in apps:
        if (app.get("state") or "").lower() != "deployed":
            continue
        functions = (info(app["app_id"]) or {}).get("functions") or {}
        jobs = [
            (name, timing(f["summary"]["schedule"]))
            for name, f in sorted(functions.items())
            if (f.get("summary") or {}).get("schedule")
        ]
        out.append({"app": app.get("description") or app["app_id"], "app_id": app["app_id"], "jobs": jobs})
    return out


def report(rows: List[Dict[str, Any]]) -> str:
    total = sum(len(r["jobs"]) for r in rows)
    lines = []
    for r in sorted(rows, key=lambda r: (-len(r["jobs"]), r["app"])):
        mark = "  (this OS)" if r["app"] == OURS else ""
        lines.append("{0}: {1} scheduled job{2}{3}".format(r["app"], len(r["jobs"]), "" if len(r["jobs"]) == 1 else "s", mark))
        for name, when in r["jobs"]:
            lines.append("    {0}  {1}".format(name, when))
    lines.append("")
    lines.append("Total: {0} of the {1} scheduled jobs the free plan allows.".format(total, FREE_LIMIT))
    ours = next((r for r in rows if r["app"] == OURS), None)
    need = 0 if ours and ours["jobs"] else 1
    if total + need > FREE_LIMIT:
        lines.append(
            "This OS needs 1 for the daily summary, and there is no room. Pick one of the three choices in "
            "tab 3 Step 7.6."
        )
    return "\n".join(lines)


def main() -> int:
    try:
        apps = run_modal(["app", "list"])
        rows = scheduled_jobs(apps or [], lambda app_id: run_modal(["app", "info", app_id]))
    except Exception as e:  # noqa: BLE001
        print("FAIL: {0}".format(e))
        print("Check that Modal is installed and you are logged in (tab 3 Step 7). 'app info' needs Modal 1.6 or newer.")
        return 1
    print(report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
