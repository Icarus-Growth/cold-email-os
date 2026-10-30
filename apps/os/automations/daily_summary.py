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

Every read goes in pages of at most 500 rows and stops after 20 pages.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, MutableMapping, Optional, Tuple

from common import (
    Config,
    People,
    button,
    card_link,
    client_link,
    os_base,
    read_settings,
    report_failure,
    section,
    stage_number,
)

SUMMARY_BOT = "☀️ Daily Summary"
MAX_LINES = 30


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
        return {"posted": True, "ts": ts, "since": since.isoformat(), "replies": len(summary["replies"])}
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
