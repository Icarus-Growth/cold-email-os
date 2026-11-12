"""Modal's free plan: 5 scheduled jobs in the whole account (plan item 4). The OS keeps one, the
guide shows which app holds each job, and the third choice runs the summary with no schedule."""

import json
import re

from fakes import AUTOMATIONS

from schedules import report, scheduled_jobs, timing

# The shape `modal app list --json` and `modal app info <id> --json` print (read from a real
# account with Modal 1.6.3; names changed).
APPS = [
    {"app_id": "ap-1", "description": "other-bot", "state": "deployed", "tasks": "0"},
    {"app_id": "ap-2", "description": "agency-os-automations", "state": "deployed", "tasks": "1"},
    {"app_id": "ap-3", "description": "old-thing", "state": "stopped", "tasks": "0"},
]
INFO = {
    "ap-1": {"functions": {
        "a": {"id": "fu-a", "summary": {"schedule": {"cron": {"cron_string": "0 19 * * *", "timezone": "UTC"}}}},
        "b": {"id": "fu-b", "summary": {"schedule": {"period": {"hours": 6}}}},
        "c": {"id": "fu-c", "summary": {}},
        "d": {"id": "fu-d", "summary": {"schedule": {"cron": {"cron_string": "0 6 * * 1-5"}}}},
        "e": {"id": "fu-e", "summary": {"schedule": {"cron": {"cron_string": "0 */6 * * *"}}}},
        "f": {"id": "fu-f", "summary": {"schedule": {"cron": {"cron_string": "0 */12 * * *"}}}},
    }},
    "ap-2": {"functions": {"web": {"id": "fu-w", "summary": {"web_function": True}}}},
    "ap-3": {"functions": {"x": {"summary": {"schedule": {"cron": {"cron_string": "* * * * *"}}}}}},
}  # fmt: skip


def test_it_lists_each_deployed_apps_scheduled_jobs_and_the_total():
    rows = scheduled_jobs(APPS, lambda app_id: INFO[app_id])
    assert [r["app"] for r in rows] == ["other-bot", "agency-os-automations"]  # a stopped app holds none
    assert [n for n, _ in rows[0]["jobs"]] == ["a", "b", "d", "e", "f"]
    assert timing(INFO["ap-1"]["functions"]["a"]["summary"]["schedule"]) == "cron 0 19 * * * (UTC)"
    assert timing({"period": {"hours": 6}}) == "every 6 hours"
    text = report(rows)
    assert "other-bot: 5 scheduled jobs" in text and "agency-os-automations: 0 scheduled jobs  (this OS)" in text
    assert "Total: 5 of the 5" in text and "no room" in text and "tab 3 Step 7.6" in text
    assert "no room" not in report(rows[1:])


def test_the_app_has_one_schedule_and_it_follows_schedule_json():
    app = (AUTOMATIONS / "app.py").read_text()
    assert len(re.findall(r"schedule=", app)) == 1 and "schedule=summary_schedule()" in app
    assert app.count("modal.Cron(") == 2  # the same hourly job, in the one function that picks it
    assert '@api.post("/summary-now")' in app and "summary_now.spawn.aio()" in app
    setting = json.loads((AUTOMATIONS / "schedule.json").read_text())
    assert setting["daily_summary"] == "hourly"  # the default: the summary runs on its own


def test_tab_3_gives_the_list_commands_and_three_choices_and_never_says_pay():
    tab3 = (AUTOMATIONS.parents[2] / "docs" / "3-automations.md").read_text()
    step = tab3.split("**If the deploy fails")[1].split("\n7. ")[0]
    assert "python3 apps/os/automations/schedules.py" in step
    assert "python3 -m modal app list" in step and "python3 -m modal app info" in step
    assert all("**Choice {0}".format(n) in step for n in (1, 2, 3)) and "**Choice 4" not in step
    assert '"daily_summary": "off"' in step and "summary_now" in step and "/summary-now" in step
    for word in ("upgrade", "pay ", "paid", "billing", "credit card"):
        assert word not in tab3.lower(), word
