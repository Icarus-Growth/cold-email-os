"""Stage alerts: the right channel, one tag, CANN format, failures posted once."""

import json

from fakes import AUTOMATIONS, OS, FakeSlack, config, world

from alerts import handle_form_submitted, handle_stage_change, route
from common import Config

CFG = config()


def first_rule(**match):
    for rule in CFG.rules["rules"]:
        if all(rule.get(k) == v for k, v in match.items()) and rule["board"] != "*":
            return rule
    raise AssertionError("no rule with {0}".format(match))


def card_world(board, card, row_extra=None):
    db = world(**{board: [card]})
    row = {
        "id": 1,
        "board": board,
        "record_id": card["id"],
        "record_name": card.get("name", "Card one"),
        "client_id": card.get("client_id"),
        "from_stage": None,
        "to_stage": "0 - Backlog",
        "changed_by_id": "t-owner",
    }
    row.update(row_extra or {})
    return db, row


def test_new_card_posts_in_new_tasks_with_one_tag_and_a_button():
    db, row = card_world("tasks", {"id": "k1", "client_id": "c-1", "assignee_id": "t-maker", "due_date": "2026-11-03"})
    slack = FakeSlack()
    res = handle_stage_change(db, slack, CFG, {}, row)
    assert res["posted"] and res["channel"] == "new-tasks"
    post = slack.in_channel("new-tasks")[0]
    text = post["text"]
    assert "*Client:* Example Client A" in text
    assert "*Card:* Card one (Tasks)" in text
    assert "(new card), moved by Olive Owner" in text
    assert "*Due:* Nov 3 2026" in text
    assert text.count("<@") == 1 and "<@UMAKER>" in text
    assert len(text.split("\n")) <= 6
    btn = post["blocks"][-1]["elements"][0]
    assert btn["url"] == OS + "/board/tasks/k1" and btn["text"]["text"] == "Open the card"
    assert post["bot_name"].startswith("🆕 ")


def test_sent_back_card_puts_the_notes_in_a_thread():
    rule = first_rule(channel="amendments")
    board, stage, col = rule["board"], rule["to"][0], rule.get("thread")
    card = {"id": "k2", "client_id": "c-1", "assignee_id": "t-maker", col: "Make the logo bigger."}
    db, row = card_world(board, card, {"from_stage": "30 - In Review", "to_stage": stage})
    slack = FakeSlack()
    handle_stage_change(db, slack, CFG, {}, row)
    main, reply = slack.in_channel("amendments")
    assert "Check the thread for the notes." in main["text"]
    assert reply["thread_ts"] == main["ts"] and reply["text"] == "Make the logo bigger."
    assert "→ " + stage in main["text"]


def test_review_stage_tags_the_reviewer():
    rule = first_rule(channel="review")
    card = {"id": "k3", "client_id": "c-1", "assignee_id": "t-maker", "reviewer_id": "t-am"}
    db, row = card_world(rule["board"], card, {"from_stage": "10 - In Progress", "to_stage": rule["to"][0]})
    slack = FakeSlack()
    handle_stage_change(db, slack, CFG, {}, row)
    text = slack.in_channel("review")[0]["text"]
    assert ("<@UANA>" in text) and text.count("<@") == 1


def test_a_move_with_no_rule_posts_nothing():
    db, row = card_world("tasks", {"id": "k4"}, {"from_stage": "0 - Backlog", "to_stage": "10 - In Progress"})
    slack = FakeSlack()
    assert handle_stage_change(db, slack, CFG, {}, row)["posted"] is False
    assert slack.posts == []


def test_client_onboarding_moves_are_not_card_alerts():
    assert route({"board": "clients", "from_stage": None, "to_stage": "0 - Paid"}, CFG) is None


def test_a_card_with_nobody_posts_once_in_needs_a_person():
    db, row = card_world("tasks", {"id": "k5"})
    db.tables["clients"] = []
    db.tables["team"] = [t for t in db.tables["team"] if t["access"] != "Owner"]
    slack, seen = FakeSlack(), {}
    handle_stage_change(db, slack, CFG, seen, row)
    handle_stage_change(db, slack, CFG, seen, row)
    assert len(slack.in_channel("new-tasks")) == 2
    assert "Nobody is set to do this yet." in slack.in_channel("new-tasks")[0]["text"]
    assert len(slack.in_channel("needs-a-person")) == 1


NEEDS_A_PERSON = (
    "A card reaches a stage with nobody set to do it (once a day per card). A person with no Slack account "
    "linked is not posted here: the alert names them as plain text, and Step 5 links them"
)


def test_needs_a_person_posts_what_tab_3_says_it_posts(tmp_path):
    """Tab 3 once said an unlinked person is posted in needs-a-person; the code never did.
    The channel list comes from a temp folder. A student's own channels.json, made in
    tab 3, keeps the "posts" text of the day it was made, so the test must not read it."""
    channels = json.loads(json.dumps(CFG.channels))
    channels["channels"]["needs-a-person"]["posts"] = "an old text the student's file may still have"
    (tmp_path / "channels.json").write_text(json.dumps(channels))
    cfg = Config.load(AUTOMATIONS / "alert_rules.json", tmp_path / "channels.json")
    db, row = card_world("tasks", {"id": "k7", "client_id": "c-1", "assignee_id": "t-noslack"})
    slack = FakeSlack()
    handle_stage_change(db, slack, cfg, {}, row)
    assert "Nia Noslack" in slack.in_channel("new-tasks")[0]["text"]
    assert slack.in_channel("needs-a-person") == []
    nobody, row = card_world("tasks", {"id": "k8"})
    nobody.tables["clients"] = []
    nobody.tables["team"] = [t for t in nobody.tables["team"] if t["access"] != "Owner"]
    handle_stage_change(nobody, slack, cfg, {}, row)
    assert len(slack.in_channel("needs-a-person")) == 1
    tab3 = (AUTOMATIONS.parents[2] / "docs/3-automations.md").read_text()
    assert "| needs-a-person | {0} |".format(NEEDS_A_PERSON) in tab3


def test_a_slack_failure_posts_once_in_pipeline_errors():
    db, row = card_world("tasks", {"id": "k6", "assignee_id": "t-maker"})
    slack, seen = FakeSlack(), {}
    slack.fail_channels.add("chan-new-tasks")
    for _ in range(3):
        assert handle_stage_change(db, slack, CFG, seen, row)["posted"] is False
    errors = slack.in_channel("pipeline-errors")
    assert len(errors) == 1
    assert "channel_not_found" in errors[0]["text"] and "<!here>" in errors[0]["text"]
    assert OS + "/board/tasks/k6" in errors[0]["text"]


def test_when_pipeline_errors_fails_too_it_stays_silent():
    db, row = card_world("tasks", {"id": "k7", "assignee_id": "t-maker"})
    slack = FakeSlack()
    slack.fail_channels.update({"chan-new-tasks", "chan-pipeline-errors"})
    assert handle_stage_change(db, slack, CFG, {}, row)["posted"] is False
    assert slack.posts == []


def test_a_channel_not_set_up_is_reported():
    db, row = card_world("tasks", {"id": "k8", "assignee_id": "t-maker"})
    cfg = config()
    cfg.channels["channels"]["new-tasks"]["id"] = ""
    slack = FakeSlack()
    handle_stage_change(db, slack, cfg, {}, row)
    assert "new-tasks channel is not set up" in slack.in_channel("pipeline-errors")[0]["text"]


def test_a_list_with_no_board_links_to_the_client_page():
    cfg = config()
    cfg.rules["boards"]["tasks"]["link"] = "client"
    db, row = card_world("tasks", {"id": "k9", "client_id": "c-1", "assignee_id": "t-maker"})
    slack = FakeSlack()
    handle_stage_change(db, slack, cfg, {}, row)
    assert slack.posts[0]["blocks"][-1]["elements"][0]["url"] == OS + "/clients/c-1"


def test_a_submitted_form_posts_in_new_tasks():
    db = world(
        onboarding_forms=[
            {
                "id": "f1",
                "client_id": "c-1",
                "submitted_by_name": "Cara Client",
                "submitted_by_email": "cara@example.com",
                "submitted_at": "2026-10-26T10:00:00+00:00",
            }
        ]
    )
    slack = FakeSlack()
    assert handle_form_submitted(db, slack, CFG, {}, "f1")["posted"]
    post = slack.in_channel("new-tasks")[0]
    assert "Cara Client (cara@example.com)" in post["text"] and "<@UANA>" in post["text"]
    assert post["blocks"][-1]["elements"][0]["url"] == OS + "/clients/c-1"


def test_an_archived_card_or_client_posts_nothing():
    stamp = "2026-10-26T09:00:00+00:00"
    db, row = card_world("tasks", {"id": "k9", "client_id": "c-1", "assignee_id": "t-maker", "archived_at": stamp})
    slack = FakeSlack()
    assert handle_stage_change(db, slack, CFG, {}, row) == {"posted": False, "reason": "archived"}
    db, row = card_world("tasks", {"id": "k8", "client_id": "c-1", "assignee_id": "t-maker"})
    db.tables["clients"][0]["archived_at"] = stamp
    assert handle_stage_change(db, slack, CFG, {}, row)["posted"] is False
    db.tables["onboarding_forms"] = [{"id": "f9", "client_id": "c-1", "company_name": "Example Client A"}]
    assert handle_form_submitted(db, slack, CFG, {}, "f9")["posted"] is False
    assert slack.posts == []
