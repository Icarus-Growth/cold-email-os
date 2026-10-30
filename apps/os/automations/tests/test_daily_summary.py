"""Daily summary: the hour and time zone, what changed, act today, one tag per person, paging."""

from datetime import datetime, timedelta, timezone

from fakes import FakeSlack, config, world

from daily_summary import collect, is_summary_hour, previous_slot, run_daily_summary, since_for, zone

CFG = config()
UTC = timezone.utc
# Tuesday 27 Oct 2026, 08:00 in London (GMT, so 08:00 UTC)
TUESDAY_8 = datetime(2026, 10, 27, 8, 0, 20, tzinfo=UTC)


def review_card():
    for rule in CFG.rules["rules"]:
        if rule["channel"] == "review" and rule["board"] != "*":
            return rule["board"], rule["to"][0]
    raise AssertionError


def summary_world(**extra):
    board, review_stage = review_card()
    old = (TUESDAY_8 - timedelta(days=5)).isoformat()
    fresh = (TUESDAY_8 - timedelta(hours=2)).isoformat()
    open_cards = [
        {
            "board": "tasks",
            "board_label": "Tasks",
            "card_id": "late1",
            "card_name": "Late task",
            "client_id": "c-1",
            "stage": "10 - In Progress",
            "assignee_id": "t-maker",
            "due_date": "2026-10-25",
            "stage_changed_at": fresh,
        },
        {
            "board": "tasks",
            "board_label": "Tasks",
            "card_id": "stuck1",
            "card_name": "Stuck task",
            "client_id": "c-1",
            "stage": "10 - In Progress",
            "assignee_id": "t-maker",
            "due_date": None,
            "stage_changed_at": old,
        },
        {
            "board": board,
            "board_label": CFG.board_label(board),
            "card_id": "rev1",
            "card_name": "Waiting card",
            "client_id": "c-1",
            "stage": review_stage,
            "assignee_id": "t-maker",
            "reviewer_id": "t-am",
            "due_date": "2026-10-28",
            "stage_changed_at": fresh,
        },
        {
            "board": "tasks",
            "board_label": "Tasks",
            "card_id": "fine1",
            "card_name": "Fine task",
            "client_id": "c-1",
            "stage": "10 - In Progress",
            "assignee_id": "t-maker",
            "due_date": "2026-12-01",
            "stage_changed_at": fresh,
        },
    ]
    moves = [
        {
            "id": 1,
            "board": "tasks",
            "record_name": "Late task",
            "from_stage": None,
            "to_stage": "0 - Backlog",
            "changed_at": (TUESDAY_8 - timedelta(hours=20)).isoformat(),
        },
        {
            "id": 2,
            "board": "tasks",
            "record_name": "Done task",
            "from_stage": "30 - In Review",
            "to_stage": "100 - Complete",
            "changed_at": (TUESDAY_8 - timedelta(hours=3)).isoformat(),
        },
        {
            "id": 3,
            "board": "tasks",
            "record_name": "Older move",
            "from_stage": "0 - Backlog",
            "to_stage": "10 - In Progress",
            "changed_at": (TUESDAY_8 - timedelta(days=2)).isoformat(),
        },
    ]
    attention = [
        {
            "client_id": "c-1",
            "client_name": "Example Client A",
            "account_manager_id": "t-am",
            "late_cards": 1,
            "stuck_cards": 1,
            "onboarding_stuck": False,
            "needs_attention": True,
        }
    ]
    tables = {"v_open_cards": open_cards, "stage_log": moves, "v_clients_attention": attention}
    tables.update(extra)
    return world(**tables)


def test_slots_skip_the_weekend():
    tz = zone({"time_zone": "Europe/London"})
    monday_9 = datetime(2026, 10, 26, 9, 0, tzinfo=tz)
    assert previous_slot(monday_9, 8) == datetime(2026, 10, 26, 8, 0, tzinfo=tz)
    monday_7 = datetime(2026, 10, 26, 7, 0, tzinfo=tz)
    assert previous_slot(monday_7, 8) == datetime(2026, 10, 23, 8, 0, tzinfo=tz)  # Friday
    assert since_for(datetime(2026, 10, 26, 8, 0, 30, tzinfo=tz), 8, scheduled=True).weekday() == 4


def test_it_posts_only_at_the_hour_in_the_agency_time_zone():
    tz = zone({"time_zone": "America/New_York"})
    assert is_summary_hour(datetime(2026, 10, 27, 12, 0, tzinfo=UTC).astimezone(tz), 8)
    assert not is_summary_hour(datetime(2026, 10, 27, 13, 0, tzinfo=UTC).astimezone(tz), 8)
    assert not is_summary_hour(datetime(2026, 10, 31, 12, 0, tzinfo=UTC).astimezone(tz), 8)  # Saturday
    slack = FakeSlack()
    res = run_daily_summary(summary_world(), slack, CFG, {}, scheduled=True, now_utc=TUESDAY_8 + timedelta(hours=1))
    assert res["posted"] is False and slack.posts == []


def test_the_summary_main_message_and_thread():
    slack = FakeSlack()
    res = run_daily_summary(summary_world(), slack, CFG, {}, scheduled=True, now_utc=TUESDAY_8)
    assert res["posted"] and res["replies"] == 3
    main, changed, todo, clients = slack.in_channel("daily-summary")
    assert all(p["thread_ts"] == main["ts"] for p in (changed, todo, clients))
    assert "1 moved, 1 new, 1 finished, 0 sent back" in main["text"]
    assert "3 cards (2 due or late, 1 stuck, 1 waiting for review)" in main["text"]
    assert "*Clients that need attention:* 1." in main["text"]
    assert "<@" not in main["text"] and len(main["text"].split("\n")) <= 6
    assert "Older move" not in changed["text"]  # before the last summary
    assert "Late task" in todo["text"] and "late 2 days" in todo["text"]
    assert "Stuck task" in todo["text"] and "stuck 5 days" in todo["text"]
    assert "Waiting card" in todo["text"] and "waiting for review" in todo["text"]
    assert "Fine task" not in todo["text"]
    assert "<https://os.example.com/board/tasks/late1|Late task>" in todo["text"]
    btn = main["blocks"][-1]["elements"][0]  # the OS home page is My Work
    assert btn["text"]["text"] == "Open My Work" and btn["url"] == "https://os.example.com/"


def test_each_person_is_tagged_once():
    slack = FakeSlack()
    run_daily_summary(summary_world(), slack, CFG, {}, scheduled=False, now_utc=TUESDAY_8)
    everything = "\n".join(p["text"] for p in slack.posts)
    assert everything.count("<@UMAKER>") == 1
    assert everything.count("<@UANA>") == 1  # reviewer in act today, then plain name as account manager
    assert "Ana Manager" in slack.posts[-1]["text"]


def test_reads_go_in_pages_of_500_and_stop_at_20():
    base = TUESDAY_8 - timedelta(hours=12)
    moves = [
        {
            "id": i,
            "board": "tasks",
            "record_name": "m",
            "from_stage": "0 - Backlog",
            "to_stage": "10 - In Progress",
            "changed_at": (base + timedelta(seconds=i)).isoformat(),
        }
        for i in range(12000)
    ]
    db = summary_world(stage_log=moves)
    slack = FakeSlack()
    run_daily_summary(db, slack, CFG, {}, scheduled=True, now_utc=TUESDAY_8)
    log_reads = [r for r in db.reads if r["table"] == "stage_log"]
    assert all(r["limit"] <= 500 for r in log_reads)
    assert len(log_reads) == 20
    assert "10000 moved" in slack.posts[0]["text"]
    assert "…and" in slack.posts[1]["text"]


def test_nothing_to_do_is_one_short_post():
    db = world(v_open_cards=[], stage_log=[], v_clients_attention=[])
    slack = FakeSlack()
    run_daily_summary(db, slack, CFG, {}, scheduled=False, now_utc=TUESDAY_8)
    assert len(slack.posts) == 1 and "Nothing to act on today." in slack.posts[0]["text"]


def test_a_failure_is_posted_once():
    slack, seen = FakeSlack(), {}
    slack.fail_channels.add("chan-daily-summary")
    for _ in range(2):
        run_daily_summary(summary_world(), slack, CFG, seen, scheduled=False, now_utc=TUESDAY_8)
    assert len(slack.in_channel("pipeline-errors")) == 1


def test_archived_clients_and_cards_are_left_out():
    stamp = "2026-10-26T09:00:00+00:00"
    db = summary_world(tasks=[{"id": "stuck1", "client_id": "c-1", "archived_at": stamp}, {"id": "late1"}])
    slack = FakeSlack()
    run_daily_summary(db, slack, CFG, {}, scheduled=False, now_utc=TUESDAY_8)
    (todo,) = [p["text"] for p in slack.posts if p["text"].startswith("*Act today*")]
    assert "Stuck task" not in todo and "Late task" in todo
    assert "*Act today:* 2 cards" in slack.posts[0]["text"]

    db = summary_world()
    db.tables["clients"][0]["archived_at"] = stamp
    for m in db.tables["stage_log"]:
        m["client_id"] = "c-1"
    slack = FakeSlack()
    run_daily_summary(db, slack, CFG, {}, scheduled=False, now_utc=TUESDAY_8)
    assert len(slack.posts) == 1 and "Nothing to act on today." in slack.posts[0]["text"]
    assert "0 moved, 0 new" in slack.posts[0]["text"] and "need attention:* 0." in slack.posts[0]["text"]


def test_the_archived_cards_are_read_from_every_board():
    db = summary_world()
    collect(db, TUESDAY_8, CFG)
    assert {r["table"] for r in db.reads} >= set(CFG.boards)
