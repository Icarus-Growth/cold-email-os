"""A new client: one post in new-tasks, and no Slack channel is ever made."""

from fakes import OS, FakeSlack, config, world

from new_client import handle_new_client

CFG = config()


def test_a_new_client_posts_once_in_new_tasks_and_makes_no_channel():
    db, slack = world(), FakeSlack()
    res = handle_new_client(db, slack, CFG, {}, "c-1")
    assert res["posted"]
    assert slack.calls == []  # no channel made, nobody invited, nothing pinned
    (post,) = slack.posts
    assert post["channel"] == "chan-new-tasks" and post["bot_name"].startswith("🤝 ")
    text = post["text"]
    assert "*Client:* Example Client A" in text
    assert text.count("<@") == 1 and "<@UANA>" in text
    assert "https://onboarding.example.com/form/abc123?company_name=Example%20Client%20A" in text
    assert "Slack channel is not linked yet" in text
    assert post["blocks"][-1]["elements"][0]["url"] == OS + "/clients/c-1"


def test_no_account_manager_says_so():
    db = world()
    db.tables["clients"][0].update(account_manager_id=None, slack_channel_id="chan-client")
    slack = FakeSlack()
    handle_new_client(db, slack, CFG, {}, "c-1")
    text = slack.posts[0]["text"]
    assert "Nobody is the account manager yet" in text and "<@" not in text
    assert "not linked yet" not in text


def test_an_archived_or_missing_client_posts_nothing():
    db, slack = world(), FakeSlack()
    db.tables["clients"][0]["archived_at"] = "2026-10-26T09:00:00+00:00"
    assert handle_new_client(db, slack, CFG, {}, "c-1")["posted"] is False
    assert handle_new_client(db, slack, CFG, {}, "nope")["posted"] is False
    assert slack.posts == []


def test_a_failure_is_posted_in_pipeline_errors():
    db, slack = world(), FakeSlack()
    slack.fail_channels.add("chan-new-tasks")
    assert handle_new_client(db, slack, CFG, {}, "c-1")["posted"] is False
    assert len(slack.in_channel("pipeline-errors")) == 1
