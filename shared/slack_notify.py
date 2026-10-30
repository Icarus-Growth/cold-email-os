"""
The one way this OS posts to Slack.

House rules, kept here so no caller has to remember them:

1. **Every message carries the agency's logo.** `icon_url` defaults to the address in
   `SLACK_ICON_URL` (the logo saved in the OS app, set up in tab 3). With no address set,
   Slack shows the Slack app's own icon.
2. **Every message names itself.** `bot_name` has no default. The sender name describes
   THAT message ("Ready For Review", "Needs Amendments", "Automation Failed"), never a
   generic app name. Slack drops a missing name without an error, so this module makes
   a missing name an error instead.
3. **Every line is followed by a blank line.** `spaced()` does it to `text` and to every
   section block's text. Code blocks and lines already apart are left alone.
4. **Every bare link reads as [LINK].** `linked()` turns a naked URL (or a label-less
   `<URL>`) into `<URL|[LINK]>`, so messages read clean. Links that already carry a
   label, and anything inside code, are left alone.

The name and the icon need the `chat:write.customize` scope. Without it Slack silently
ignores `username` and `icon_url`, so `preflight()` checks for the scope.

    from shared.slack_notify import post_message

    post_message(
        channel="<channel id>",
        bot_name="Ready For Review",
        text="*Card:* Welcome email\\n<@USER> please check it",
    )

Standard library only, Python 3.9. Imported by the Modal app and by local scripts alike.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

SLACK_API = "https://slack.com/api/"

# Slack truncates the displayed username around 80 characters.
MAX_BOT_NAME = 80


def default_icon_url() -> str:
    """The logo address from SLACK_ICON_URL, or "" when none is set. Read at call time,
    so a changed secret takes effect without a code change."""
    return (os.environ.get("SLACK_ICON_URL") or "").strip()


def spaced(text: str) -> str:
    """Put one blank line between every two lines of text. Lines already apart stay
    as they are, and nothing inside a ``` code block changes. Pure."""
    if not text or "\n" not in text:
        return text
    lines = text.split("\n")
    out: List[str] = []
    in_code = False
    for i, line in enumerate(lines):
        out.append(line)
        if line.count("```") % 2:
            in_code = not in_code
        if not in_code and i + 1 < len(lines) and line.strip() and lines[i + 1].strip():
            out.append("")
    return "\n".join(out)


def spaced_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The same rule for the text of section blocks. Returns new dicts. Pure."""
    out = []
    for block in blocks:
        text = block.get("text") if isinstance(block, dict) else None
        if isinstance(text, dict) and isinstance(text.get("text"), str):
            body = spaced(text["text"])
            if text.get("type") == "mrkdwn":
                body = linked(body)
            block = dict(block, text=dict(text, text=body))
        out.append(block)
    return out


_URL = re.compile(r"<(https?://[^|>\s]+)>|(?<![<|])(https?://[^\s<>|]+)")
_TRAILING = ".,;:!?'\""


def _link_one(url: str) -> Tuple[str, str]:
    """Split trailing sentence punctuation (and an unbalanced ')') off a URL."""
    tail = ""
    while url and (url[-1] in _TRAILING or (url[-1] == ")" and url.count("(") < url.count(")"))):
        tail = url[-1] + tail
        url = url[:-1]
    return url, tail


def linked(text: str) -> str:
    """Turn every bare link into ``<URL|[LINK]>``. Labelled links and code stay as they are. Pure."""
    if not text or "http" not in text:
        return text
    parts = re.split(r"(```.*?```|`[^`\n]*`)", text, flags=re.S)
    for i in range(0, len(parts), 2):

        def sub(m: Any) -> str:
            raw = m.group(1) or m.group(2)
            url, tail = _link_one(raw) if m.group(2) else (raw, "")
            return "<{0}|[LINK]>{1}".format(url, tail) if url else m.group(0)

        parts[i] = _URL.sub(sub, parts[i])
    return "".join(parts)


class SlackError(RuntimeError):
    """Slack returned ok:false, or no token was available."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


def _token(token: Optional[str] = None) -> str:
    tok = (token or os.environ.get("SLACK_BOT_TOKEN") or "").strip()
    if not tok:
        raise SlackError("No SLACK_BOT_TOKEN in the environment", "no_token")
    return tok


# Slack's read methods do not read a JSON body. users.lookupByEmail answers
# invalid_arguments, and conversations.list drops "types" and "cursor" without an
# error. These go as a form body; every other method goes as JSON.
FORM_METHODS = frozenset(
    {
        "users.lookupByEmail",
        "users.info",
        "users.list",
        "users.conversations",
        "conversations.list",
        "conversations.info",
        "conversations.members",
        "conversations.history",
        "conversations.replies",
        "team.info",
    }
)


def _form_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def request_body(method: str, payload: Dict[str, Any]) -> Tuple[bytes, str]:
    """The body and its Content-Type for one method: a form for Slack's read methods,
    JSON for the rest. Pure."""
    if method in FORM_METHODS:
        form = {k: _form_value(v) for k, v in payload.items() if v is not None}
        return urllib.parse.urlencode(form).encode("utf-8"), "application/x-www-form-urlencoded"
    return json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8"


def call(method: str, payload: Dict[str, Any], token: Optional[str] = None, timeout: int = 30) -> Dict[str, Any]:
    """Call one Slack Web API method. Raises SlackError (with `.code`) when Slack says no."""
    data, content_type = request_body(method, payload)
    req = urllib.request.Request(
        SLACK_API + method,
        method="POST",
        data=data,
        headers={"Authorization": "Bearer " + _token(token), "Content-Type": content_type},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("ok"):
        code = body.get("error", "unknown")
        raise SlackError("{0} failed: {1}".format(method, code), code)
    return body


def clean_bot_name(bot_name: str) -> str:
    """A bot name is required and must say something. Empty, whitespace, or a generic
    app name are all rejected: those are the failure this module exists to prevent."""
    name = (bot_name or "").strip()
    if not name:
        raise SlackError(
            "bot_name is required. Name the message after what just happened "
            "('Ready For Review', 'Automation Failed'), not after the app."
        )
    if name.lower() in ("bot", "app", "os", "automation", "automations", "slack bot"):
        raise SlackError(
            "bot_name {0!r} is a generic name, not a description of this message. "
            "Use something that tells the team what happened at a glance.".format(name)
        )
    return name[:MAX_BOT_NAME]


def message_payload(
    channel: str,
    bot_name: str,
    text: str,
    blocks: Optional[List[Dict[str, Any]]] = None,
    thread_ts: Optional[str] = None,
    icon_url: Optional[str] = None,
    unfurl_links: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """The chat.postMessage body, with every house rule applied. Pure apart from reading
    SLACK_ICON_URL."""
    payload: Dict[str, Any] = {
        "channel": channel,
        "text": linked(spaced(text)),
        "username": clean_bot_name(bot_name),
        "unfurl_links": unfurl_links,
        "unfurl_media": unfurl_links,
    }
    icon = icon_url or default_icon_url()
    if icon:
        payload["icon_url"] = icon
    if blocks:
        payload["blocks"] = spaced_blocks(blocks)
    if thread_ts:
        payload["thread_ts"] = thread_ts
    payload.update(extra)
    return payload


def post_message(
    channel: str,
    bot_name: str,
    text: str,
    blocks: Optional[List[Dict[str, Any]]] = None,
    thread_ts: Optional[str] = None,
    icon_url: Optional[str] = None,
    unfurl_links: bool = False,
    token: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Post one message. `bot_name` is required on purpose.

    Returns the Slack response (carries `ts`, used to thread replies).
    """
    payload = message_payload(channel, bot_name, text, blocks, thread_ts, icon_url, unfurl_links, **extra)
    return call("chat.postMessage", payload, token=token)


def post_thread_reply(channel: str, bot_name: str, text: str, thread_ts: str, **kwargs: Any) -> Dict[str, Any]:
    """A reply is still a message, so it still names itself and still wears the logo."""
    return post_message(channel, bot_name, text, thread_ts=thread_ts, **kwargs)


def preflight(token: Optional[str] = None) -> Dict[str, Any]:
    """Confirm the token works and can set the name and icon of each message.

    Slack does NOT error when `chat:write.customize` is missing: it posts under the
    app's own name and drops the icon. So this reads the granted scopes directly.
    """
    req = urllib.request.Request(
        SLACK_API + "auth.test",
        method="POST",
        data=b"{}",
        headers={"Authorization": "Bearer " + _token(token), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        scopes = [s.strip() for s in (resp.headers.get("x-oauth-scopes") or "").split(",") if s.strip()]
        body = json.loads(resp.read().decode("utf-8"))
    return {
        "ok": bool(body.get("ok")),
        "error": body.get("error"),
        "bot": body.get("user"),
        "workspace": body.get("team"),
        "scopes": scopes,
        "can_customize": "chat:write.customize" in scopes,
        "icon_url": default_icon_url(),
    }


if __name__ == "__main__":
    import pprint

    pprint.pprint(preflight())
