"""Tab 3 set-up, version 2: the channel names are all checked before any is made (plan item 5), and
the logo check waits for a fresh deploy (plan item 7)."""

import json

import pytest
from fakes import AUTOMATIONS  # noqa: F401 - puts the automations folder on the path

import logo
import slack_setup
from shared.slack_notify import SlackError
from slack_setup import HIDDEN_NOTE, plan_channels

WANTED = {
    "new-tasks": "new-tasks", "task-updates": "task-updates", "amendments": "amendments", "review": "review",
    "approved": "approved", "daily-summary": "daily-summary", "pipeline-errors": "pipeline-errors",
    "needs-a-person": "needs-a-person",
}  # fmt: skip


def ch(name, cid, member=True, private=False, archived=False):
    return {"name": name, "id": cid, "is_member": member, "is_private": private, "is_archived": archived}


def test_the_plan_sorts_every_name_before_anything_is_made():
    seen = [
        ch("review", "C1"),
        ch("approved", "C2", member=False),
        ch("amendments", "C3", member=False, private=True),
        ch("pipeline-errors", "C4", archived=True),
    ]
    plan = plan_channels(WANTED, seen)
    assert [i["name"] for i in plan["use"]] == ["review"]
    assert [i["name"] for i in plan["join"]] == ["approved"]
    assert [i["name"] for i in plan["blocked"]] == ["amendments", "pipeline-errors"]
    assert "private channel the bot is not in" in plan["blocked"][0]["why"]
    assert "archived" in plan["blocked"][1]["why"]
    assert {i["name"] for i in plan["make"]} == {"new-tasks", "task-updates", "daily-summary", "needs-a-person"}
    dup = plan_channels({"review": "alerts", "approved": "alerts"}, [])
    assert [i["key"] for i in dup["make"]] == ["review"] and "same name as 'review'" in dup["blocked"][0]["why"]


@pytest.fixture
def slack(tmp_path, monkeypatch):
    """channels.json in a temp folder, and a fake Slack that records every call."""
    data = {"channels": {k: {"name": v, "id": ""} for k, v in WANTED.items()}}
    path = tmp_path / "channels.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(slack_setup, "CHANNELS_FILE", path)
    monkeypatch.setattr(slack_setup, "REPO", tmp_path)
    state = {"seen": [], "hidden": set(), "calls": []}

    def call(method, body):
        state["calls"].append((method, dict(body)))
        if method == "conversations.list":
            assert body["exclude_archived"] is False  # archived channels hold names too
            return {"channels": state["seen"]}
        if method == "conversations.create":
            if body["name"] in state["hidden"]:
                raise SlackError("name_taken", "name_taken")
            return {"channel": {"id": "N-" + body["name"], "name": body["name"]}}
        return {"ok": True}

    monkeypatch.setattr(slack_setup, "call", call)
    state["path"] = path
    return state


def made(state):
    return [b["name"] for m, b in state["calls"] if m == "conversations.create"]


def test_a_visible_clash_stops_before_anything_is_made_and_lists_every_name(slack, capsys):
    slack["seen"] = [ch("amendments", "C3", member=False, private=True), ch("review", "C4", archived=True)]
    assert slack_setup.cmd_make_channels(False) == 1
    out = capsys.readouterr().out
    assert made(slack) == [] and not [m for m, _ in slack["calls"] if m == "conversations.join"]
    assert "TAKEN #amendments" in out and "TAKEN #review" in out and HIDDEN_NOTE in out
    assert "Checked all 8 names before making any" in out


def test_hidden_clashes_are_all_listed_in_one_run(slack, capsys):
    slack["seen"] = [ch("approved", "C2", member=False)]
    slack["hidden"] = {"review", "needs-a-person"}  # private channels the bot cannot see
    assert slack_setup.cmd_make_channels(False) == 1
    out = capsys.readouterr().out
    assert "TAKEN #review" in out and "TAKEN #needs-a-person" in out and "private channel" in out
    assert len(made(slack)) == 7  # it tried every name the bot could not see, not only up to the first clash
    saved = json.loads(slack["path"].read_text())["channels"]
    assert saved["approved"]["id"] == "C2" and saved["new-tasks"]["id"] == "N-new-tasks" and saved["review"]["id"] == ""


def test_a_clean_run_makes_joins_and_saves(slack, capsys):
    slack["seen"] = [ch("review", "C1"), ch("approved", "C2", member=False)]
    assert slack_setup.cmd_make_channels(False) == 0
    saved = json.loads(slack["path"].read_text())["channels"]
    assert all(v["id"] for v in saved.values())
    assert ("conversations.join", {"channel": "C2"}) in slack["calls"]


def test_the_logo_check_waits_30_seconds_and_tries_3_more_times(capsys):
    looks, waits = [], []

    def look(url):
        looks.append(url)
        return (len(looks) == 3, "image/png" if len(looks) == 3 else "it answered 404")

    assert logo.cmd_check("https://os.example.com/slack-logo.png", look=look, wait=waits.append) == 0
    assert len(looks) == 3 and waits == [30, 30]
    looks.clear(), waits.clear()
    assert logo.cmd_check("https://x/slack-logo.png", look=lambda u: (looks.append(u) or False, "it answered 404"), wait=waits.append) == 1
    assert len(looks) == 4 and waits == [30, 30, 30]
    out = capsys.readouterr().out
    assert "FAIL" in out and "after 4 tries over about 90 seconds" in out


def test_the_logo_check_counts_an_unreachable_address_as_not_yet():
    ok, seen = logo.check_once("http://127.0.0.1:9/slack-logo.png")  # nothing listens on port 9
    assert ok is False and "could not be reached" in seen
