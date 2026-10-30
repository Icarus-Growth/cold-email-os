"""A new team member gets their sign-in details as a Slack direct message.

The OS calls this after "Add team member" or "Resend access" (the OS's server step
holds the shared secret). The body is {"team_id": "<row id>", "temp_password": "...",
"resend": false}. The password is sent in the message only. It is never saved or logged.

If the person has no Slack id yet, it is looked up by their email and saved on their
team row. The answer says whether the message was sent, so the OS can tell the owner.
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping, Optional

from common import Config, os_base, read_settings, report_failure, section

INVITE_BOT = "🔑 Your OS Access"


def invite_text(person: Dict[str, Any], settings: Dict[str, Any], temp_password: str, resend: bool) -> str:
    """The direct message. Pure."""
    first = (person.get("full_name") or "").split(" ")[0] or "there"
    agency = settings.get("agency_name") or "the agency"
    url = os_base(settings)
    lines = [
        "Hi {0}, {1} access to the {2} OS.".format(first, "here is new" if resend else "you now have", agency),
        "*Address:* <{0}|Open the OS>".format(url) if url else "*Address:* ask the person who added you",
        "*Email:* {0}".format(person.get("email")),
        "*Temporary password:* `{0}`".format(temp_password),
        "Sign in, then choose your own password. The OS asks you to do this first.",
    ]
    return "\n".join(lines)


def handle_team_invite(
    db: Any, slack: Any, config: Config, seen: Optional[MutableMapping[str, Any]], body: Dict[str, Any]
) -> Dict[str, Any]:
    """Send the sign-in message. Never raises, and never echoes the password back."""
    team_id = body.get("team_id") or ""
    password = body.get("temp_password") or ""
    if not team_id or not password:
        return {"sent": False, "reason": "team_id and temp_password are both needed"}
    step = "Read the team member"
    try:
        settings = read_settings(db)
        person = db.get("team", team_id, columns="id,full_name,email,slack_user_id")
        if not person:
            return {"sent": False, "reason": "No team member with that id"}
        slack_id = (person.get("slack_user_id") or "").strip()
        if not slack_id:
            step = "Find them in Slack by email"
            try:
                found = slack.call("users.lookupByEmail", {"email": person["email"]})
            except Exception as e:  # noqa: BLE001
                if getattr(e, "code", "") == "users_not_found":
                    return {"sent": False, "reason": "No Slack account uses {0}".format(person["email"])}
                raise
            slack_id = found["user"]["id"]
            db.update("team", team_id, {"slack_user_id": slack_id})
        step = "Open the direct message"
        dm = slack.call("conversations.open", {"users": slack_id})["channel"]["id"]
        step = "Send the direct message"
        text = invite_text(person, settings, password, bool(body.get("resend")))
        slack.post(dm, INVITE_BOT, text, blocks=[section(text)])
        return {"sent": True}
    except Exception as e:  # noqa: BLE001
        report_failure(
            slack,
            config,
            seen,
            "Team member access message",
            step,
            e,
            "",
            "The new person did not get their sign-in message in Slack. The owner saw it once in the OS: send it to them another way, or press Resend access.",
        )
        return {"sent": False, "reason": "The Slack message could not be sent. It is posted in pipeline-errors."}
