"""A new client: one post in new-tasks. No Slack channel is made.

The client's own channel already exists in the agency's Slack. Tab 3 links it to the
client row (slack_setup.py link-clients), and the client page has a field for it. The
OS never makes a client channel and never posts in one.

When a client row is added (the database calls POST /new-client), this posts once in
new-tasks: the client, the account manager (tagged) or a note that there is none, the
onboarding form link to send, and a button that opens the client in the OS.
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping, Optional

from common import Config, People, button, client_link, form_link, is_archived, read_settings, report_failure, section

NEW_CLIENT_BOT = "🤝 New Client"


def build_new_client_post(client: Dict[str, Any], people: People, settings: Dict[str, Any]) -> Dict[str, Any]:
    """The new-tasks post for one new client. Pure: no Slack, no database."""
    manager = client.get("account_manager_id")
    lines = ["*Client:* {0}".format(client.get("client_name") or "A new client")]
    if client.get("onboarding_stage"):
        lines.append("*Onboarding:* {0}".format(client["onboarding_stage"]))
    form = form_link(settings, client)
    if form:
        lines.append("*Onboarding form:* <{0}|Send this link to the client>".format(form))
    if manager in people.by_id:
        lines.append("{0} Set up the client's onboarding.".format(people.tag(manager)))
    else:
        lines.append("Nobody is the account manager yet. Pick one on the client page.")
    if not (client.get("slack_channel_id") or "").strip():
        lines.append("_The client's Slack channel is not linked yet. Add its id on the client page._")
    text = "\n".join(lines)
    blocks = [section(text)]
    link = client_link(settings, client.get("id") or "")
    if link:
        blocks.append(button("Open the client", link))
    return {"bot_name": NEW_CLIENT_BOT, "text": text, "blocks": blocks, "link": link}


def handle_new_client(
    db: Any, slack: Any, config: Config, seen: Optional[MutableMapping[str, Any]], client_id: str
) -> Dict[str, Any]:
    """Post the new client in new-tasks. Never raises: a failure is posted in pipeline-errors."""
    settings: Dict[str, Any] = {}
    try:
        settings = read_settings(db)
        client = db.get("clients", client_id) if client_id else None
        if not client:
            return {"posted": False, "reason": "client not found"}
        if is_archived(client):
            return {"posted": False, "reason": "the client is archived"}
        channel = config.channel_id("new-tasks")
        if not channel:
            raise RuntimeError("The new-tasks channel is not set up in channels.json")
        post = build_new_client_post(client, People.load(db), settings)
        ts = slack.post(channel, post["bot_name"], post["text"], blocks=post["blocks"])
        return {"posted": True, "ts": ts}
    except Exception as e:  # noqa: BLE001 - every failure is reported, never raised
        report_failure(
            slack,
            config,
            seen,
            "New client alert",
            "Post in new-tasks",
            e,
            client_link(settings, client_id),
            "Nobody was told about this new client. Open it and give it an account manager.",
        )
        return {"posted": False, "reason": str(e)}
