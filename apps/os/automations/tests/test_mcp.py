"""The AI connector: who may see and run what, every action, the stage log, the link and the audit."""

import copy
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from fakes import AUTOMATIONS, TEAM, FakeDB, columns, config, ladders, world

import mcp_actions
from mcp_actions import ALL, BRAIN_RULE, NOT_SET_UP, PAGE, Registry, load_spec
from mcp_server import INSTRUCTIONS, IDENTITY_TTL_SECONDS, NO_ACCESS, Connector, public_base, shrink, token_hash

CFG = config()
SPEC = load_spec(AUTOMATIONS / "mcp_actions.json")
PEPPER = "test-pepper"
TODAY = date.today()
NOW = datetime.now(timezone.utc)
TOKENS = {"t-owner": "owner-token", "t-maker": "member-token", "t-am": "admin-token"}
PLAN_ACTIONS = {
    "my_queue", "urgent", "boards", "cards.search", "cards.get", "clients.get", "team", "calls.get", "forms.get",
    "metrics.get", "cards.create", "cards.move", "cards.update", "cards.note", "calls.add", "metrics.add",
    "clients.update", "brain.index", "brain.map", "brain.search", "brain.read", "docs.read", "docs.write",
    "brain.list", "skills.list", "skills.read", "db.read", "db.write",
}  # fmt: skip
OTHER_BOARD = next((b for b in SPEC["boards"] if b != "tasks"), "tasks")


def day(n):
    return (TODAY + timedelta(days=n)).isoformat()


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def team_rows():
    rows = copy.deepcopy(TEAM)
    for r in rows:
        r.update(can_sign_in=True, capacity=10)
        if r["id"] in TOKENS:
            r["mcp_token_hash"] = token_hash(TOKENS[r["id"]], PEPPER)
    return rows


def open_card(card_id, board="tasks", **extra):
    row = {
        "board": board,
        "board_label": CFG.board_label(board),
        "card_id": card_id,
        "card_name": card_id,
        "client_id": "c-1",
        "stage": SPEC["boards"][board]["stages"][1],
        "assignee_id": "t-maker",
        "reviewer_id": None,
        "due_date": None,
        "stage_changed_at": ago(1),
    }
    row.update(extra)
    return row


def make(**tables):
    base = {
        "team": team_rows(),
        "tasks": [
            {"id": "k1", "task_name": "Write the brief", "client_id": "c-1", "stage": "10 - In Progress",
             "assignee_id": "t-maker", "notes": "First line.", "updated_at": ago(1)},
            {"id": "k2", "task_name": "Old done task", "client_id": "c-1", "stage": "100 - Complete",
             "assignee_id": "t-maker", "updated_at": ago(9)},
            {"id": "k3", "task_name": "Archived brief", "client_id": "c-1", "stage": "10 - In Progress",
             "assignee_id": "t-maker", "archived_at": ago(2)},
        ],
        "mcp_audit": [],
        "stage_log": [],
        "v_team_load": [{"team_id": "t-maker", "open_cards": 12, "late_cards": 1, "sent_back_cards": 0, "overloaded": True}],
    }  # fmt: skip
    base.update(tables)
    db = world(**base)
    return db, Connector(db, Registry(SPEC), CFG, PEPPER, today=TODAY)


def ok(res):
    assert res["ok"], res
    return res["result"]


# --------------------------------------------------------------------------- the registry per type


def test_the_type_offers_every_plan_action_and_nothing_else():
    assert set(SPEC["actions"]) - {"emails.tick"} == PLAN_ACTIONS
    assert ("emails.tick" in SPEC["actions"]) == ("emails" in SPEC)
    assert set(SPEC["actions"]) <= set(ALL)
    for name in SPEC["actions"]:
        assert not any(w in name for w in ("delete", "remove", "team.", "token", "key")), name


def test_the_type_file_matches_the_database():
    ladder = ladders()
    assert set(SPEC["boards"]) == set(CFG.boards)
    for board, spec in SPEC["boards"].items():
        assert spec["stages"] == ladder[board], board
        cols = columns(board)
        for col in [spec["name"]] + spec["fields"] + spec["people"] + [spec.get("work_link") or "due_date"]:
            assert col in cols, (board, col)
        if spec.get("items"):
            assert spec["items"]["key"] in columns(spec["items"]["table"])
    assert SPEC["client_stages"] == ladder["clients"]
    client_cols = columns("clients")
    assert all(c in client_cols for c in SPEC["client_fields"])
    assert not set(SPEC["client_fields"]) & {"slack_channel_id", "form_code", "id", "archived_at"}
    for period, table in (("daily", "daily_metrics"), ("weekly", "weekly_metrics")):
        assert SPEC["metrics"][period] and all(c in columns(table) for c in SPEC["metrics"][period])


def test_only_owners_and_admins_get_urgent_and_clients_update():
    reg = Registry(SPEC)
    member = set(reg.visible_to("Member"))
    assert "urgent" not in member and "clients.update" not in member
    assert set(reg.visible_to("Admin")) == set(reg.visible_to("Owner")) == set(SPEC["actions"])
    assert reg.visible_to(None) == [] and reg.visible_to("Nobody") == []


# --------------------------------------------------------------------------- who is calling


def test_an_unknown_link_sees_nothing_and_runs_nothing():
    db, mcp = make()
    out = mcp.list_actions("not-a-token")
    assert out["actions"] == [] and out["message"] == NO_ACCESS
    assert "connector key does not work" in NO_ACCESS and "link" not in NO_ACCESS  # header users have a key
    res = mcp.run("read", "not-a-token", "my_queue", {})
    assert res == {"ok": False, "error": NO_ACCESS}
    assert mcp.describe_action("", "my_queue")["ok"] is False
    assert all(a["team_id"] is None and a["ok"] is False for a in db.tables["mcp_audit"])
    assert len(db.tables["mcp_audit"]) == 3


def test_a_member_is_refused_an_admin_action_and_it_is_logged():
    db, mcp = make()
    names = [a["name"] for a in mcp.list_actions("member-token")["actions"]]
    assert "my_queue" in names and "urgent" not in names
    for kind, name, params in (
        ("read", "urgent", {}),
        ("write", "clients.update", {"client": "Example Client A", "fields": {"notes": "x"}}),
    ):
        res = mcp.run(kind, "member-token", name, params)
        # The AI must be able to say who it is for (tab 5 Step 5.6).
        assert res["ok"] is False and "is for Owners and Admins only; you are a Member" in res["error"]
        described = mcp.describe_action("member-token", name)
        assert described["ok"] is False and "Owners and Admins" in described["error"]
    assert db.tables["clients"][0].get("notes") is None
    last = db.tables["mcp_audit"][-2]
    assert last["team_id"] == "t-maker" and last["action"] == "clients.update" and last["ok"] is False
    assert ok(mcp.run("read", "admin-token", "urgent", {}))["rows"] is not None
    assert mcp.run("read", "member-token", "no.such", {})["error"].startswith("No action called 'no.such'.")


def test_a_revoked_link_is_refused():
    db, mcp = make()
    status, out = mcp.token_request({"team_id": "t-maker".ljust(36, "0"), "action": "issue"}, "owner@example.com", "x")
    assert status == 404
    db.tables["team"][1]["id"] = "11111111-2222-3333-4444-555555555555"
    member = db.tables["team"][1]["id"]
    status, out = mcp.token_request(
        {"team_id": member, "action": "issue"}, "owner@example.com", "https://ops.example.com"
    )
    assert status == 200 and set(out) == {"server", "key", "url"}
    token = out["key"]
    assert out["server"] == "https://ops.example.com/mcp/" and token not in out["server"]
    assert out["url"] == "https://ops.example.com/mcp/s/{0}/".format(token)  # claude.ai: the same key, as an address
    assert db.tables["team"][1]["mcp_token_hash"] == token_hash(token, PEPPER) != token
    assert token not in str(db.tables["mcp_audit"])
    assert mcp.run("read", token, "my_queue", {})["ok"]
    assert mcp.run("read", "member-token", "my_queue", {})["ok"] is False  # the old link died when a new one was made

    other = Connector(db, Registry(SPEC), CFG, PEPPER, clock=lambda: 1000.0, today=TODAY)
    assert other.identity(token)["known"]  # another container remembers it for up to 60 seconds
    status, out = mcp.token_request({"team_id": member, "action": "revoke"}, "owner@example.com", "x")
    assert (status, out) == (200, {"revoked": True}) and db.tables["team"][1]["mcp_token_hash"] is None
    gone = [a for a in db.tables["mcp_audit"] if a["action"] == "revoked"]
    assert [(a["team_id"], a["args"]["reason"], a["ok"]) for a in gone] == [
        (member, "replaced by a new key", True),  # the old key died when the new one was made
        (member, "Revoke button", True),
    ]
    assert all(a["args"]["by"] == db.tables["team"][0]["full_name"] for a in gone)
    assert token not in str(db.tables["mcp_audit"])
    assert mcp.run("read", token, "my_queue", {}) == {"ok": False, "error": NO_ACCESS}
    assert other.identity(token)["known"]
    other.clock = lambda: 1000.0 + IDENTITY_TTL_SECONDS
    assert other.identity(token)["known"] is False  # within a minute everywhere


def test_a_person_who_cannot_sign_in_loses_their_link():
    db, mcp = make()
    db.tables["team"][1]["can_sign_in"] = False
    assert mcp.run("read", "member-token", "my_queue", {})["ok"] is False
    db.tables["team"][0]["status"] = "Inactive"
    assert mcp.list_actions("owner-token")["actions"] == []


def test_last_seen_is_written():
    db, mcp = make()
    mcp.list_actions("member-token")
    assert db.tables["team"][1].get("mcp_last_seen_at")


def test_only_a_signed_in_owner_or_admin_can_make_a_link():
    db, mcp = make()
    target = {"team_id": "22222222-2222-3333-4444-555555555555", "action": "issue"}
    assert mcp.token_request(target, None, "x")[0] == 401
    assert mcp.token_request(target, "max@example.com", "x")[0] == 403  # a Member
    assert mcp.token_request(target, "stranger@example.com", "x")[0] == 403
    assert mcp.token_request({"team_id": "nope", "action": "issue"}, "ana@example.com", "x")[0] == 400
    db.tables["team"][3].update(id=target["team_id"], can_sign_in=False)
    status, out = mcp.token_request(target, "ana@example.com", "x")
    assert status == 400 and "cannot sign in" in out["error"]
    db.tables["team"][3]["can_sign_in"] = True
    assert mcp.token_request(target, "ana@example.com", "x")[0] == 200
    assert [a["action"] for a in db.tables["mcp_audit"]] == ["token.issue"]  # no old key, so nothing revoked
    assert mcp.token_request(dict(target, action="revoke"), "ana@example.com", "x")[0] == 200
    assert [a["action"] for a in db.tables["mcp_audit"]] == ["token.issue", "revoked"]
    assert mcp.token_request(dict(target, action="revoke"), "ana@example.com", "x")[0] == 200  # again: still logged
    assert db.tables["mcp_audit"][-1]["args"]["reason"] == "Revoke button (no key)"
    assert Connector(db, Registry(SPEC), CFG, "").token_request(target, "ana@example.com", "x")[0] == 500


def test_the_wrong_tool_bad_params_and_long_text():
    db, mcp = make()
    res = mcp.run("read", "member-token", "cards.move", {"board": "tasks", "id": "k1", "stage": "30"})
    assert res["ok"] is False and "run_write_action" in res["error"]
    assert "has no parameter" in mcp.run("read", "member-token", "my_queue", {"nope": 1})["error"]
    assert "needs board" in mcp.run("read", "member-token", "cards.get", {"id": "k1"})["error"]
    assert "must be an object" in mcp.run("read", "member-token", "my_queue", "not json")["error"]
    assert shrink({"t": "x" * 2000})["t"].endswith("[cut, 2000 letters]")
    assert public_base("http://abc-web.modal.run/") == "https://abc-web.modal.run"
    assert public_base("http://localhost:8000/") == "http://localhost:8000"


# --------------------------------------------------------------------------- read actions


def queue_world():
    review = CFG.review_stages()["tasks"][0]
    cards = [
        open_card("stuck-long", stage_changed_at=ago(20)),
        open_card("due-today", due_date=day(0)),
        open_card("late-1", due_date=day(-1)),
        open_card("my-review", assignee_id="t-am", reviewer_id="t-maker", stage=review),
        open_card("late-5", due_date=day(-5)),
        open_card("stuck-short", stage_changed_at=ago(4)),
        open_card("not-mine", assignee_id="t-am"),
        open_card("review-not-yet", assignee_id="t-am", reviewer_id="t-maker"),
    ]
    return make(v_open_cards=cards)


def test_my_queue_is_most_urgent_first():
    db, mcp = queue_world()
    out = ok(mcp.run("read", "member-token", "my_queue", {}))
    assert [r["id"] for r in out["rows"]] == ["late-5", "late-1", "due-today", "my-review", "stuck-long", "stuck-short"]
    assert out["rows"][0]["why"].startswith("late 5 days")
    assert "waiting for your review" in out["rows"][3]["why"]
    assert out["rows"][0]["link"] == "https://os.example.com/board/tasks/late-5"
    assert out["rows"][0]["client"] == "Example Client A" and out["next_page"] is None


def test_urgent_is_the_whole_team_for_admins():
    db, mcp = queue_world()
    rows = ok(mcp.run("read", "owner-token", "urgent", {}))["rows"]
    assert rows[0]["id"] == "late-5" and len(rows) == 8
    assert {r.get("assignee") for r in rows} == {"Max Maker", "Ana Manager"}


def test_reads_give_100_rows_and_a_next_page():
    db, mcp = make(v_open_cards=[open_card("c{0:03d}".format(i)) for i in range(250)])
    first = ok(mcp.run("read", "member-token", "my_queue", {}))
    assert len(first["rows"]) == PAGE == 100 and first["next_page"] == 2 and first["total"] == 250
    last = ok(mcp.run("read", "member-token", "my_queue", {"page": "3"}))
    assert len(last["rows"]) == 50 and last["next_page"] is None


def test_boards_lists_stages_with_counts():
    db, mcp = make(v_open_cards=[open_card("a"), open_card("b"), open_card("c", board=OTHER_BOARD)])
    out = ok(mcp.run("read", "member-token", "boards", {}))["boards"]
    assert [b["board"] for b in out] == list(SPEC["boards"])
    tasks = out[0]
    assert tasks["stages"][1] == {"stage": SPEC["boards"]["tasks"]["stages"][1], "open_cards": 2}
    assert tasks["finished_stages"] == CFG.boards["tasks"]["final"]


def test_cards_search_leaves_out_finished_and_archived():
    db, mcp = make()
    rows = ok(mcp.run("read", "member-token", "cards.search", {"query": "brief"}))["rows"]
    assert [r["id"] for r in rows] == ["k1"]
    rows = ok(mcp.run("read", "member-token", "cards.search", {"person": "me", "include_finished": "true"}))["rows"]
    assert [r["id"] for r in rows] == ["k1", "k2"]
    assert ok(mcp.run("read", "member-token", "cards.search", {"person": "Ana"}))["rows"] == []
    db.tables["clients"][0]["archived_at"] = ago(1)
    mcp = Connector(db, Registry(SPEC), CFG, PEPPER, today=TODAY)
    assert ok(mcp.run("read", "member-token", "cards.search", {"board": "Tasks"}))["rows"] == []


def test_cards_get_has_history_and_items():
    db, mcp = make()
    mcp.run("write", "member-token", "cards.move", {"board": "tasks", "id": "k1", "stage": "30"})
    out = ok(mcp.run("read", "member-token", "cards.get", {"board": "tasks", "id": "k1"}))
    assert out["card"]["task_name"] == "Write the brief"
    assert out["history"][0]["from"] == "10 - In Progress" and out["history"][0]["by"] == "Max Maker"
    with_items = [b for b, s in SPEC["boards"].items() if s.get("items")]
    for board in with_items:
        item = SPEC["boards"][board]["items"]
        db.tables[board] = [{"id": "p1", "client_id": "c-1", "stage": SPEC["boards"][board]["stages"][0]}]
        db.tables[item["table"]] = [
            {"id": "e1", item["key"]: "p1", "position": 1, "email_name": "One"},
            {"id": "e2", item["key"]: "p1", "position": 2, "email_name": "Gone", "archived_at": ago(1)},
        ]
        rows = ok(mcp.run("read", "member-token", "cards.get", {"board": board, "id": "p1"}))["items"]["rows"]
        assert [r["id"] for r in rows] == ["e1"]
    assert "No card" in mcp.run("read", "member-token", "cards.get", {"board": "tasks", "id": "zz"})["error"]
    assert "No board" in mcp.run("read", "member-token", "cards.get", {"board": "nope", "id": "k1"})["error"]


def test_clients_get_by_name_and_two_matches_ask_which():
    db, mcp = make(
        calls=[{"id": "call1", "client_id": "c-1", "title": "Kick-off", "call_at": ago(1)},
               {"id": "call2", "client_id": "c-1", "title": "Old", "call_at": ago(9), "archived_at": ago(1)}],
        v_open_cards=[open_card("a")],
    )  # fmt: skip
    out = ok(mcp.run("read", "member-token", "clients.get", {"client": "example client a"}))
    assert out["client"]["client_name"] == "Example Client A" and "form_code" not in out["client"]
    assert out["people"]["account_manager"] == "Ana Manager"
    assert [c["id"] for c in out["recent_calls"]] == ["call1"] and len(out["open_cards"]) == 1
    db.tables["clients"].append({"id": "c-2", "client_name": "Example Client AB"})
    db.tables["clients"].append({"id": "c-3", "client_name": "Example Client ABC"})
    res = mcp.run("read", "member-token", "clients.get", {"client": "Example Client AB"})
    assert ok(res)["client"]["id"] == "c-2"  # an exact name wins
    res = mcp.run("read", "member-token", "clients.get", {"client": "example"})
    assert res["ok"] is False and "matches 3 clients" in res["error"]


def test_team_shows_the_load():
    db, mcp = make()
    rows = ok(mcp.run("read", "member-token", "team", {}))["team"]
    maker = next(r for r in rows if r["id"] == "t-maker")
    assert maker["open_cards"] == 12 and maker["overloaded"] is True and maker["is_me"] is True
    assert all("mcp_token_hash" not in r and "slack_user_id" not in r for r in rows)


def test_calls_forms_and_metrics_reads():
    db, mcp = make(
        calls=[{"id": "call1", "client_id": "c-1", "title": "Kick-off", "summary": "s" * 900, "transcript": "long"}],
        onboarding_forms=[{"id": "f1", "client_id": "c-1", "answers": {"q1": "yes"}, "submitted_at": ago(3)}],
        weekly_metrics=[{"id": 1, "client_id": "c-1", "week_start": day(-7)},
                        {"id": 2, "client_id": "c-1", "week_start": day(-14), "archived_at": ago(1)}],
    )  # fmt: skip
    listed = ok(mcp.run("read", "member-token", "calls.get", {"client": "Example Client A"}))["rows"]
    assert len(listed[0]["summary"]) == 300 and "transcript" not in listed[0]
    assert ok(mcp.run("read", "member-token", "calls.get", {"id": "call1"}))["call"]["transcript"] == "long"
    assert ok(mcp.run("read", "member-token", "forms.get", {"id": "f1"}))["form"]["answers"] == {"q1": "yes"}
    assert [
        f["id"] for f in ok(mcp.run("read", "member-token", "forms.get", {"client": "Example Client A"}))["rows"]
    ] == ["f1"]
    rows = ok(mcp.run("read", "member-token", "metrics.get", {"client": "Example Client A"}))["rows"]
    assert [r["id"] for r in rows] == [1]
    assert (
        "daily"
        in mcp.run("read", "member-token", "metrics.get", {"client": "Example Client A", "period": "monthly"})["error"]
    )


# --------------------------------------------------------------------------- write actions


def test_a_moved_card_writes_the_stage_log_with_the_mover_on_every_board():
    for board, spec in SPEC["boards"].items():
        db, mcp = make(
            **{board: [{"id": "m1", spec["name"]: "Move me", "client_id": "c-1", "stage": spec["stages"][0]}]}
        )
        target = spec["stages"][2]
        out = ok(mcp.run("write", "member-token", "cards.move", {"board": board, "id": "m1", "stage": target}))
        assert out["moved"] and out["from"] == spec["stages"][0] and out["to"] == target
        (log,) = db.tables["stage_log"]
        assert (log["board"], log["record_id"], log["to_stage"], log["changed_by_id"]) == (
            board,
            "m1",
            target,
            "t-maker",
        )
        assert db.tables["mcp_audit"][-1]["action"] == "cards.move" and db.tables["mcp_audit"][-1]["ok"] is True


def test_a_repeat_move_by_the_same_person_names_the_mover_every_time():
    """Before 0012, every second move in a row lost "moved by". The database (0012) takes the mover
    whenever the update names it, so each move must send the stage and the mover together."""
    db, mcp = make()
    for to in ("30 - In Review", "10 - In Progress", "30 - In Review", "10 - In Progress"):
        ok(mcp.run("write", "owner-token", "cards.move", {"board": "tasks", "id": "k1", "stage": to}))
    moves = [v for t, i, v in db.updates if t == "tasks" and i == "k1"]
    assert len(moves) == 4 and all(v == {"stage": v["stage"], "stage_changed_by_id": "t-owner"} for v in moves)
    assert [r["changed_by_id"] for r in db.tables["stage_log"]] == ["t-owner"] * 4


def test_move_takes_a_number_and_refuses_bad_or_archived():
    db, mcp = make()
    assert (
        ok(mcp.run("write", "member-token", "cards.move", {"board": "tasks", "id": "k1", "stage": "in review"}))["to"]
        == "30 - In Review"
    )
    assert (
        ok(mcp.run("write", "member-token", "cards.move", {"board": "tasks", "id": "k1", "stage": "30"}))["moved"]
        is False
    )
    res = mcp.run("write", "member-token", "cards.move", {"board": "tasks", "id": "k1", "stage": "Done-ish"})
    assert res["ok"] is False and "100 - Complete" in res["error"]
    res = mcp.run("write", "member-token", "cards.move", {"board": "tasks", "id": "k3", "stage": "30"})
    assert "archived" in res["error"]
    assert len(db.tables["stage_log"]) == 1


def test_create_starts_at_the_first_open_stage_and_logs_it():
    db, mcp = make()
    out = ok(mcp.run("write", "member-token", "cards.create",
                     {"board": "tasks", "name": "New one", "assignee": "me", "due_date": day(2), "client": "Example Client A"}))  # fmt: skip
    row = db.tables["tasks"][-1]
    assert row["stage"] == "0 - Backlog" and row["created_by_id"] == "t-maker"
    assert row["assignee_id"] == "t-maker" and out["created"]["link"].startswith("https://os.example.com/board/tasks/")
    assert db.tables["stage_log"][-1]["from_stage"] is None and db.tables["stage_log"][-1]["changed_by_id"] == "t-maker"
    if OTHER_BOARD != "tasks":
        res = mcp.run("write", "member-token", "cards.create", {"board": OTHER_BOARD, "name": "No client"})
        assert "needs a client" in res["error"]
    db.tables["clients"][0]["archived_at"] = ago(1)
    mcp = Connector(db, Registry(SPEC), CFG, PEPPER, today=TODAY)
    assert (
        "archived"
        in mcp.run(
            "write", "member-token", "cards.create", {"board": "tasks", "name": "x", "client": "Example Client A"}
        )["error"]
    )


def test_a_new_card_never_starts_at_a_finished_stage():
    """A Tasks card made with no stage once started at '-1 - Rejected' and left my_queue at once."""
    for key in SPEC["boards"]:
        db, mcp = make()
        args = {"board": key, "name": "Fresh " + key, "assignee": "me", "client": "Example Client A"}
        if "assignee_id" not in SPEC["boards"][key].get("people", []):
            args.pop("assignee")
        ok(mcp.run("write", "member-token", "cards.create", args))
        stage = db.tables[key][-1]["stage"]
        assert stage not in CFG.boards[key].get("final", []), (key, stage)
        assert stage == next(s for s in SPEC["boards"][key]["stages"] if s not in CFG.boards[key].get("final", []))


def test_update_changes_only_allowed_fields_and_note_adds_a_dated_line():
    db, mcp = make()
    ok(
        mcp.run(
            "write",
            "member-token",
            "cards.update",
            {"board": "tasks", "id": "k1", "due_date": day(3), "work_link": "https://doc.example.com/1"},
        )
    )
    row = db.tables["tasks"][0]
    assert row["due_date"] == day(3) and row["links"] == "https://doc.example.com/1"
    res = mcp.run(
        "write", "member-token", "cards.update", {"board": "tasks", "id": "k1", "fields": {"stage": "100 - Complete"}}
    )
    assert res["ok"] is False and "cards.move" in res["error"] and row["stage"] == "10 - In Progress"
    assert (
        "Nothing to change" in mcp.run("write", "member-token", "cards.update", {"board": "tasks", "id": "k1"})["error"]
    )
    ok(mcp.run("write", "member-token", "cards.note", {"board": "tasks", "id": "k1", "text": "Sent to the client."}))
    assert row["notes"] == "First line.\n\n{0}, Max Maker: Sent to the client.".format(TODAY.isoformat())


def test_emails_tick_moves_one_email_on():
    if "emails.tick" not in SPEC["actions"]:
        pytest.skip("this agency type has no emails")
    statuses = SPEC["emails"]["statuses"]
    db, mcp = make(emails=[{"id": "e1", "client_id": "c-1", "email_name": "Welcome", "status": statuses[0], "flow_id": "p1"}],
                   flows=[{"id": "p1", "client_id": "c-1"}])  # fmt: skip
    assert ok(mcp.run("write", "member-token", "emails.tick", {"id": "e1"}))["to"] == statuses[1]
    assert (
        ok(mcp.run("write", "member-token", "emails.tick", {"id": "e1", "status": statuses[-1].lower()}))["to"]
        == statuses[-1]
    )
    assert ok(mcp.run("write", "member-token", "emails.tick", {"id": "e1"}))["ticked"] is False
    db.tables["flows"][0]["archived_at"] = ago(1)
    assert "archived" in mcp.run("write", "member-token", "emails.tick", {"id": "e1", "status": statuses[0]})["error"]


def test_calls_add_and_metrics_add():
    db, mcp = make()
    ok(
        mcp.run(
            "write",
            "member-token",
            "calls.add",
            {"client": "Example Client A", "title": "Check-in", "call_type": "check-in", "summary": "Good."},
        )
    )
    assert db.tables["calls"][-1]["call_type"] == "Check-In"
    assert (
        "call_type must be"
        in mcp.run(
            "write", "member-token", "calls.add", {"client": "Example Client A", "title": "x", "call_type": "Party"}
        )["error"]
    )
    first = SPEC["metrics"]["weekly"][0]
    wed = TODAY - timedelta(days=TODAY.weekday()) + timedelta(days=2)
    ok(
        mcp.run(
            "write",
            "member-token",
            "metrics.add",
            {"client": "Example Client A", "period": "weekly", "date": wed.isoformat(), "values": {first: 5}},
        )
    )
    ok(
        mcp.run(
            "write",
            "member-token",
            "metrics.add",
            {"client": "Example Client A", "period": "week", "date": wed.isoformat(), "values": {first: 7}},
        )
    )
    (row,) = db.tables["weekly_metrics"]
    assert row[first] == 7 and row["week_start"] == (wed - timedelta(days=2)).isoformat()
    res = mcp.run(
        "write",
        "member-token",
        "metrics.add",
        {"client": "Example Client A", "period": "daily", "date": day(0), "values": {"profit": 1}},
    )
    assert res["ok"] is False and "Not: profit" in res["error"]


def test_clients_update_for_admins_logs_an_onboarding_move():
    db, mcp = make()
    stage = SPEC["client_stages"][2]
    ok(
        mcp.run(
            "write",
            "admin-token",
            "clients.update",
            {"client": "Example Client A", "fields": {"onboarding_stage": stage, "account_manager_id": "Max"}},
        )
    )
    client = db.tables["clients"][0]
    assert client["onboarding_stage"] == stage and client["account_manager_id"] == "t-maker"
    log = db.tables["stage_log"][-1]
    assert (log["board"], log["to_stage"], log["changed_by_id"]) == ("clients", stage, "t-am")
    res = mcp.run(
        "write", "admin-token", "clients.update", {"client": "Example Client A", "fields": {"slack_channel_id": "x"}}
    )
    assert res["ok"] is False and client["slack_channel_id"] is None


def test_every_call_is_in_the_audit_log():
    db, mcp = make()
    mcp.list_actions("member-token")
    mcp.describe_action("member-token", "cards.move")
    mcp.run("read", "member-token", "boards", {})
    mcp.run_status("member-token", "r1")
    assert [a["action"] for a in db.tables["mcp_audit"]] == [
        "list_actions",
        "describe_action",
        "boards",
        "get_run_status",
    ]
    assert all(a["team_id"] == "t-maker" and a["ok"] for a in db.tables["mcp_audit"])


def test_a_failed_audit_write_does_not_fail_the_call():
    class NoAudit(FakeDB):
        def insert(self, table, values):
            if table == "mcp_audit":
                raise RuntimeError("audit table down")
            return super().insert(table, values)

    db, _ = make()
    mcp = Connector(NoAudit(db.tables), Registry(SPEC), CFG, PEPPER, today=TODAY)
    assert mcp.run("read", "member-token", "boards", {})["ok"]


def test_the_web_app_serves_the_connector_and_guards_the_token_route():
    from mcp_server import signed_in_email

    app = (AUTOMATIONS / "app.py").read_text()
    assert '"fastmcp==' in app and "mount_connector(api, mcp_app)" in app
    # /mcp/token must be matched before the /mcp mount, so the connector goes on last.
    assert app.index('@api.post("/mcp/token")') < app.index("mount_connector(api, mcp_app)")
    server = (AUTOMATIONS / "mcp_server.py").read_text()
    assert server.index('api.mount("/mcp/s/{token}", mcp_app)') < server.index('api.mount("/mcp", mcp_app)')
    route = app.split('@api.post("/mcp/token")')[1].split("@api.post")[0]
    assert "if not allowed(request):" in route and "signed_in_email" in route
    assert signed_in_email("https://db.example.com", "k", "") is None
    assert signed_in_email("https://db.example.com", "k", "Bearer ") is None


# --------------------------------------------------------------------------- the second brain


def note(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def brain(tmp_path, monkeypatch):
    root = tmp_path / "second-brain"
    note(
        root,
        "INDEX.md",
        "# Second brain: INDEX\n\n- [[sales_map]]: how we sell. 2 notes.\n- [[delivery_map]]: 1 note.\n",
    )
    note(
        root,
        "sales/sales_map.md",
        "# Sales\n\n**Calls**\n- [[Discovery_Call]]\n- [[Price_Objection]]\n\nBack to [[INDEX]]\n",
    )
    note(
        root,
        "sales/Discovery_Call.md",
        "# Discovery call\n\nAsk about the budget first.\nSource: call\nRaw: [[2026-10-01_call]]\n",
    )
    note(
        root,
        "sales/Price_Objection.md",
        "# Price objection\n\nWhen a client says the price is high, show the budget math.\n",
    )
    note(root, "delivery/delivery_map.md", "# Delivery\n\n- [[Unhappy_Client]]\n\nBack to [[INDEX]]\n")
    note(root, "delivery/Unhappy_Client.md", "# Unhappy client\n\nCall them the same day. Never argue in Slack.\n")
    note(root, "raw/2026-10-01_call.md", "The whole call, word for word. budget budget.\n")
    note(root, "inbox/secret_draft.md", "budget plans not sorted yet\n")
    (tmp_path / "outside.md").write_text("budget outside the brain")
    os.symlink(str(tmp_path / "outside.md"), str(root / "sales" / "Sneaky_Link.md"))
    monkeypatch.setattr(mcp_actions, "BRAIN_DIRS", [root])
    return root


def read(mcp, name, params=None, token="member-token"):
    return mcp.run("read", token, name, params or {})


def test_the_brain_actions_are_for_every_member_and_carry_the_rule():
    reg = Registry(SPEC)
    for name in ("brain.index", "brain.map", "brain.search", "brain.read"):
        assert name in reg.visible_to("Member") and reg.entries[name]["kind"] == "read"
        assert BRAIN_RULE in reg.entries[name]["description"]
    assert "my_queue" in INSTRUCTIONS and "has nothing on" in INSTRUCTIONS and "brain.index" in INSTRUCTIONS


def test_no_notes_yet_is_a_plain_answer(tmp_path, monkeypatch):
    """Temp folders only: the repo's own second-brain/ has real notes once tab 4 is done."""
    db, mcp = make()
    shipped = tmp_path / "shipped"  # second-brain/ as the template ships it: a stub index, no notes
    note(shipped, "INDEX.md", "# Second brain: INDEX\n\nNot built yet.\n")
    note(shipped, "PROMPT.md", "# Build the second brain\n")
    only_inbox = tmp_path / "only-inbox"
    note(only_inbox, "INDEX.md", "# Second brain: INDEX\n")
    note(only_inbox, "inbox/draft.md", "not sorted yet\n")
    for dirs in ([tmp_path / "none"], [shipped], [only_inbox]):
        monkeypatch.setattr(mcp_actions, "BRAIN_DIRS", dirs)
        for name, params in (("brain.index", {}), ("brain.map", {"area": "sales"}), ("brain.search", {"query": "x"}),
                             ("brain.read", {"note": "INDEX"})):  # fmt: skip
            assert read(mcp, name, params) == {"ok": False, "error": NOT_SET_UP}


def test_brain_index_and_map(brain):
    db, mcp = make()
    out = ok(read(mcp, "brain.index"))
    assert out["index"].startswith("# Second brain: INDEX") and out["rule"] == BRAIN_RULE
    assert {a["area"] for a in out["areas"]} == {"sales", "delivery"}
    for area in ("sales", "Sales", "sales_map", "[[sales_map]]"):
        got = ok(read(mcp, "brain.map", {"area": area}))
        assert got["area"] == "sales" and sorted(got["notes"]) == ["Discovery_Call", "Price_Objection"]
    res = read(mcp, "brain.map", {"area": "hiring"})
    assert res["ok"] is False and "delivery" in res["error"] and "sales" in res["error"]


def test_brain_search_finds_notes_only(brain):
    db, mcp = make()
    hits = ok(read(mcp, "brain.search", {"query": "budget"}))["hits"]
    assert [h["note"] for h in hits] == ["Discovery_Call", "Price_Objection"]  # not raw/, inbox/ or the outside link
    assert hits[0]["path"] == "sales/Discovery_Call.md" and "budget" in hits[0]["line"]
    assert [h["note"] for h in ok(read(mcp, "brain.search", {"query": "price budget"}))["hits"]] == ["Price_Objection"]
    assert ok(read(mcp, "brain.search", {"query": "budget", "area": "delivery"}))["hits"] == []
    out = ok(read(mcp, "brain.search", {"query": "hiring plan"}))
    assert out["hits"] == [] and "the second brain has nothing on hiring plan" in out["message"]


def test_brain_search_gives_20_hits_at_most(brain):
    for i in range(30):
        note(brain, "sales/Note_{0:02d}.md".format(i), "pricing pricing\n")
    db, mcp = make()
    out = ok(read(mcp, "brain.search", {"query": "pricing"}))
    assert len(out["hits"]) == 20 and out["more"] is True


def test_brain_read_by_name_link_or_path(brain):
    db, mcp = make()
    for ref in ("Unhappy_Client", "[[Unhappy_Client]]", "unhappy_client.md", "delivery/Unhappy_Client.md"):
        got = ok(read(mcp, "brain.read", {"note": ref}))
        assert got["note"] == "Unhappy_Client" and "same day" in got["text"] and "[[Unhappy_Client]]" in got["rule"]
    assert ok(read(mcp, "brain.read", {"note": "Discovery_Call"}))["links"] == ["2026-10-01_call"]
    assert "No note called" in read(mcp, "brain.read", {"note": "Nope"})["error"]


def test_raw_sources_are_never_shipped_or_read(brain):
    """raw/ holds whole transcripts, word for word. Tab 4 keeps details about one lead or one
    person only there, and every Member's AI can read the brain, so the connector never does."""
    db, mcp = make()
    for ref in ("2026-10-01_call", "[[2026-10-01_call]]", "raw/2026-10-01_call.md", "sales/../raw/2026-10-01_call.md"):
        res = read(mcp, "brain.read", {"note": ref})
        assert res["ok"] is False and "word for word" not in str(res.get("text")), ref
    assert "whole sources" in read(mcp, "brain.read", {"note": "raw/2026-10-01_call.md"})["error"]
    assert all("raw" not in h["path"] for h in ok(read(mcp, "brain.search", {"query": "call word"}))["hits"])
    assert "raw" in mcp_actions.BRAIN_SKIP
    app = (AUTOMATIONS / "app.py").read_text()
    shipped = app.split('remote_path="/app/second-brain"')[1].split(")")[0]
    assert '"raw", "raw/**"' in shipped and '"inbox", "inbox/**"' in shipped


def test_a_path_outside_the_brain_is_refused(brain):
    db, mcp = make()
    for ref in ("../outside.md", "sales/../../outside.md", str(brain.parent / "outside.md"), "/etc/passwd",
                "../../../../app.py"):  # fmt: skip
        res = read(mcp, "brain.read", {"note": ref})
        assert res["ok"] is False and "outside the second brain" in res["error"], ref
    for ref in ("Sneaky_Link", "sales/Sneaky_Link.md"):  # a link inside that points outside
        res = read(mcp, "brain.read", {"note": ref})
        assert res["ok"] is False and "budget outside" not in str(res), ref
    for ref in ("inbox/secret_draft.md", "secret_draft"):
        res = read(mcp, "brain.read", {"note": ref})
        assert res["ok"] is False and "not sorted" in res["error"] or "No note called" in res["error"], ref
    assert db.tables["mcp_audit"][-1]["action"] == "brain.read" and db.tables["mcp_audit"][-1]["ok"] is False
