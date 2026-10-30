"""Team access message: a direct message with the address, email and temporary password."""

from fakes import OS, FakeSlack, config, world

from team_invite import handle_team_invite

CFG = config()


def test_the_message_has_what_the_person_needs():
    slack = FakeSlack()
    res = handle_team_invite(world(), slack, CFG, {}, {"team_id": "t-maker", "temp_password": "Temp-Pass-1"})
    assert res == {"sent": True}
    dm = slack.posts[0]
    assert dm["channel"] == "dm-UMAKER"
    assert OS in dm["text"] and "max@example.com" in dm["text"] and "`Temp-Pass-1`" in dm["text"]


def test_a_person_with_no_slack_id_is_found_by_email_and_saved():
    db = world()
    slack = FakeSlack()
    slack.users_by_email["nia@example.com"] = "UNIA"
    assert handle_team_invite(db, slack, CFG, {}, {"team_id": "t-noslack", "temp_password": "x"})["sent"]
    assert ("team", "t-noslack", {"slack_user_id": "UNIA"}) in db.updates


def test_no_slack_account_is_an_answer_not_an_error():
    slack = FakeSlack()
    res = handle_team_invite(world(), slack, CFG, {}, {"team_id": "t-noslack", "temp_password": "x"})
    assert res["sent"] is False and "nia@example.com" in res["reason"]
    assert slack.posts == []


def test_missing_fields_and_the_password_never_comes_back():
    slack = FakeSlack()
    assert handle_team_invite(world(), slack, CFG, {}, {"team_id": "t-maker"})["sent"] is False
    slack.fail_channels.add("dm-UMAKER")
    res = handle_team_invite(world(), slack, CFG, {}, {"team_id": "t-maker", "temp_password": "Secret-9"})
    assert res["sent"] is False and "Secret-9" not in str(res)
    assert all("Secret-9" not in p["text"] for p in slack.posts)
