"""The daily summary: one post in daily-summary on weekdays.

The Modal app runs `run_daily_summary` every hour. It posts only when the hour in the
agency's time zone is `settings.daily_summary_hour` on a weekday (Monday to Friday),
so a change in the settings table takes effect the next day with no new deploy.
Run it by hand with `modal run apps/os/automations/app.py::summary_now`.

The post (CANN, main message plus thread):
  * main message: counts only, and an "Open My Work" button (the OS home page);
  * thread reply 1, what changed since the last summary (the weekday before, same hour);
  * thread reply 2, the "act today" list, grouped by person: due within 24 hours or
    late, stuck (no move for settings.stuck_after_days days), waiting for review;
  * thread reply 3, the clients that need attention.
Each person is tagged once in the whole summary. After that only their name is written.
Archived clients and archived cards (archived_at is set) are left out of every part.

Then, in the same run (no new schedule), each team member with open work gets one Slack direct
message: their own open cards, late first, then due today, then waiting for their review, then
the rest, each with a link. Nobody with no open cards gets a message, and nobody gets two on one
day (a run by hand after the scheduled one sends none again). A live card (is_live: a campaign
that is running, a post that is scheduled) is never called late or stuck.
Slack permissions it uses (already in the manifest): chat:write, im:write (open the direct
message), users:read.email (find a person with no Slack id yet by their email).

Every read goes in pages of at most 500 rows and stops after 20 pages.
"""

from __future__ import annotations

import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, MutableMapping, Optional, Tuple

from common import (
    Config,
    People,
    button,
    card_link,
    client_link,
    first_time,
    os_base,
    read_settings,
    report_failure,
    section,
    stage_number,
)

SUMMARY_BOT = "☀️ Daily Summary"
TASKS_BOT = "📋 Your Work Today"
MAX_LINES = 30
DM_LINES = 15


def zone(settings: Dict[str, Any]) -> Any:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(settings.get("time_zone") or "UTC")
    except Exception:  # noqa: BLE001 - an unknown zone falls back to UTC
        return timezone.utc


def is_summary_hour(now_local: datetime, hour: int) -> bool:
    return now_local.weekday() < 5 and now_local.hour == hour


def previous_slot(t_local: datetime, hour: int) -> datetime:
    """The latest weekday at `hour`:00 that is not after `t_local`."""
    slot = t_local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot > t_local:
        slot -= timedelta(days=1)
    while slot.weekday() >= 5:
        slot -= timedelta(days=1)
    return slot


def since_for(now_local: datetime, hour: int, scheduled: bool) -> datetime:
    """Where "what changed" starts. A scheduled run looks back to the slot before its
    own; a run by hand looks back to the last summary that went out."""
    return previous_slot(now_local - timedelta(hours=1) if scheduled else now_local, hour)


def esc(text: Any) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_day(value: Any) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(value)[:10]).date() if value else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- reading


def collect(db: Any, since_utc: datetime, config: Config) -> Dict[str, List[Dict[str, Any]]]:
    """Everything the summary needs, read in pages of at most 500 rows."""
    archived = []
    for board in config.boards:
        for row in db.select_all(board, {"archived_at": "not.is.null"}, columns="id"):
            archived.append({"board": board, "id": row["id"]})
    return {
        "moves": db.select_all("stage_log", {"changed_at": "gt." + since_utc.isoformat()}, order="id"),
        "open": db.select_all("v_open_cards", order="card_id"),
        "attention": db.select_all("v_clients_attention", {"needs_attention": "eq.true"}, order="client_id"),
        "clients": db.select_all("clients", columns="id,client_name,account_manager_id,archived_at", order="id"),
        "archived_cards": archived,
    }


def without_archived(data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    """The same lists with every archived client and archived card taken out. Pure.
    (The dashboard views leave them out too; this is the second check.)"""
    gone_clients = {c["id"] for c in data.get("clients", []) if c.get("archived_at")}
    gone_cards = {(a["board"], a["id"]) for a in data.get("archived_cards", [])}
    return dict(
        data,
        moves=[
            m
            for m in data.get("moves", [])
            if m.get("client_id") not in gone_clients and (m.get("board"), m.get("record_id")) not in gone_cards
        ],
        open=[
            c
            for c in data.get("open", [])
            if c.get("client_id") not in gone_clients and (c.get("board"), c.get("card_id")) not in gone_cards
        ],
        attention=[a for a in data.get("attention", []) if a.get("client_id") not in gone_clients],
        clients=[c for c in data.get("clients", []) if c["id"] not in gone_clients],
    )


# --------------------------------------------------------------------------- building


def act_today(
    open_cards: List[Dict[str, Any]], settings: Dict[str, Any], config: Config, now_utc: datetime, today: date
) -> List[Dict[str, Any]]:
    """Open cards to act on today, each with its reasons and the person who must act."""
    stuck_days = int(settings.get("stuck_after_days") or 3)
    review = config.review_stages()
    out = []
    for card in open_cards:
        reasons = []
        if card.get("is_live"):
            # A running campaign or a scheduled post is not late or stuck (the views leave it out too).
            waiting = card.get("stage") in review.get(card.get("board"), [])
            if waiting:
                out.append(dict(card, reasons=["waiting for review"], person=card.get("reviewer_id")
                                or card.get("assignee_id"), waiting=True, late_or_due=False))  # fmt: skip
            continue
        due = parse_day(card.get("due_date"))
        if due and due < today:
            reasons.append("late {0} day{1}".format((today - due).days, "" if (today - due).days == 1 else "s"))
        elif due and due <= today + timedelta(days=1):
            reasons.append("due today" if due == today else "due tomorrow")
        moved = parse_time(card.get("stage_changed_at"))
        if moved and moved < now_utc - timedelta(days=stuck_days):
            reasons.append("stuck {0} days".format((now_utc - moved).days))
        waiting = card.get("stage") in review.get(card.get("board"), [])
        if waiting:
            reasons.append("waiting for review")
        if not reasons:
            continue
        person = card.get("reviewer_id") if waiting and card.get("reviewer_id") else card.get("assignee_id")
        out.append(
            dict(
                card,
                reasons=reasons,
                person=person,
                waiting=waiting,
                late_or_due=bool(due and due <= today + timedelta(days=1)),
            )
        )
    return out


def summarise_moves(moves: List[Dict[str, Any]], config: Config) -> Dict[str, Any]:
    finals = {b: set(v.get("final", [])) for b, v in config.boards.items()}
    counts = {"moved": 0, "new": 0, "finished": 0, "sent_back": 0}
    lines = []
    for m in moves:
        board = m.get("board")
        if board not in config.boards:
            continue
        if not m.get("from_stage"):
            counts["new"] += 1
            change = "new card at {0}".format(m.get("to_stage"))
        else:
            counts["moved"] += 1
            change = "{0} → {1}".format(m.get("from_stage"), m.get("to_stage"))
        if m.get("to_stage") in finals.get(board, set()):
            counts["finished"] += 1
        num = stage_number(m.get("to_stage"))
        if m.get("from_stage") and num is not None and num > 9 and num % 10 == 9:
            counts["sent_back"] += 1
        lines.append(
            "• {0} ({1}): {2}".format(esc(m.get("record_name") or "A card"), config.board_label(board), change)
        )
    return {"counts": counts, "lines": lines}


def capped(lines: List[str], more_url: str) -> List[str]:
    if len(lines) <= MAX_LINES:
        return lines
    extra = len(lines) - MAX_LINES
    tail = "…and {0} more.".format(extra)
    if more_url:
        tail += " <{0}|Open the OS>".format(more_url)
    return lines[:MAX_LINES] + [tail]


def build_summary(
    data: Dict[str, List[Dict[str, Any]]],
    people: People,
    settings: Dict[str, Any],
    config: Config,
    now_utc: datetime,
    today: date,
) -> Dict[str, Any]:
    """The main message and the thread replies. Pure."""
    base = os_base(settings)
    data = without_archived(data)
    clients = {c["id"]: c for c in data.get("clients", [])}
    moves = summarise_moves(data.get("moves", []), config)
    todo = act_today(data.get("open", []), settings, config, now_utc, today)
    attention = data.get("attention", [])
    c = moves["counts"]

    head = "*Daily summary, {0} {1} {2} {3}*".format(today.strftime("%a"), today.strftime("%b"), today.day, today.year)
    lines = [
        head,
        "*Since the last summary:* {0} moved, {1} new, {2} finished, {3} sent back.".format(
            c["moved"], c["new"], c["finished"], c["sent_back"]
        ),
        "*Act today:* {0} cards ({1} due or late, {2} stuck, {3} waiting for review).".format(
            len(todo),
            sum(1 for t in todo if t["late_or_due"]),
            sum(1 for t in todo if any(r.startswith("stuck") for r in t["reasons"])),
            sum(1 for t in todo if t["waiting"]),
        ),
        "*Clients that need attention:* {0}.".format(len(attention)),
    ]
    replies: List[str] = []
    if moves["lines"]:
        replies.append("\n".join(["*What changed since the last summary*"] + capped(moves["lines"], base)))

    if todo:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for t in todo:
            groups.setdefault(t.get("person") or "", []).append(t)
        order = sorted(groups, key=lambda pid: (pid == "", people.name(pid)))
        out = ["*Act today*"]
        for pid in order:
            who = people.tag(pid) if pid else "Nobody set"
            out.append("")
            out.append(who or "Someone who is no longer on the team")
            for t in groups[pid]:
                if config.boards.get(t["board"], {}).get("link") == "client" and t.get("client_id"):
                    link = client_link(settings, t["client_id"])
                else:
                    link = card_link(settings, t["board"], t["card_id"])
                name = esc(t.get("card_name") or "A card")
                label = "<{0}|{1}>".format(link, name) if link else name
                client = esc((clients.get(t.get("client_id")) or {}).get("client_name") or "")
                where = (
                    "{0}, {1}".format(t.get("board_label") or config.board_label(t["board"]), client)
                    if client
                    else (t.get("board_label") or "")
                )
                out.append("• {0} ({1}): {2}".format(label, where, ", ".join(t["reasons"])))
        replies.append("\n".join(capped(out, base)))

    if attention:
        out = ["*Clients that need attention*"]
        for a in attention:
            reasons = []
            if a.get("late_cards"):
                reasons.append("{0} late".format(a["late_cards"]))
            if a.get("stuck_cards"):
                reasons.append("{0} stuck".format(a["stuck_cards"]))
            if a.get("onboarding_stuck"):
                reasons.append("onboarding has not moved")
            link = client_link(settings, a["client_id"])
            name = esc(a.get("client_name"))
            label = "<{0}|{1}>".format(link, name) if link else name
            who = people.tag(a.get("account_manager_id")) if a.get("account_manager_id") else "no account manager"
            out.append("• {0}: {1}. {2}".format(label, ", ".join(reasons) or "check the client", who))
        replies.append("\n".join(capped(out, base)))

    if replies:
        lines.append("Check the thread for the lists and who does what.")
    else:
        lines.append("Nothing to act on today.")
    text = "\n".join(lines)
    blocks = [section(text)]
    if base:
        blocks.append(button("Open My Work", base + "/"))
    return {"text": text, "blocks": blocks, "replies": replies}


# --------------------------------------------------------------------------- each person's own work


def card_url(card: Dict[str, Any], settings: Dict[str, Any], config: Config) -> str:
    if config.boards.get(card.get("board"), {}).get("link") == "client" and card.get("client_id"):
        return client_link(settings, card["client_id"])
    return card_link(settings, card.get("board"), card.get("card_id") or "")


def pending_by_person(
    open_cards: List[Dict[str, Any]],
    config: Config,
    today: date,
    now_utc: Optional[datetime] = None,
    stuck_days: int = 3,
) -> Dict[str, List[Tuple[Tuple[int, Any], Dict[str, Any], str]]]:
    """{team id: [(sort key, card, why)]}: each person's own open cards (as the maker), and the
    cards waiting for their review. Late first, then due today, then waiting for review, then due
    tomorrow, then stuck (no move for stuck_days), then the rest by due date. Pure."""
    review = config.review_stages()
    out: Dict[str, List[Tuple[Tuple[int, Any], Dict[str, Any], str]]] = {}
    for card in open_cards:
        due = parse_day(card.get("due_date"))
        live = bool(card.get("is_live"))
        waiting = card.get("stage") in review.get(card.get("board"), [])
        people = []
        if card.get("assignee_id") and not (waiting and card.get("reviewer_id")):
            people.append(card["assignee_id"])
        if waiting and card.get("reviewer_id"):
            people.append(card["reviewer_id"])
        for pid in dict.fromkeys(people):
            if waiting and pid == card.get("reviewer_id"):
                key, why = (2, ""), "waiting for your review"
            elif due and due < today and not live:
                days = (today - due).days
                key, why = (0, due.isoformat()), "late {0} day{1}".format(days, "" if days == 1 else "s")
            elif due and due == today and not live:
                key, why = (1, ""), "due today"
            elif due and due == today + timedelta(days=1):
                key, why = (3, ""), "due tomorrow"
            elif not live and stuck_for(card, now_utc) >= stuck_days:
                key, why = (4, -stuck_for(card, now_utc)), "no move for {0} days".format(stuck_for(card, now_utc))
            else:
                key, why = (5, due.isoformat() if due else "9999"), ("live" if live else "")
            out.setdefault(pid, []).append((key, card, why))
    for items in out.values():
        items.sort(key=lambda t: (t[0], str(t[1].get("card_name") or "")))
    return out


def stuck_for(card: Dict[str, Any], now_utc: Optional[datetime]) -> int:
    moved = parse_time(card.get("stage_changed_at"))
    return (now_utc - moved).days if moved and now_utc else 0


def pending_message(
    person: Dict[str, Any],
    items: List[Tuple[Tuple[int, Any], Dict[str, Any], str]],
    clients: Dict[str, Dict[str, Any]],
    settings: Dict[str, Any],
    config: Config,
    today: date,
) -> Dict[str, Any]:
    """One person's direct message: what is on their plate today, each card with a link. Pure."""
    base = os_base(settings)
    first = (person.get("full_name") or "").split(" ")[0] or "there"
    late = sum(1 for k, _, _ in items if k[0] == 0)
    due = sum(1 for k, _, _ in items if k[0] == 1)
    review = sum(1 for k, _, _ in items if k[0] == 2)
    head = "*Your work, {0} {1} {2}*".format(today.strftime("%a"), today.strftime("%b"), today.day)
    counts = "Hi {0}. You have {1} open card{2}: {3} late, {4} due today, {5} waiting for your review.".format(
        first, len(items), "" if len(items) == 1 else "s", late, due, review
    )
    todo = "Start with the first one." if (late or due or review) else "Nothing is late or due today."
    lines = [head, counts, todo]
    for _, card, why in items[:DM_LINES]:
        name = esc(card.get("card_name") or "A card")
        link = card_url(card, settings, config)
        label = "<{0}|{1}>".format(link, name) if link else name
        client = esc((clients.get(card.get("client_id")) or {}).get("client_name") or "")
        where = card.get("board_label") or config.board_label(card.get("board"))
        where = "{0}, {1}".format(where, client) if client else where
        lines.append("• {0} ({1}){2}".format(label, where, ": " + why if why else ""))
    if len(items) > DM_LINES:
        lines.append("…and {0} more on My Work.".format(len(items) - DM_LINES))
    text = "\n".join(lines)
    blocks = [section(text)]
    if base:
        blocks.append(button("Open My Work", base + "/"))
    return {"text": text, "blocks": blocks}


def send_pending_tasks(
    db: Any,
    slack: Any,
    config: Config,
    seen: Optional[MutableMapping[str, Any]],
    data: Dict[str, List[Dict[str, Any]]],
    settings: Dict[str, Any],
    today: date,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """One direct message per team member with open cards. Never raises: a person who cannot be
    reached is counted, and one message in pipeline-errors names them all."""
    data = without_archived(data)
    clients = {c["id"]: c for c in data.get("clients", [])}
    team = {
        r["id"]: r
        for r in db.select_all("team", {"status": "eq.Active"}, columns="id,full_name,email,status,slack_user_id")
    }
    sent, skipped, failed = [], [], []
    stuck_days = int(settings.get("stuck_after_days") or 3)
    by_person = pending_by_person(
        data.get("open", []), config, today, now_utc or datetime.now(timezone.utc), stuck_days
    )
    for pid, items in sorted(by_person.items()):
        person = team.get(pid)
        if not person or not items:
            continue  # not on the active team any more
        if not first_time(seen, "pending-dm:{0}:{1}".format(pid, today.isoformat()), hours=20):
            skipped.append(person.get("full_name"))
            continue
        try:
            slack_id = (person.get("slack_user_id") or "").strip()
            if not slack_id and person.get("email"):
                try:
                    slack_id = slack.call("users.lookupByEmail", {"email": person["email"]})["user"]["id"]
                    db.update("team", pid, {"slack_user_id": slack_id})
                except Exception as e:  # noqa: BLE001
                    if getattr(e, "code", "") != "users_not_found":
                        raise
                    slack_id = ""
            if not slack_id:
                failed.append("{0} (no Slack account uses {1})".format(person.get("full_name"), person.get("email")))
                continue
            dm = slack.call("conversations.open", {"users": slack_id})["channel"]["id"]
            msg = pending_message(person, items, clients, settings, config, today)
            slack.post(dm, TASKS_BOT, msg["text"], blocks=msg["blocks"])
            sent.append(person.get("full_name"))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            failed.append("{0} ({1})".format(person.get("full_name"), getattr(e, "code", "") or e))
    if failed:
        report_failure(
            slack,
            config,
            seen,
            "Morning tasks message",
            "Send each person their open cards",
            RuntimeError("not sent to: " + "; ".join(failed)),
            os_base(settings),
            "These people did not get their morning list. Link them in Slack (tab 3 Step 5), or they open My Work.",
        )
    return {"sent": len(sent), "already_sent_today": len(skipped), "not_sent": failed}


# --------------------------------------------------------------------------- running


def run_daily_summary(
    db: Any,
    slack: Any,
    config: Config,
    seen: Optional[MutableMapping[str, Any]],
    scheduled: bool = True,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Post the summary if it is time (or always, when run by hand). Never raises."""
    now_utc = now_utc or datetime.now(timezone.utc)
    settings: Dict[str, Any] = {}
    try:
        settings = read_settings(db)
        hour = int(settings.get("daily_summary_hour") if settings.get("daily_summary_hour") is not None else 8)
        now_local = now_utc.astimezone(zone(settings))
        if scheduled and not is_summary_hour(now_local, hour):
            return {"posted": False, "reason": "not the summary hour"}
        channel = config.channel_id("daily-summary")
        if not channel:
            raise RuntimeError("The daily-summary channel is not set up in channels.json")
        since = since_for(now_local, hour, scheduled).astimezone(timezone.utc)
        data = collect(db, since, config)
        summary = build_summary(data, People.load(db), settings, config, now_utc, now_local.date())
        ts = slack.post(channel, SUMMARY_BOT, summary["text"], blocks=summary["blocks"])
        for reply in summary["replies"]:
            slack.post(channel, SUMMARY_BOT, reply, thread_ts=ts)
        out = {"posted": True, "ts": ts, "since": since.isoformat(), "replies": len(summary["replies"])}
        try:
            out["direct_messages"] = send_pending_tasks(
                db, slack, config, seen, data, settings, now_local.date(), now_utc
            )
        except Exception as e:  # noqa: BLE001 - the summary is already out; the messages fail on their own
            report_failure(slack, config, seen, "Morning tasks message", "Read each person's cards", e, os_base(settings))
            out["direct_messages"] = {"sent": 0, "error": str(e)}
        try:
            # Skills whose SKILL.md says `daily: true` run here, once a day (no new scheduled job).
            from skills_runner import run_daily_skills

            out["daily_skills"] = run_daily_skills(db, slack, config, seen, now_local.date())
        except Exception as e:  # noqa: BLE001 - one bad skill never stops the summary
            report_failure(slack, config, seen, "Daily skills", "Start the daily skills", e, os_base(settings))
            out["daily_skills"] = {"error": str(e)}
        return out
    except Exception as e:  # noqa: BLE001
        report_failure(
            slack,
            config,
            seen,
            "Daily summary",
            "Build and post the summary",
            e,
            os_base(settings),
            "Today's summary was not posted. Open My Work in the OS to see what needs doing.",
        )
        return {"posted": False, "reason": str(e)}


def slots_between(start: datetime, end: datetime, hour: int) -> List[Tuple[datetime, datetime]]:
    """(slot, since) pairs between two times. Used by the tests to check no change is
    left out between two summaries."""
    out = []
    t = start
    while t <= end:
        if is_summary_hour(t, hour) and t.minute == 0:
            out.append((t, since_for(t, hour, True)))
        t += timedelta(hours=1)
    return out
