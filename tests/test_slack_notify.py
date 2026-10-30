"""The shared Slack sender: links read [LINK], lines are spaced, every post names itself and
wears the logo from SLACK_ICON_URL.

    python3 -m pytest tests/test_slack_notify.py
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import shared.slack_notify as slack_notify  # noqa: E402
from shared.slack_notify import SlackError, clean_bot_name, linked, message_payload, spaced, spaced_blocks  # noqa: E402


def test_bare_link_becomes_link_label():
    assert linked("See https://a.com/x.") == "See <https://a.com/x|[LINK]>."


def test_labelled_and_mentions_stay():
    assert linked("<https://a.com|Open> <@U1>") == "<https://a.com|Open> <@U1>"


def test_label_less_angle_link_gets_label():
    assert linked("<https://a.com>") == "<https://a.com|[LINK]>"


def test_code_is_left_alone():
    assert linked("`https://a.com` and ```\nhttps://b.com\n```") == "`https://a.com` and ```\nhttps://b.com\n```"


def test_brackets_and_trailing_punctuation():
    assert linked("(https://a.com/p_(1))") == "(<https://a.com/p_(1)|[LINK]>)"
    assert linked("x https://b.com/q?x=1,") == "x <https://b.com/q?x=1|[LINK]>,"


def test_empty_and_plain_text():
    assert linked("") == ""
    assert linked("no links") == "no links"


def test_blocks_only_mrkdwn():
    out = spaced_blocks(
        [
            {"type": "section", "text": {"type": "mrkdwn", "text": "a https://x.io\nb"}},
            {"type": "header", "text": {"type": "plain_text", "text": "https://x.io"}},
        ]
    )
    assert out[0]["text"]["text"] == "a <https://x.io|[LINK]>\n\nb"
    assert out[1]["text"]["text"] == "https://x.io"


def test_lines_get_a_blank_line_between_them_but_code_does_not():
    assert spaced("a\nb\n\nc") == "a\n\nb\n\nc"
    assert spaced("```\nx\ny\n```") == "```\nx\ny\n```"


def test_a_post_must_name_itself():
    for bad in ("", "  ", "Bot", "automations"):
        with pytest.raises(SlackError):
            clean_bot_name(bad)
    assert clean_bot_name("👀 Ready For Review") == "👀 Ready For Review"
    assert len(clean_bot_name("x" * 200)) == 80


def test_the_logo_comes_from_slack_icon_url(monkeypatch):
    monkeypatch.setenv("SLACK_ICON_URL", "https://app.youragency.com/slack-logo.png")
    p = message_payload("CHAN", "Ready For Review", "hi")
    assert p["icon_url"] == "https://app.youragency.com/slack-logo.png"
    assert p["username"] == "Ready For Review"
    assert p["unfurl_links"] is False and p["unfurl_media"] is False


def test_no_logo_set_means_the_app_icon(monkeypatch):
    monkeypatch.delenv("SLACK_ICON_URL", raising=False)
    assert "icon_url" not in message_payload("CHAN", "Ready For Review", "hi")


class _Answer:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_email_lookup_goes_as_a_form_body(monkeypatch):
    """Slack answers invalid_arguments to users.lookupByEmail sent as JSON."""
    sent = []

    def fake_urlopen(req, timeout=0):
        sent.append(req)
        return _Answer(b'{"ok": true, "user": {"id": "U1"}}')

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(slack_notify.urllib.request, "urlopen", fake_urlopen)
    assert slack_notify.call("users.lookupByEmail", {"email": "a+b@example.com"})["user"]["id"] == "U1"
    req = sent[0]
    assert req.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert req.data == b"email=a%2Bb%40example.com"


def test_channel_list_keeps_its_types_and_cursor_as_a_form():
    data, kind = slack_notify.request_body(
        "conversations.list", {"types": "public_channel,private_channel", "exclude_archived": True, "cursor": "c2"}
    )
    assert kind == "application/x-www-form-urlencoded"
    assert data == b"types=public_channel%2Cprivate_channel&exclude_archived=true&cursor=c2"


def test_posts_and_other_writes_stay_json():
    for method in ("chat.postMessage", "conversations.open", "conversations.invite", "conversations.create"):
        data, kind = slack_notify.request_body(method, {"channel": "C1", "blocks": [{"type": "divider"}]})
        assert kind.startswith("application/json")
        assert data.startswith(b"{")
