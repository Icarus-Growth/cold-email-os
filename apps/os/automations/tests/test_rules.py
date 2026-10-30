"""alert_rules.json matches the database: every board, stage, channel and column is real."""

from fakes import AUTOMATIONS, clean_bot_name, columns, config, ladders, load_json

from alerts import unknown_stages

CFG = config()
LADDERS = ladders()
CLIENT_COLS = columns("clients")
TAGS = {"assignee", "reviewer", "owner"}


def test_every_rule_stage_is_on_its_board():
    assert unknown_stages(CFG, LADDERS) == []


def test_every_board_has_a_stage_log_and_real_final_stages():
    for board, meta in CFG.boards.items():
        assert board in LADDERS, board
        for stage in meta.get("final", []):
            assert stage in LADDERS[board], (board, stage)


def test_every_channel_is_in_channels_json():
    known = set(load_json(AUTOMATIONS / "channels.json")["channels"])
    for rule in CFG.rules["rules"]:
        assert rule["channel"] in known, rule


def test_every_tag_and_client_column_exists():
    for rule in CFG.rules["rules"]:
        assert rule["tag"], rule
        for target in rule["tag"]:
            if target.startswith("client."):
                assert target.split(".", 1)[1] in CLIENT_COLS, target
            else:
                assert target in TAGS, target
    for col in CFG.rules["client_roles"]:
        assert col in CLIENT_COLS, col


def test_thread_columns_exist_on_the_board():
    for rule in CFG.rules["rules"]:
        if rule.get("thread"):
            assert rule["thread"] in columns(rule["board"]), rule


def test_every_bot_name_is_a_real_name_with_an_emoji():
    for rule in CFG.rules["rules"]:
        assert rule["emoji"].strip()
        clean_bot_name(rule["bot_name"])
        assert rule["action"].endswith("."), rule


def test_every_sent_back_stage_goes_to_amendments():
    """A stage ending in 9 (except Blocked) means "sent back": it posts in amendments."""
    routed = {(r["board"], s): r["channel"] for r in CFG.rules["rules"] for s in r.get("to", [])}
    for board in CFG.boards:
        for stage in LADDERS[board]:
            n = int(stage.split(" ")[0])
            if n > 9 and n % 10 == 9:
                assert routed.get((board, stage)) == "amendments", (board, stage)


def test_every_board_but_lists_gets_a_new_card_rule():
    assert any(r.get("when") == "new" and r["board"] == "*" for r in CFG.rules["rules"])
