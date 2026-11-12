"""Each team member's morning list (plan Wave 2 item 7, contract "Daily pending tasks"): one Slack
direct message per person with open cards, inside the daily summary run (no new schedule)."""

from datetime import timedelta

from fakes import FakeSlack, config
from test_daily_summary import TUESDAY_8, summary_world

from daily_summary import TASKS_BOT, act_today, pending_by_person, run_daily_summary

CFG = config()


def dms(slack):
    return [p for p in slack.posts if p["channel"].startswith("dm-")]


def run(db, slack, seen=None, hours=0, scheduled=True):
    return run_daily_summary(db, slack, CFG, {} if seen is None else seen, scheduled=scheduled,
                             now_utc=TUESDAY_8 + timedelta(hours=hours))  # fmt: skip


def test_each_person_with_open_cards_gets_one_message_with_links():
    db, slack = summary_world(), FakeSlack()
    res = run(db, slack)
    assert res["posted"] and res["direct_messages"]["sent"] == 2
    got = {p["channel"]: p for p in dms(slack)}
    assert set(got) == {"dm-UMAKER", "dm-UANA"}  # the Owner has no open card: no message
    assert all(p["bot_name"] == TASKS_BOT and p["thread_ts"] is None for p in got.values())
    maker = got["dm-UMAKER"]["text"]
    assert "Hi Max. You have 3 open cards: 1 late, 0 due today, 0 waiting for your review." in maker
    assert "Stuck task" in maker and "no move for 5 days" in maker
    lines = [ln for ln in maker.splitlines() if ln.startswith("• ")]
    assert lines[0].startswith("• <https://os.example.com/") and "Late task" in lines[0] and "late 2 days" in lines[0]
    assert [ln.split("|")[1].split(">")[0] for ln in lines] == ["Late task", "Stuck task", "Fine task"]
    assert "Waiting card" not in maker  # it waits for Ana's review, so it is on Ana's list
    assert "Waiting card" in got["dm-UANA"]["text"] and "waiting for your review" in got["dm-UANA"]["text"]
    assert got["dm-UANA"]["blocks"][-1]["elements"][0]["text"]["text"] == "Open My Work"
    assert ("conversations.open", {"users": "UMAKER"}) in slack.calls


def test_nobody_gets_two_messages_on_one_day_and_none_off_the_hour():
    db, slack, seen = summary_world(), FakeSlack(), {}
    run(db, slack, seen)
    run(db, slack, seen, hours=2, scheduled=False)  # someone runs it by hand later the same day
    assert len(dms(slack)) == 2
    other = FakeSlack()
    assert run(db, other, {}, hours=1)["posted"] is False and dms(other) == []  # not the summary hour


def test_a_person_with_no_slack_id_is_found_by_email_or_named_once_in_pipeline_errors():
    db, slack = summary_world(), FakeSlack()
    for r in db.tables["team"]:
        if r["id"] in ("t-maker", "t-am"):
            r["slack_user_id"] = None
    slack.users_by_email = {"max@example.com": "UMAX2"}
    res = run(db, slack)
    assert [p["channel"] for p in dms(slack)] == ["dm-UMAX2"]
    assert next(r for r in db.tables["team"] if r["id"] == "t-maker")["slack_user_id"] == "UMAX2"  # saved
    assert res["direct_messages"]["not_sent"] == ["Ana Manager (no Slack account uses ana@example.com)"]
    errors = slack.in_channel("pipeline-errors")
    assert len(errors) == 1 and "Ana Manager" in errors[0]["text"]
    assert res["posted"] is True  # the summary still went out


def test_a_failing_message_never_stops_the_summary():
    db, slack = summary_world(), FakeSlack()
    slack.fail_channels = {"dm-UMAKER"}
    res = run(db, slack)
    assert res["posted"] and res["direct_messages"]["sent"] == 1 and len(slack.in_channel("daily-summary")) >= 1


def test_live_cards_are_never_late_or_stuck_but_stay_on_the_list():
    old = (TUESDAY_8 - timedelta(days=30)).isoformat()
    live = {"board": "tasks", "card_id": "live1", "card_name": "Running", "client_id": "c-1", "stage": "10 - In Progress",
            "assignee_id": "t-maker", "due_date": "2026-10-01", "stage_changed_at": old, "is_live": True}  # fmt: skip
    today = TUESDAY_8.date()
    assert act_today([live], {"stuck_after_days": 3}, CFG, TUESDAY_8, today) == []
    (key, card, why), = pending_by_person([live], CFG, today, TUESDAY_8, 3)["t-maker"]
    assert why == "live" and key[0] == 5  # with the rest, never "late" (0) or "stuck" (4)


def test_a_card_off_my_work_gets_no_morning_line():
    card = {"board": "tasks", "card_id": "flow1", "card_name": "Live flow", "client_id": "c-1", "stage": "10 - In Progress",
            "assignee_id": "t-maker", "due_date": "2026-10-01", "on_my_work": False}  # fmt: skip
    assert pending_by_person([card], CFG, TUESDAY_8.date(), TUESDAY_8, 3) == {}
    assert pending_by_person([dict(card, on_my_work=None)], CFG, TUESDAY_8.date(), TUESDAY_8, 3)  # before 0023: kept
