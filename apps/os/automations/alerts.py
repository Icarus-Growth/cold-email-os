"""Stage alerts: which stage move posts where, and what the post says.

One rule list for every board lives in `alert_rules.json`. A stage log row (one card
added or moved) is matched against the rules in order; the first rule that matches
decides the channel, the bot name and emoji, who is tagged and what they must do.
No match: nothing is posted.

A rule:

    {"board": "*" or a table name,
     "when": "new"                      a card was just added (no "from" stage), or
     "to": ["39 - Redo Requested"],     the card moved into one of these stages
     "channel": "amendments",           a key in channels.json
     "bot_name": "Needs Amendments", "emoji": "📷",
     "tag": ["assignee", "client.account_manager_id"],   the first one that is filled in
     "action": "Make the changes in the thread, then move the card on.",
     "thread": "feedback_notes"}        optional: this column goes in a thread reply

An archived card, or a card of an archived client, posts nothing.

Every post follows CANN: context (client, card, stage, due date), action (one
sentence), notification (one person tagged) and navigation (a button that opens the
card in the OS).
"""

from __future__ import annotations

from typing import Any, Dict, List, MutableMapping, Optional

from common import (
    Config,
    People,
    button,
    card_link,
    client_link,
    friendly_date,
    is_archived,
    needs_a_person,
    os_base,
    read_settings,
    report_failure,
    section,
)

NEW_FORM_BOT = "📋 Onboarding Form Received"


def record_link(config: Config, settings: Dict[str, Any], row: Dict[str, Any], client_id: Optional[str]) -> str:
    """The card's page in the OS. A list with no board ("link": "client") opens the client page."""
    if config.boards.get(row["board"], {}).get("link") == "client" and client_id:
        return client_link(settings, client_id)
    return card_link(settings, row["board"], row["record_id"])


def route(row: Dict[str, Any], config: Config) -> Optional[Dict[str, Any]]:
    """The first rule that matches this stage log row, or None."""
    board = row.get("board")
    if board not in config.boards:
        return None
    is_new = not row.get("from_stage")
    for rule in config.rules.get("rules", []):
        if rule.get("board") not in ("*", board):
            continue
        if rule.get("when") == "new" and is_new:
            return rule
        if not is_new and row.get("to_stage") in rule.get("to", []):
            return rule
    return None


def who_to_tag(rule: Dict[str, Any], card: Dict[str, Any], client: Dict[str, Any], people: People) -> Optional[str]:
    """The team id of the first person the rule names who is filled in."""
    for target in rule.get("tag", []):
        if target == "owner":
            owners = people.owners()
            value = owners[0] if owners else None
        elif target.startswith("client."):
            value = client.get(target.split(".", 1)[1])
        else:
            value = card.get(target if target.endswith("_id") else target + "_id")
        if value and value in people.by_id:
            return value
    return None


def build_post(
    rule: Dict[str, Any],
    row: Dict[str, Any],
    card: Dict[str, Any],
    client: Dict[str, Any],
    people: People,
    settings: Dict[str, Any],
    config: Config,
) -> Dict[str, Any]:
    """The message for one matched stage move. Pure: no Slack, no database."""
    board = row["board"]
    name = row.get("record_name") or card.get("name") or "A card"
    stage_line = (
        "*Stage:* {0} (new card)".format(row.get("to_stage"))
        if not row.get("from_stage")
        else "*Stage:* {0} → {1}".format(row.get("from_stage"), row.get("to_stage"))
    )
    mover = people.name(row.get("changed_by_id"))
    if mover:
        stage_line += ", moved by {0}".format(mover)

    thread_text = ""
    if rule.get("thread"):
        thread_text = (card.get(rule["thread"]) or "").strip()

    person = who_to_tag(rule, card, client, people)
    tag = people.tag(person) if person else ""
    action = rule.get("action", "Open the card and take the next step.")
    if thread_text:
        action += " Check the thread for the notes."
    action_line = "{0} {1}".format(tag, action) if tag else "Nobody is set to do this yet. " + action

    lines = []
    if client.get("client_name"):
        lines.append("*Client:* {0}".format(client["client_name"]))
    lines.append("*Card:* {0} ({1})".format(name, config.board_label(board)))
    lines.append(stage_line)
    if card.get("due_date"):
        lines.append("*Due:* {0}".format(friendly_date(card["due_date"])))
    lines.append(action_line)

    link = record_link(config, settings, row, card.get("client_id") or row.get("client_id"))
    text = "\n".join(lines)
    blocks = [section(text)]
    if link:
        blocks.append(button("Open the card", link))
    return {
        "channel": rule["channel"],
        "bot_name": "{0} {1}".format(rule.get("emoji", ""), rule["bot_name"]).strip(),
        "text": text,
        "blocks": blocks,
        "thread_text": thread_text,
        "link": link,
        "tagged": person,
    }


def handle_stage_change(
    db: Any, slack: Any, config: Config, seen: Optional[MutableMapping[str, Any]], row: Dict[str, Any]
) -> Dict[str, Any]:
    """Post the alert for one stage log row. Never raises: a failure is posted once in
    pipeline-errors instead."""
    rule = route(row, config)
    if not rule:
        return {"posted": False, "reason": "no rule for this move"}
    settings: Dict[str, Any] = {}
    link = ""
    try:
        settings = read_settings(db)
        link = record_link(config, settings, row, row.get("client_id"))
        card = db.get(row["board"], row["record_id"]) or {}
        client_id = card.get("client_id") or row.get("client_id")
        client = (db.get("clients", client_id) if client_id else None) or {}
        if is_archived(card) or is_archived(client):
            return {"posted": False, "reason": "archived"}
        people = People.load(db)
        post = build_post(rule, row, card, client, people, settings, config)
        channel = config.channel_id(post["channel"])
        if not channel:
            raise RuntimeError("The {0} channel is not set up in channels.json".format(post["channel"]))
        ts = slack.post(channel, post["bot_name"], post["text"], blocks=post["blocks"])
        if post["thread_text"]:
            slack.post(channel, post["bot_name"], post["thread_text"], thread_ts=ts)
        if not post["tagged"]:
            needs_a_person(
                slack,
                config,
                seen,
                "no-owner:{0}:{1}".format(row["board"], row["record_id"]),
                "*{0}* ({1}) is at *{2}*, but nobody is set to do it. Pick a person on the card.".format(
                    row.get("record_name") or "A card", config.board_label(row["board"]), row.get("to_stage")
                ),
                link,
                "Open the card",
            )
        return {"posted": True, "channel": post["channel"], "ts": ts}
    except Exception as e:  # noqa: BLE001 - every failure is reported, never raised
        report_failure(
            slack,
            config,
            seen,
            "Stage alert",
            "Post the {0} alert".format(rule.get("bot_name", "")),
            e,
            link,
            "The alert for this card was not posted, so nobody was told. Open the card and tell the right person yourself.",
        )
        return {"posted": False, "reason": str(e)}


def build_form_post(
    form: Dict[str, Any], client: Dict[str, Any], people: People, settings: Dict[str, Any]
) -> Dict[str, Any]:
    """The new-tasks post for one submitted onboarding form. Pure."""
    person = client.get("account_manager_id") if client.get("account_manager_id") in people.by_id else None
    if not person:
        owners = people.owners()
        person = owners[0] if owners else None
    tag = people.tag(person) if person else ""
    who = form.get("submitted_by_name") or "Someone"
    if form.get("submitted_by_email"):
        who += " ({0})".format(form["submitted_by_email"])
    lines = [
        "*Client:* {0}".format(client.get("client_name") or form.get("company_name") or "A new client"),
        "*Sent by:* {0}".format(who),
        "*Received:* {0}".format(friendly_date(form.get("submitted_at"))),
        "{0} Read the answers, then move the client's onboarding on.".format(tag).strip(),
    ]
    link = (
        client_link(settings, client["id"])
        if client.get("id")
        else (os_base(settings) + "/forms" if os_base(settings) else "")
    )
    text = "\n".join(lines)
    blocks = [section(text)]
    if link:
        blocks.append(button("Open the client" if client.get("id") else "Open the forms", link))
    return {"bot_name": NEW_FORM_BOT, "text": text, "blocks": blocks, "link": link}


def handle_form_submitted(
    db: Any, slack: Any, config: Config, seen: Optional[MutableMapping[str, Any]], form_id: str
) -> Dict[str, Any]:
    """Post one message in new-tasks when an onboarding form is submitted. Never raises."""
    try:
        settings = read_settings(db)
        form = db.get(
            "onboarding_forms",
            form_id,
            columns="id,client_id,company_name,submitted_by_name,submitted_by_email,submitted_at",
        )
        if not form:
            return {"posted": False, "reason": "form not found"}
        client = (db.get("clients", form["client_id"]) if form.get("client_id") else None) or {}
        if is_archived(client):
            return {"posted": False, "reason": "the client is archived"}
        post = build_form_post(form, client, People.load(db), settings)
        channel = config.channel_id("new-tasks")
        if not channel:
            raise RuntimeError("The new-tasks channel is not set up in channels.json")
        ts = slack.post(channel, post["bot_name"], post["text"], blocks=post["blocks"])
        return {"posted": True, "ts": ts}
    except Exception as e:  # noqa: BLE001
        report_failure(slack, config, seen, "Onboarding form alert", "Post in new-tasks", e)
        return {"posted": False, "reason": str(e)}


def unknown_stages(config: Config, ladders: Dict[str, List[str]]) -> List[str]:
    """Every rule stage that is not on its board's ladder (for the check and the tests)."""
    bad = []
    for rule in config.rules.get("rules", []):
        boards = list(config.boards) if rule.get("board") == "*" else [rule.get("board")]
        for board in boards:
            if board not in ladders:
                bad.append("{0}: board has no ladder".format(board))
                continue
            if rule.get("board") == "*":
                continue
            for stage in rule.get("to", []):
                if stage not in ladders[board]:
                    bad.append("{0}: {1}".format(board, stage))
    return bad
