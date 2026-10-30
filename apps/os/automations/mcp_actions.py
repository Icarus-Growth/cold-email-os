"""The AI connector's actions: what a person's AI may read and change in the OS.

The connector (mcp_server.py) shows the AI five fixed tools. Every ability is an action
in the registry built here, so a new ability is one entry and one function, and nobody's
AI set-up ever changes. Which actions this agency type has, and each board's columns and
stages, are in `mcp_actions.json` next to this file (one per agency type).

Each entry:

    kind         "read" or "write": which tool may run it, checked twice
    roles        the team access levels allowed to see AND run it
    description  what the AI is told in list_actions and describe_action
    schema       the parameters (checked before the function runs)
    handler      the function: handler(ctx, **params)

The rules every action keeps:
  * The AI acts as the person who owns the link. "Me" is their team row.
  * A Member can do what a Member can do in the app. "urgent" and "clients.update" are
    for Owners and Admins only.
  * Nothing is deleted. The team, keys and sign-in settings are not in the connector.
  * Archived clients and cards are left out of every list, and cannot be changed.
  * A read returns at most 100 rows, with "next_page" when there are more.
  * A card added or moved here writes the stage log, the same as in the app (the database
    does it), so the Slack alerts fire the same way.
  * Documents (docs.*) are the long texts on a card or a client page (copy, scripts, briefs),
    stored as Markdown. A write names the version it read; a newer save by someone else is a
    conflict, never an overwrite. Client page documents follow clients.update: Owners and Admins.
  * The second brain (brain.*) is read from the copy of second-brain/ that the deploy puts
    in the app. Only notes inside it can be read. inbox/ (not sorted) and raw/ (whole
    sources: transcripts, word for word) are never shipped or read: tab 4 keeps details
    about one lead or one person only in raw/, and every Member's AI can read the notes.

Standard library only, Python 3.9 syntax. `db` is anything with the
shared.supabase_client.Supabase methods.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from common import Config, card_link, client_link, is_archived, read_settings, stage_number

HERE = Path(__file__).resolve().parent
ACTIONS_FILE = HERE / "mcp_actions.json"
# The second brain: next to this file in the Modal app (/app/second-brain), at the repo
# root on a laptop.
BRAIN_DIRS = [HERE / "second-brain", HERE.parents[2] / "second-brain" if len(HERE.parents) > 2 else HERE]

PAGE = 100
EVERYONE = {"Owner", "Admin", "Member"}
ADMINS = {"Owner", "Admin"}
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
TEAM_COLUMNS = "id,full_name,email,job_title,access,status,capacity"


class ActionError(ValueError):
    """A plain sentence for the AI: what was wrong and what to do instead."""


# --------------------------------------------------------------------------- the context


class Context:
    """One call: the database, the caller's team row, the settings and the type's files."""

    def __init__(self, db: Any, me: Dict[str, Any], spec: Dict[str, Any], config: Config, today: Optional[date] = None):
        self.db = db
        self.me = me
        self.spec = spec
        self.config = config
        self.settings = read_settings(db)
        self._today = today
        self._team: Optional[List[Dict[str, Any]]] = None
        self._clients: Dict[str, Dict[str, Any]] = {}

    # ---- time

    @property
    def today(self) -> date:
        if self._today:
            return self._today
        try:
            from zoneinfo import ZoneInfo

            tz: Any = ZoneInfo(self.settings.get("time_zone") or "UTC")
        except Exception:  # noqa: BLE001 - an unknown zone falls back to UTC
            tz = timezone.utc
        return datetime.now(timezone.utc).astimezone(tz).date()

    # ---- boards

    @property
    def boards(self) -> Dict[str, Dict[str, Any]]:
        return self.spec.get("boards", {})

    def board(self, name: Any) -> Dict[str, Any]:
        key = str(name or "").strip()
        if key not in self.boards:
            for b in self.boards:  # "Tasks", "campaign calendars" ...
                if key.lower() in (b, b.replace("_", " "), self.config.board_label(b).lower()):
                    key = b
                    break
        if key not in self.boards:
            raise ActionError("No board called '{0}'. The boards are: {1}.".format(name, ", ".join(self.boards)))
        return dict(self.boards[key], key=key)

    def finals(self, board: str) -> List[str]:
        return self.config.boards.get(board, {}).get("final", [])

    def first_open(self, board: Dict[str, Any]) -> str:
        """The first stage that is not a finished one. On Tasks that is '0 - Backlog', not '-1 - Rejected'."""
        finals = self.finals(board["key"])
        return next((s for s in board["stages"] if s not in finals), board["stages"][0])

    def review(self, board: str) -> List[str]:
        return self.config.review_stages().get(board, [])

    def link(self, board: str, card: Dict[str, Any]) -> str:
        if self.config.boards.get(board, {}).get("link") == "client" and card.get("client_id"):
            return client_link(self.settings, card["client_id"])
        return card_link(self.settings, board, card.get("id") or card.get("card_id") or "")

    # ---- people

    @property
    def team(self) -> List[Dict[str, Any]]:
        if self._team is None:
            self._team = self.db.select_all("team", columns=TEAM_COLUMNS, order="full_name")
        return self._team

    def name(self, team_id: Any) -> Optional[str]:
        for t in self.team:
            if t["id"] == team_id:
                return t.get("full_name")
        return None

    def person(self, ref: Any) -> str:
        """'me', a team id, an email or a name -> the team id of one Active person."""
        text = str(ref or "").strip()
        if text.lower() in ("me", "myself", "i"):
            return self.me["id"]
        active = [t for t in self.team if t.get("status", "Active") == "Active"]
        for t in active:
            if text == t["id"] or text.lower() == (t.get("email") or "").lower():
                return t["id"]
        hits = [t for t in active if text.lower() == (t.get("full_name") or "").lower()]
        if not hits:
            hits = [t for t in active if text and text.lower() in (t.get("full_name") or "").lower()]
        if len(hits) == 1:
            return hits[0]["id"]
        if not hits:
            raise ActionError("Nobody on the active team matches '{0}'. Run 'team' to see the names.".format(ref))
        raise ActionError(
            "'{0}' matches {1}. Use the full name or the email.".format(
                ref, ", ".join(t.get("full_name") or "" for t in hits)
            )
        )

    # ---- clients

    def client_row(self, client_id: Any) -> Optional[Dict[str, Any]]:
        if not client_id:
            return None
        key = str(client_id)
        if key not in self._clients:
            self._clients[key] = self.db.get("clients", key) or {}
        return self._clients[key] or None

    def client_name(self, client_id: Any) -> Optional[str]:
        return (self.client_row(client_id) or {}).get("client_name")

    def client(self, ref: Any, allow_archived: bool = False) -> Dict[str, Any]:
        """A client id or name -> one client row. Several matches: the AI is asked to pick."""
        text = str(ref or "").strip()
        if not text:
            raise ActionError("Say which client: its name or its id.")
        if UUID.match(text):
            row = self.client_row(text)
            if not row:
                raise ActionError("No client with the id {0}.".format(text))
        else:
            safe = re.sub(r"[*,()%\\]", " ", text).strip()
            rows = self.db.select("clients", {"client_name": "ilike.*{0}*".format(safe)}, order="client_name", limit=20)
            if not allow_archived:
                gone = [r for r in rows if is_archived(r)]
                rows = [r for r in rows if not is_archived(r)]
                if gone and not rows:
                    raise ActionError("{0} is archived. Restore it in the OS first.".format(gone[0].get("client_name")))
            exact = [r for r in rows if (r.get("client_name") or "").lower() == text.lower()]
            rows = exact or rows
            if not rows:
                raise ActionError("No client matches '{0}'.".format(text))
            if len(rows) > 1:
                raise ActionError(
                    "'{0}' matches {1} clients: {2}. Ask which one, then use its id.".format(
                        text, len(rows), "; ".join("{0} ({1})".format(r["client_name"], r["id"]) for r in rows)
                    )
                )
            row = rows[0]
            self._clients[row["id"]] = row
        if is_archived(row) and not allow_archived:
            raise ActionError("{0} is archived. Restore it in the OS first.".format(row.get("client_name")))
        return row

    # ---- cards

    def card(self, board: Dict[str, Any], card_id: Any) -> Dict[str, Any]:
        row = self.db.get(board["key"], str(card_id or "")) if card_id else None
        if not row:
            raise ActionError("No card with the id {0} on {1}.".format(card_id, board["key"]))
        return row

    def changeable(self, board: Dict[str, Any], card: Dict[str, Any]) -> None:
        if is_archived(card):
            raise ActionError("This card is archived. Restore it in the OS first.")
        if is_archived(self.client_row(card.get("client_id"))):
            raise ActionError("This card's client is archived. Restore the client in the OS first.")

    def stage(self, board: Dict[str, Any], wanted: Any) -> str:
        """'30 - In Review', '30', 'in review' -> the exact stage label."""
        text = str(wanted or "").strip()
        stages = board["stages"]
        for s in stages:
            if text == s or text.lower() == s.lower():
                return s
        for s in stages:
            num = stage_number(s)
            if text.lstrip("-").isdigit() and num == int(text):
                return s
            if text.lower() == s.split(" - ", 1)[-1].lower():
                return s
        raise ActionError(
            "'{0}' is not a stage on {1}. The stages are: {2}.".format(wanted, board["key"], "; ".join(stages))
        )

    def short(self, board: str, card: Dict[str, Any]) -> Dict[str, Any]:
        """One card in the shape every list uses."""
        spec = self.boards.get(board, {})
        out = {
            "board": board,
            "board_label": self.config.board_label(board),
            "id": card.get("id") or card.get("card_id"),
            "name": card.get(spec.get("name", "")) or card.get("card_name"),
            "client": self.client_name(card.get("client_id")),
            "client_id": card.get("client_id"),
            "stage": card.get("stage"),
            "due_date": card.get("due_date"),
            "assignee": self.name(card.get("assignee_id")),
            "reviewer": self.name(card.get("reviewer_id")),
            "link": self.link(board, card),
        }
        return {k: v for k, v in out.items() if v not in (None, "")}


# --------------------------------------------------------------------------- small helpers


def page_of(rows: List[Any], page: Optional[int]) -> Dict[str, Any]:
    """At most 100 rows, and the number of the next page when there are more."""
    n = max(1, int(page or 1))
    start = (n - 1) * PAGE
    chunk = rows[start : start + PAGE]
    more = len(rows) > start + PAGE
    return {"rows": chunk, "page": n, "next_page": n + 1 if more else None, "total": len(rows)}


def parse_day(value: Any) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(value)[:10]).date() if value else None
    except ValueError:
        return None


def parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def a_date(value: Any, what: str) -> Optional[str]:
    if value in (None, ""):
        return None
    d = parse_day(value)
    if not d:
        raise ActionError("{0} must be a date like 2026-11-03.".format(what))
    return d.isoformat()


def live(client: Dict[str, Any], **filters: str) -> Dict[str, str]:
    """Filters for one client's calls, forms, numbers or items: archived rows are left
    out, unless the client itself is archived (then its history is shown as it was)."""
    out = {"client_id": "eq." + client["id"]}
    if not is_archived(client):
        out["archived_at"] = "is.null"
    out.update(filters)
    return out


def clean(row: Dict[str, Any]) -> Dict[str, Any]:
    """A row without the columns the AI never needs."""
    return {k: v for k, v in row.items() if k not in ("is_example", "mcp_token_hash") and v not in (None, "")}


# --------------------------------------------------------------------------- urgency


def urgency(ctx: Context, card: Dict[str, Any], me: Optional[str]) -> Tuple[Tuple[Any, ...], List[str]]:
    """The sort key and the reasons. Late, then due today, then waiting for my review
    (anyone's review when me is None), then stuck longest."""
    today = ctx.today
    due = parse_day(card.get("due_date"))
    moved = parse_time(card.get("stage_changed_at"))
    days_still = (datetime.now(timezone.utc) - moved).days if moved else 0
    waiting = card.get("stage") in ctx.review(card.get("board", "")) and (me is None or card.get("reviewer_id") == me)
    reasons: List[str] = []
    if due and due < today:
        bucket, inner = 0, -(today - due).days
        reasons.append("late {0} day{1}".format((today - due).days, "" if (today - due).days == 1 else "s"))
    elif due and due == today:
        bucket, inner = 1, 0
        reasons.append("due today")
    elif waiting:
        bucket, inner = 2, -days_still
    else:
        bucket, inner = 3, -days_still
    if waiting:
        reasons.append("waiting for {0} review".format("your" if me else "a"))
    if due and due == today + timedelta(days=1):
        reasons.append("due tomorrow")
    stuck_after = int(ctx.settings.get("stuck_after_days") or 3)
    if days_still >= stuck_after:
        reasons.append("no move for {0} days".format(days_still))
    return (bucket, inner, str(card.get("card_name") or "")), reasons


def ranked(ctx: Context, cards: List[Dict[str, Any]], me: Optional[str]) -> List[Dict[str, Any]]:
    scored = []
    for card in cards:
        if is_archived(ctx.client_row(card.get("client_id"))):
            continue
        key, reasons = urgency(ctx, card, me)
        row = ctx.short(card["board"], card)
        row["why"] = ", ".join(reasons) or "open"
        scored.append((key, row))
    scored.sort(key=lambda kv: kv[0])
    return [row for _, row in scored]


# --------------------------------------------------------------------------- read actions


def my_queue(ctx: Context, page: int = 1) -> Dict[str, Any]:
    me = ctx.me["id"]
    mine = ctx.db.select_all("v_open_cards", {"assignee_id": "eq." + me}, order="card_id")
    seen = {(c["board"], c["card_id"]) for c in mine}
    for c in ctx.db.select_all("v_open_cards", {"reviewer_id": "eq." + me}, order="card_id"):
        if (c["board"], c["card_id"]) not in seen and c.get("stage") in ctx.review(c["board"]):
            mine.append(c)
    out = page_of(ranked(ctx, [dict(c, id=c["card_id"]) for c in mine], me), page)
    out["order"] = "late, then due today, then waiting for your review, then the longest without a move"
    return out


def urgent(ctx: Context, page: int = 1) -> Dict[str, Any]:
    cards = ctx.db.select_all("v_open_cards", order="card_id")
    out = page_of(ranked(ctx, [dict(c, id=c["card_id"]) for c in cards], None), page)
    out["order"] = "late, then due today, then waiting for review, then the longest without a move"
    return out


def boards(ctx: Context) -> Dict[str, Any]:
    counts: Dict[Tuple[str, str], int] = {}
    for c in ctx.db.select_all("v_open_cards", columns="board,stage,client_id", order="card_id"):
        if not is_archived(ctx.client_row(c.get("client_id"))):
            counts[(c["board"], c["stage"])] = counts.get((c["board"], c["stage"]), 0) + 1
    out = []
    for key, spec in ctx.boards.items():
        out.append(
            {
                "board": key,
                "label": ctx.config.board_label(key),
                "stages": [{"stage": s, "open_cards": counts.get((key, s), 0)} for s in spec["stages"]],
                "finished_stages": ctx.finals(key),
                "review_stages": ctx.review(key),
                "fields_cards_update_may_change": spec.get("fields", []),
                "work_link_column": spec.get("work_link"),
                "documents": sorted(spec.get("documents", {})),
            }
        )
    return {"boards": out, "client_page_documents": sorted(ctx.spec.get("client_documents", {}))}


def cards_search(
    ctx: Context,
    query: str = "",
    board: str = "",
    client: str = "",
    person: str = "",
    stage: str = "",
    include_finished: bool = False,
    page: int = 1,
) -> Dict[str, Any]:
    keys = [ctx.board(board)["key"]] if board else list(ctx.boards)
    client_id = ctx.client(client)["id"] if client else None
    person_id = ctx.person(person) if person else None
    found: List[Tuple[str, Dict[str, Any]]] = []
    for key in keys:
        spec = ctx.boards[key]
        filters = {"archived_at": "is.null"}
        if query:
            filters[spec["name"]] = "ilike.*{0}*".format(re.sub(r"[*,()%\\]", " ", query).strip())
        if client_id:
            filters["client_id"] = "eq." + client_id
        wanted_stage = ctx.stage(dict(spec, key=key), stage) if stage else None
        for row in ctx.db.select_all(key, filters, order="id"):
            if wanted_stage and row.get("stage") != wanted_stage:
                continue
            if not include_finished and not wanted_stage and row.get("stage") in ctx.finals(key):
                continue
            if person_id and person_id not in [row.get(p) for p in spec.get("people", [])]:
                continue
            if is_archived(ctx.client_row(row.get("client_id"))):
                continue
            found.append((key, row))
    found.sort(key=lambda kr: str(kr[1].get("updated_at") or ""), reverse=True)
    out = page_of([ctx.short(k, r) for k, r in found], page)
    out["order"] = "most recently changed first"
    return out


def cards_get(ctx: Context, board: str, id: str) -> Dict[str, Any]:
    spec = ctx.board(board)
    card = ctx.card(spec, id)
    out: Dict[str, Any] = {"card": clean(card), "summary": ctx.short(spec["key"], card)}
    if is_archived(card) or is_archived(ctx.client_row(card.get("client_id"))):
        out["archived"] = True
    history = ctx.db.select(
        "stage_log",
        {"board": "eq." + spec["key"], "record_id": "eq." + card["id"]},
        columns="from_stage,to_stage,changed_at,changed_by_id",
        order="changed_at.desc",
        limit=50,
    )
    out["history"] = [
        {
            "from": h.get("from_stage"),
            "to": h.get("to_stage"),
            "at": h.get("changed_at"),
            "by": ctx.name(h.get("changed_by_id")),
        }
        for h in history
    ]
    docs = docs_list(ctx, spec, card)
    if docs:
        out["documents"] = docs
    items = spec.get("items")
    if items:
        rows = ctx.db.select(
            items["table"],
            {items["key"]: "eq." + card["id"], "archived_at": "is.null"},
            order=items.get("order"),
            limit=PAGE,
        )
        out["items"] = {"table": items["table"], "rows": [clean(r) for r in rows]}
    return out


def clients_get(ctx: Context, client: str) -> Dict[str, Any]:
    row = ctx.client(client, allow_archived=True)
    cid = row["id"]
    roles = {}
    for col in ctx.config.rules.get("client_roles", ["account_manager_id"]):
        if row.get(col):
            roles[col[:-3]] = ctx.name(row[col])
    open_cards = ctx.db.select_all("v_open_cards", {"client_id": "eq." + cid}, order="card_id")
    calls = ctx.db.select(
        "calls", live(row), columns="id,title,call_type,call_at,summary", order="call_at.desc", limit=5
    )
    forms = ctx.db.select(
        "onboarding_forms",
        live(row),
        columns="id,form_key,submitted_by_name,submitted_at",
        order="submitted_at.desc",
        limit=5,
    )
    weeks = ctx.db.select("weekly_metrics", live(row), order="week_start.desc", limit=4)
    out = {
        "client": clean({k: v for k, v in row.items() if k != "form_code"}),
        "people": roles,
        "link": client_link(ctx.settings, cid),
        "open_cards": [ctx.short(c["board"], dict(c, id=c["card_id"])) for c in open_cards[:PAGE]],
        "recent_calls": [clean(c) for c in calls],
        "forms": [clean(f) for f in forms],
        "last_weeks": [clean(w) for w in weeks],
    }
    docs = docs_list(ctx, None, row)
    if docs:
        out["documents"] = docs
    if is_archived(row):
        out["archived"] = True
    return out


def team(ctx: Context) -> Dict[str, Any]:
    load = {r["team_id"]: r for r in ctx.db.select_all("v_team_load", order="team_id")}
    out = []
    for t in ctx.team:
        if t.get("status", "Active") != "Active":
            continue
        row = load.get(t["id"], {})
        out.append(
            clean(
                {
                    "id": t["id"],
                    "name": t.get("full_name"),
                    "email": t.get("email"),
                    "job_title": t.get("job_title"),
                    "access": t.get("access"),
                    "open_cards": row.get("open_cards", 0),
                    "late_cards": row.get("late_cards", 0),
                    "sent_back_cards": row.get("sent_back_cards", 0),
                    "capacity": t.get("capacity"),
                    "overloaded": bool(row.get("overloaded")),
                    "is_me": t["id"] == ctx.me["id"] or None,
                }
            )
        )
    return {"team": out}


def calls_get(ctx: Context, id: str = "", client: str = "", page: int = 1) -> Dict[str, Any]:
    if id:
        row = ctx.db.get("calls", id)
        if not row:
            raise ActionError("No call with the id {0}.".format(id))
        return {
            "call": clean(row),
            "client": ctx.client_name(row.get("client_id")),
            "archived": is_archived(row) or None,
        }
    if not client:
        raise ActionError("Give a call id, or a client to list its calls.")
    rows = ctx.db.select_all(
        "calls",
        live(ctx.client(client, allow_archived=True)),
        columns="id,title,call_type,call_at,summary,recording_url",
        order="call_at.desc",
    )
    out = page_of([clean(dict(r, summary=(r.get("summary") or "")[:300])) for r in rows], page)
    out["note"] = "Newest first. Summaries are cut at 300 letters; calls.get with the id gives the full call."
    return out


def forms_get(ctx: Context, id: str = "", client: str = "", page: int = 1) -> Dict[str, Any]:
    if id:
        row = ctx.db.get("onboarding_forms", id)
        if not row:
            raise ActionError("No onboarding form with the id {0}.".format(id))
        return {
            "form": clean(row),
            "client": ctx.client_name(row.get("client_id")),
            "archived": is_archived(row) or None,
        }
    if not client:
        raise ActionError("Give a form id, or a client to list its forms.")
    rows = ctx.db.select_all(
        "onboarding_forms",
        live(ctx.client(client, allow_archived=True)),
        columns="id,form_key,submitted_by_name,submitted_by_email,company_name,submitted_at",
        order="submitted_at.desc",
    )
    return page_of([clean(r) for r in rows], page)


def metrics_get(
    ctx: Context, client: str, period: str = "weekly", date_from: str = "", date_to: str = "", page: int = 1
) -> Dict[str, Any]:
    table, col = period_table(period)
    rows = ctx.db.select_all(table, live(ctx.client(client, allow_archived=True)), order=col + ".desc")
    lo, hi = a_date(date_from, "date_from"), a_date(date_to, "date_to")
    rows = [r for r in rows if (not lo or str(r.get(col)) >= lo) and (not hi or str(r.get(col)) <= hi)]
    out = page_of([clean({k: v for k, v in r.items() if k != "client_id"}) for r in rows], page)
    out["period"] = "daily" if table == "daily_metrics" else "weekly"
    return out


def period_table(period: str) -> Tuple[str, str]:
    p = (period or "weekly").strip().lower()
    if p in ("daily", "day"):
        return "daily_metrics", "metric_date"
    if p in ("weekly", "week"):
        return "weekly_metrics", "week_start"
    raise ActionError("period must be 'daily' or 'weekly'.")


# --------------------------------------------------------------------------- write actions


def cards_create(
    ctx: Context,
    board: str,
    name: str,
    client: str = "",
    assignee: str = "",
    reviewer: str = "",
    due_date: str = "",
    stage: str = "",
    notes: str = "",
    work_link: str = "",
) -> Dict[str, Any]:
    spec = ctx.board(board)
    values: Dict[str, Any] = {spec["name"]: name.strip(), "stage_changed_by_id": ctx.me["id"]}
    values["stage"] = ctx.stage(spec, stage) if stage else ctx.first_open(spec)
    if client:
        values["client_id"] = ctx.client(client)["id"]
    elif spec["key"] != "tasks":
        raise ActionError("A card on {0} needs a client.".format(spec["key"]))
    for col, ref in (("assignee_id", assignee), ("reviewer_id", reviewer)):
        if ref:
            if col not in spec.get("people", []):
                raise ActionError("Cards on {0} have no {1}.".format(spec["key"], col[:-3]))
            values[col] = ctx.person(ref)
    if due_date:
        values["due_date"] = a_date(due_date, "due_date")
    if notes:
        values["notes"] = notes
    if work_link:
        if not spec.get("work_link"):
            raise ActionError("Cards on {0} have no work link.".format(spec["key"]))
        values[spec["work_link"]] = work_link.strip()
    if spec.get("created_by"):
        values[spec["created_by"]] = ctx.me["id"]
    row = ctx.db.insert(spec["key"], values)
    return {"created": ctx.short(spec["key"], row or values), "stage_log": "written by the database, as in the app"}


def cards_move(ctx: Context, board: str, id: str, stage: str) -> Dict[str, Any]:
    spec = ctx.board(board)
    card = ctx.card(spec, id)
    ctx.changeable(spec, card)
    to = ctx.stage(spec, stage)
    if card.get("stage") == to:
        return {
            "moved": False,
            "reason": "The card is already at {0}.".format(to),
            "card": ctx.short(spec["key"], card),
        }
    # Naming the mover in the same change is how the stage log records who moved it.
    row = ctx.db.update(spec["key"], card["id"], {"stage": to, "stage_changed_by_id": ctx.me["id"]})
    return {
        "moved": True,
        "from": card.get("stage"),
        "to": to,
        "card": ctx.short(spec["key"], row or dict(card, stage=to)),
        "note": "The stage log is written and the Slack alert for this stage fires, as in the app.",
    }


def cards_update(
    ctx: Context,
    board: str,
    id: str,
    due_date: Optional[str] = None,
    notes: Optional[str] = None,
    work_link: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    spec = ctx.board(board)
    card = ctx.card(spec, id)
    ctx.changeable(spec, card)
    values: Dict[str, Any] = {}
    if due_date is not None:
        values["due_date"] = a_date(due_date, "due_date")
    if notes is not None:
        values["notes"] = notes or None
    if work_link is not None:
        if not spec.get("work_link"):
            raise ActionError("Cards on {0} have no work link.".format(spec["key"]))
        values[spec["work_link"]] = work_link.strip() or None
    for col, value in (fields or {}).items():
        if col not in spec.get("fields", []):
            raise ActionError(
                "cards.update cannot change '{0}' on {1}. It may change: {2}. Use cards.move for the stage.".format(
                    col, spec["key"], ", ".join(spec.get("fields", []))
                )
            )
        values[col] = a_date(value, col) if col == "due_date" else (value if value != "" else None)
    if not values:
        raise ActionError("Nothing to change. Give due_date, notes, work_link or fields.")
    row = ctx.db.update(spec["key"], card["id"], values)
    return {"updated": sorted(values), "card": ctx.short(spec["key"], row or dict(card, **values))}


def cards_note(ctx: Context, board: str, id: str, text: str) -> Dict[str, Any]:
    spec = ctx.board(board)
    card = ctx.card(spec, id)
    ctx.changeable(spec, card)
    line = "{0}, {1}: {2}".format(ctx.today.isoformat(), ctx.me.get("full_name") or "Someone", text.strip())
    notes = "\n\n".join(p for p in ((card.get("notes") or "").rstrip(), line) if p)
    ctx.db.update(spec["key"], card["id"], {"notes": notes})
    return {"added": line, "card": ctx.short(spec["key"], card)}


def emails_tick(ctx: Context, id: str, status: str = "") -> Dict[str, Any]:
    statuses = ctx.spec.get("emails", {}).get("statuses", [])
    email = ctx.db.get("emails", id) if id else None
    if not email:
        raise ActionError("No email with the id {0}.".format(id))
    if is_archived(email):
        raise ActionError("This email is archived. Restore it in the OS first.")
    if is_archived(ctx.client_row(email.get("client_id"))):
        raise ActionError("This email's client is archived. Restore the client in the OS first.")
    for parent, col in (("flows", "flow_id"), ("campaign_calendars", "calendar_id")):
        if email.get(col) and is_archived(ctx.db.get(parent, email[col], columns="id,archived_at")):
            raise ActionError("This email's card is archived. Restore it in the OS first.")
    now = email.get("status")
    if status:
        match = [s for s in statuses if s.lower() == status.strip().lower()]
        if not match:
            raise ActionError("'{0}' is not an email status. They are: {1}.".format(status, ", ".join(statuses)))
        new = match[0]
    else:
        at = statuses.index(now) if now in statuses else -1
        if at + 1 >= len(statuses):
            return {"ticked": False, "reason": "The email is already at the last step ({0}).".format(now)}
        new = statuses[at + 1]
    ctx.db.update("emails", email["id"], {"status": new})
    return {"ticked": True, "email": email.get("email_name"), "from": now, "to": new}


def calls_add(
    ctx: Context,
    client: str,
    title: str,
    call_at: str = "",
    call_type: str = "",
    recording_url: str = "",
    summary: str = "",
    transcript: str = "",
    action_items: str = "",
    attendees: str = "",
) -> Dict[str, Any]:
    values: Dict[str, Any] = {"client_id": ctx.client(client)["id"], "title": title.strip()}
    if call_type:
        types = ctx.spec.get("call_types", [])
        match = [t for t in types if t.lower() == call_type.strip().lower()]
        if not match:
            raise ActionError("call_type must be one of: {0}.".format(", ".join(types)))
        values["call_type"] = match[0]
    if call_at:
        when = parse_time(call_at)
        if not when:
            raise ActionError("call_at must be a date and time like 2026-11-03T14:00:00Z.")
        values["call_at"] = when.isoformat()
    for col, value in (
        ("recording_url", recording_url),
        ("summary", summary),
        ("transcript", transcript),
        ("action_items", action_items),
        ("attendees", attendees),
    ):
        if value:
            values[col] = value
    row = ctx.db.insert("calls", values)
    return {
        "added": {"id": (row or {}).get("id"), "title": values["title"], "client": ctx.client_name(values["client_id"])}
    }


def metrics_add(ctx: Context, client: str, period: str, date: str, values: Dict[str, Any]) -> Dict[str, Any]:
    table, col = period_table(period)
    allowed = ctx.spec.get("metrics", {}).get("daily" if table == "daily_metrics" else "weekly", [])
    bad = sorted(set(values or {}) - set(allowed))
    if bad or not values:
        raise ActionError(
            "values may hold: {0}.{1}".format(", ".join(allowed), " Not: " + ", ".join(bad) if bad else "")
        )
    day = parse_day(date)
    if not day:
        raise ActionError("date must be a date like 2026-11-02.")
    if table == "weekly_metrics":
        day = day - timedelta(days=day.weekday())  # a week starts on Monday
    row = dict(values, client_id=ctx.client(client)["id"])
    row[col] = day.isoformat()
    saved = ctx.db.upsert(table, row, on_conflict="client_id," + col)
    return {"saved": clean(saved or row), "table": table}


def clients_update(ctx: Context, client: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    row = ctx.client(client)
    allowed = ctx.spec.get("client_fields", [])
    values: Dict[str, Any] = {}
    for col, value in (fields or {}).items():
        if col not in allowed:
            raise ActionError("clients.update cannot change '{0}'. It may change: {1}.".format(col, ", ".join(allowed)))
        if value == "":
            value = None
        if col.endswith("_id") and value and col != "ad_account_id":
            value = ctx.person(value)
        if col == "onboarding_stage" and value:
            value = ctx.stage({"key": "clients", "stages": ctx.spec.get("client_stages", [])}, value)
            if value != row.get("onboarding_stage"):
                values["onboarding_stage_changed_by_id"] = ctx.me["id"]
        values[col] = value
    if not values:
        raise ActionError('Nothing to change. Give fields, for example {"status": "Paused"}.')
    saved = ctx.db.update("clients", row["id"], values)
    return {
        "updated": sorted(k for k in values if k != "onboarding_stage_changed_by_id"),
        "client": (saved or row).get("client_name"),
        "link": client_link(ctx.settings, row["id"]),
    }


# --------------------------------------------------------------------------- documents

DOC_MAX_BYTES = 500000
DOC_PREVIEW = 500
DOC_COLUMNS = "id,client_id,board,card_id,field_key,body_md,word_count,version,updated_by,updated_at,archived_at"
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def word_count(body_md: str) -> int:
    """The app's count: the plain text split on spaces, counting the parts with a letter or a
    digit. A link counts its words, not its address; {{firstName}} is one word. Pure."""
    text = _MD_LINK.sub(r"\1", body_md or "")
    return sum(1 for part in text.split() if re.search(r"[^\W_]", part))


def doc_fields(ctx: Context, board: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The document fields of a board, or of the client page when board is None."""
    return (board or {}).get("documents", {}) if board else ctx.spec.get("client_documents", {})


def doc_target(
    ctx: Context, document: str = "", board: str = "", card: str = "", client: str = "", field: str = ""
) -> Dict[str, Any]:
    """Which document: by its id, or by board + card + field, or by client + field (client page).
    Returns the place (client row, board spec or None, card or None, field) and the row if one exists."""
    row: Optional[Dict[str, Any]] = None
    if document:
        row = ctx.db.get("documents", str(document).strip(), columns=DOC_COLUMNS)
        if not row:
            raise ActionError("No document with the id {0}.".format(document))
        board, card, field = row.get("board") or "", row.get("card_id") or "", row["field_key"]
        client = row["client_id"]
    spec = ctx.board(board) if board else None
    the_card = None
    if spec:
        if not card:
            raise ActionError("Say which card: give its id as 'card' (cards.search finds it).")
        the_card = ctx.card(spec, card)
        client_row = ctx.client_row(the_card.get("client_id"))
        if not client_row:
            raise ActionError("This card has no client, so it has no documents.")
    else:
        client_row = ctx.client(client, allow_archived=True)
    fields = doc_fields(ctx, spec)
    where = "cards on {0}".format(spec["key"]) if spec else "the client page"
    if not fields:
        raise ActionError("{0} have no documents.".format(where[0].upper() + where[1:]))
    key = str(field or "").strip()
    if key not in fields:
        for k, f in fields.items():
            if key.lower() in (k.lower(), str(f.get("label", "")).lower()):
                key = k
                break
    if key not in fields:
        raise ActionError(
            "Say which document on {0}: {1}.".format(
                where, "; ".join("'{0}' ({1})".format(k, f.get("label", k)) for k, f in fields.items())
            )
        )
    if row is None:
        found = ctx.db.select(
            "documents",
            {
                "client_id": "eq." + client_row["id"],
                "board": "eq." + spec["key"] if spec else "is.null",
                "card_id": "eq." + the_card["id"] if the_card else "is.null",
                "field_key": "eq." + key,
            },
            columns=DOC_COLUMNS,
            limit=1,
        )
        row = found[0] if found else None
    return {"client": client_row, "board": spec, "card": the_card, "field": key, "spec": fields[key], "row": row}


def doc_summary(ctx: Context, t: Dict[str, Any], body: bool) -> Dict[str, Any]:
    row = t["row"] or {}
    text = row.get("body_md") or ""
    out: Dict[str, Any] = {
        "document": row.get("id"),
        "field": t["field"],
        "label": t["spec"].get("label", t["field"]),
        "client": t["client"].get("client_name"),
        "board": t["board"]["key"] if t["board"] else None,
        "card": t["card"]["id"] if t["card"] else None,
        "version": row.get("version", 0),
        "word_count": row.get("word_count", 0),
        "updated_by": ctx.name(row.get("updated_by")),
        "updated_at": row.get("updated_at"),
    }
    if body:
        out["body_md"] = text
    else:
        out["preview"] = text[:DOC_PREVIEW] + ("..." if len(text) > DOC_PREVIEW else "")
    link_col = t["spec"].get("link")
    holder = t["card"] if t["board"] else t["client"]
    if link_col and (holder or {}).get(link_col):
        out["pasted_link"] = holder[link_col]
    if not row:
        out["note"] = "Not written yet. To write it, use docs.write with version 0."
    return {k: v for k, v in out.items() if v not in (None, "")}


def docs_list(ctx: Context, board: Optional[Dict[str, Any]], holder: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every document field of one card or client page: first 500 characters and the word count."""
    fields = doc_fields(ctx, board)
    if not fields:
        return []
    client_id = holder.get("client_id") if board else holder.get("id")
    rows = ctx.db.select(
        "documents",
        {
            "client_id": "eq." + str(client_id),
            "board": "eq." + board["key"] if board else "is.null",
            "card_id": "eq." + holder["id"] if board else "is.null",
        },
        columns=DOC_COLUMNS,
        limit=50,
    )
    by_key = {r["field_key"]: r for r in rows}
    client_row = ctx.client_row(client_id) or {}
    return [
        doc_summary(
            ctx,
            {"client": client_row, "board": board, "card": holder if board else None, "field": k, "spec": f,
             "row": by_key.get(k)},
            body=False,
        )
        for k, f in fields.items()
    ]  # fmt: skip


def docs_read(
    ctx: Context, document: str = "", board: str = "", card: str = "", client: str = "", field: str = ""
) -> Dict[str, Any]:
    t = doc_target(ctx, document, board, card, client, field)
    out = doc_summary(ctx, t, body=True)
    if is_archived(t["row"]) or is_archived(t["card"]) or is_archived(t["client"]):
        out["archived"] = True
    return out


def docs_write(
    ctx: Context,
    body_md: str,
    version: int,
    document: str = "",
    board: str = "",
    card: str = "",
    client: str = "",
    field: str = "",
) -> Dict[str, Any]:
    t = doc_target(ctx, document, board, card, client, field)
    if t["board"]:
        ctx.changeable(t["board"], t["card"])
    else:
        if ctx.me.get("access") not in ADMINS:
            raise ActionError(
                "Refused: client page documents are for Owners and Admins only, the same as clients.update; "
                "you are a Member. Card documents are open to everyone."
            )
        if is_archived(t["client"]):
            raise ActionError("{0} is archived. Restore it in the OS first.".format(t["client"].get("client_name")))
    if len((body_md or "").encode("utf-8")) > DOC_MAX_BYTES:
        raise ActionError("This document is too long: the most is 500 000 bytes. Split it, or paste a link instead.")
    row = t["row"]
    version = int(version or 0)
    if row is None:
        if version != 0:
            raise ActionError("This document is not written yet, so its version is 0. Write it with version 0.")
        row = one_row(
            ctx.db.rpc(
                "open_document",
                {
                    "p_client": t["client"]["id"],
                    "p_board": t["board"]["key"] if t["board"] else None,
                    "p_card": t["card"]["id"] if t["card"] else None,
                    "p_field": t["field"],
                },
            )
        )
        if row.get("version") != 1 or row.get("body_md"):
            raise ActionError(conflict_text(row.get("version")))
        version = 1
    count = word_count(body_md)
    try:
        saved = ctx.db.rpc(
            "save_document",
            {
                "p_id": row["id"],
                "p_version": version,
                "p_body_md": body_md or "",
                "p_word_count": count,
                "p_saved_by": ctx.me["id"],
            },
        )
    except Exception as e:  # noqa: BLE001 - the database's reasons, in plain words
        if "document_conflict" in str(e):
            fresh = ctx.db.get("documents", row["id"], columns="version") or {}
            raise ActionError(conflict_text(fresh.get("version"))) from e
        raise
    new_version = saved.get("version") if isinstance(saved, dict) else saved
    if isinstance(saved, list):
        new_version = one_row(saved).get("version")
    holder_link = ctx.link(t["board"]["key"], t["card"]) if t["board"] else client_link(ctx.settings, t["client"]["id"])
    return {
        "saved": True,
        "document": row["id"],
        "field": t["field"],
        "version": new_version,
        "word_count": count,
        "link": holder_link,
    }


def one_row(value: Any) -> Dict[str, Any]:
    if isinstance(value, list):
        return value[0] if value else {}
    return value or {}


def conflict_text(now: Any) -> str:
    return (
        "Someone else changed this document after you read it (it is now version {0}). Nothing was saved. "
        "Read it again with docs.read, put your change into the new text, then write with version {0}.".format(
            now if now is not None else "newer"
        )
    )


# --------------------------------------------------------------------------- the second brain

BRAIN_RULE = (
    "Read the second brain before any work that needs judgment (sales, offers, copy, process, planning, "
    "a client plan): brain.index, then the area map, then the notes. Name the notes you used. If no note "
    "covers it, say 'the second brain has nothing on <subject>'. Never name a note you did not open."
)
NOT_SET_UP = (
    "The second brain is not set up yet, so there are no notes to read. Say that plainly and do not guess. "
    "Tab 4 (docs/4-second-brain.md) builds it."
)
BRAIN_SKIP = {"inbox": "inbox/ is not sorted yet", "raw": "raw/ holds whole sources, word for word"}
BRAIN_FILES = {".md", ".txt"}
NOTE_MAX = 40000
HITS = 20


def brain_root() -> Optional[Path]:
    for d in BRAIN_DIRS:
        if d.is_dir():
            return d.resolve()
    return None


def brain_files(root: Path) -> List[Path]:
    """Every readable file: markdown and text, not in inbox/ or raw/, not the set-up files."""
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or p.suffix.lower() not in BRAIN_FILES or rel.parts[0] in BRAIN_SKIP:
            continue
        if p.name == "PROMPT.md" and len(rel.parts) == 1:
            continue
        if not p.resolve().is_relative_to(root):  # a link that points outside
            continue
        out.append(p)
    return out


def is_note(root: Path, p: Path) -> bool:
    rel = p.relative_to(root)
    return p.suffix.lower() == ".md" and len(rel.parts) > 1


def brain_ready() -> Path:
    """The brain folder, or a plain answer that it is not set up (no index, or no notes)."""
    root = brain_root()
    if root is None or not (root / "INDEX.md").is_file():
        raise ActionError(NOT_SET_UP)
    if not any(is_note(root, p) for p in brain_files(root)):
        raise ActionError(NOT_SET_UP)
    return root


def note_title(p: Path, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return p.stem.replace("_", " ")


def read_text(p: Path) -> Tuple[str, bool]:
    text = p.read_text(encoding="utf-8", errors="replace")
    return (text[:NOTE_MAX], True) if len(text) > NOTE_MAX else (text, False)


def find_note(root: Path, ref: Any) -> Path:
    """'[[Note_Name]]', 'Note_Name' or 'area/Note_Name.md' -> one note inside the brain."""
    text = str(ref or "").strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2].split("|")[0].split("#")[0].strip()
    if not text:
        raise ActionError("Say which note: its name, as in a [[link]], or its path.")
    if "/" in text or "\\" in text or text.startswith("."):
        target = (root / text).resolve()
        if not target.is_relative_to(root):
            raise ActionError("Refused: '{0}' is outside the second brain. Only its notes can be read.".format(ref))
        rel = target.relative_to(root)
        if rel.parts and rel.parts[0] in BRAIN_SKIP:
            raise ActionError("Refused: {0}, so the connector does not read it.".format(BRAIN_SKIP[rel.parts[0]]))
        if target in brain_files(root):
            return target
        raise ActionError("No note at '{0}'. Use brain.search or brain.map to find it.".format(ref))
    want = text.lower()[:-3] if text.lower().endswith(".md") else text.lower()
    hits = [p for p in brain_files(root) if p.stem.lower() == want or p.name.lower() == want]
    if not hits:
        raise ActionError("No note called '{0}'. Use brain.search to find it.".format(ref))
    return hits[0]


def brain_index(ctx: Context) -> Dict[str, Any]:
    root = brain_ready()
    text, cut = read_text(root / "INDEX.md")
    maps = [p for p in brain_files(root) if p.name.endswith("_map.md")]
    return {
        "index": text,
        "cut_short": cut or None,
        "areas": [{"area": p.parent.name, "map": p.stem} for p in maps],
        "rule": BRAIN_RULE,
    }


def brain_map(ctx: Context, area: str) -> Dict[str, Any]:
    root = brain_ready()
    want = str(area or "").strip().strip("[]").lower()
    want = want[:-4] if want.endswith("_map") else want
    maps = [p for p in brain_files(root) if p.name.endswith("_map.md")]
    for p in maps:
        if want in (p.parent.name.lower(), p.stem.lower()[:-4]):
            text, cut = read_text(p)
            notes = [q.stem for q in brain_files(root) if q.parent == p.parent and q != p and is_note(root, q)]
            return {"area": p.parent.name, "map": text, "cut_short": cut or None, "notes": notes, "rule": BRAIN_RULE}
    raise ActionError(
        "No area called '{0}'. The areas are: {1}.".format(area, ", ".join(p.parent.name for p in maps) or "none yet")
    )


def brain_search(ctx: Context, query: str, area: str = "") -> Dict[str, Any]:
    root = brain_ready()
    words = [w for w in re.split(r"\s+", str(query or "").lower()) if w]
    if not words:
        raise ActionError("Give the words to look for.")
    scored = []
    for p in brain_files(root):
        if not is_note(root, p) or (area and p.parent.name.lower() != area.strip().lower()):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        hay = (p.stem.replace("_", " ") + "\n" + text).lower()
        if not all(w in hay for w in words):
            continue
        score = sum(hay.count(w) for w in words) + 5 * sum(w in p.stem.lower() for w in words)
        line = next((ln.strip() for ln in text.splitlines() if words[0] in ln.lower()), "")
        scored.append(
            (
                -score,
                p.stem,
                {
                    "note": p.stem,
                    "path": str(p.relative_to(root)),
                    "area": p.parent.name,
                    "title": note_title(p, text),
                    "line": line[:200],
                },
            )
        )
    scored.sort(key=lambda t: (t[0], t[1]))
    hits = [h for _, _, h in scored[:HITS]]
    out: Dict[str, Any] = {"hits": hits, "more": len(scored) > HITS or None, "rule": BRAIN_RULE}
    if not hits:
        out["message"] = "No note has all of: {0}. Say 'the second brain has nothing on {1}'.".format(
            ", ".join(words), query
        )
    return out


def brain_read(ctx: Context, note: str) -> Dict[str, Any]:
    root = brain_ready()
    p = find_note(root, note)
    text, cut = read_text(p)
    return {
        "note": p.stem,
        "path": str(p.relative_to(root)),
        "title": note_title(p, text),
        "text": text,
        "cut_short": cut or None,
        "links": sorted(set(re.findall(r"\[\[([^\]|#]+)", text))),
        "rule": "Name this note ([[{0}]]) when you use it.".format(p.stem),
    }


# --------------------------------------------------------------------------- the registry


def _p(kind: str, description: str) -> Dict[str, Any]:
    return {"type": kind, "description": description}


PAGE_P = _p("integer", "Page number, from 1. Each page has at most 100 rows; 'next_page' says if there is another.")
BOARD_P = _p("string", "The board, for example 'tasks'. Run 'boards' to see them.")
ID_P = _p("string", "The card's id.")
CLIENT_P = _p("string", "The client's name or id.")
PERSON_P = _p("string", "'me', a name, an email or a team id.")
DOC_PARAMS = {
    "document": _p("string", "The document's id (from cards.get, clients.get or docs.read)."),
    "board": BOARD_P,
    "card": _p("string", "The card's id, with board and field."),
    "client": _p("string", "The client's name or id, with field, for a client page document."),
    "field": _p("string", "Which document, for example 'copy_doc' ('boards' lists them)."),
}


def _entry(kind, roles, description, handler, props=None, required=None):
    return {
        "kind": kind,
        "roles": roles,
        "description": description,
        "schema": {"type": "object", "properties": props or {}, "required": required or []},
        "handler": handler,
    }


ALL: Dict[str, Dict[str, Any]] = {
    "my_queue": _entry(
        "read",
        EVERYONE,
        "My open cards, most urgent first: late, then due today, then waiting for my review, then the "
        "longest without a move. Start here for 'what should I do next?' or 'what is most urgent for me?'.",
        my_queue,
        {"page": PAGE_P},
    ),
    "urgent": _entry(
        "read",
        ADMINS,
        "Every open card on the team, most urgent first (same order as my_queue), with who has it. Owners and Admins.",
        urgent,
        {"page": PAGE_P},
    ),
    "boards": _entry(
        "read",
        EVERYONE,
        "The boards: each one's stages in order with the number of open cards, the finished and review stages, "
        "and the fields cards.update may change.",
        boards,
    ),
    "cards.search": _entry(
        "read",
        EVERYONE,
        "Find cards by words in the name, board, client, person or stage. Finished cards only with "
        "include_finished. Archived cards are never shown.",
        cards_search,
        {
            "query": _p("string", "Words in the card's name."),
            "board": BOARD_P,
            "client": CLIENT_P,
            "person": _p("string", "Cards this person works on or reviews: 'me', a name or an email."),
            "stage": _p("string", "Only cards at this stage."),
            "include_finished": _p("boolean", "Also show cards at a finished stage."),
            "page": PAGE_P,
        },
    ),
    "cards.get": _entry(
        "read",
        EVERYONE,
        "One card in full: every field, its stage history (who moved it and when) and its items "
        "(for example the emails in a flow).",
        cards_get,
        {"board": BOARD_P, "id": ID_P},
        ["board", "id"],
    ),
    "clients.get": _entry(
        "read",
        EVERYONE,
        "One client: its fields, its people, its open cards, its last calls and forms, "
        "and its last four weeks of numbers.",
        clients_get,
        {"client": CLIENT_P},
        ["client"],
    ),
    "team": _entry(
        "read",
        EVERYONE,
        "The active team, with each person's open, late and sent-back cards against their capacity.",
        team,
    ),
    "calls.get": _entry(
        "read",
        EVERYONE,
        "One call in full (summary, transcript, action items) by its id, or a client's calls, newest first.",
        calls_get,
        {"id": _p("string", "The call's id."), "client": CLIENT_P, "page": PAGE_P},
    ),
    "forms.get": _entry(
        "read",
        EVERYONE,
        "One onboarding form with every answer, by its id, or a client's forms, newest first.",
        forms_get,
        {"id": _p("string", "The form's id."), "client": CLIENT_P, "page": PAGE_P},
    ),
    "metrics.get": _entry(
        "read",
        EVERYONE,
        "A client's report numbers, daily or weekly, newest first.",
        metrics_get,
        {
            "client": CLIENT_P,
            "period": _p("string", "'weekly' (default) or 'daily'."),
            "date_from": _p("string", "Only from this date, for example 2026-10-01."),
            "date_to": _p("string", "Only up to this date."),
            "page": PAGE_P,
        },
        ["client"],
    ),
    "cards.create": _entry(
        "write",
        EVERYONE,
        "Add a card to a board. It starts at the first stage unless a stage is given. The stage log "
        "and the new-card alert work as in the app.",
        cards_create,
        {
            "board": BOARD_P,
            "name": _p("string", "The card's name."),
            "client": _p("string", "The client's name or id (needed on every board except tasks)."),
            "assignee": PERSON_P,
            "reviewer": PERSON_P,
            "due_date": _p("string", "For example 2026-11-03."),
            "stage": _p("string", "The stage to start at."),
            "notes": _p("string", "Notes for the card."),
            "work_link": _p("string", "The link to the work (the board's work link column)."),
        },
        ["board", "name"],
    ),
    "cards.move": _entry(
        "write",
        EVERYONE,
        "Move a card to another stage (the full name, or its number such as '30'). Writes the stage log "
        "and fires the Slack alert, as in the app.",
        cards_move,
        {"board": BOARD_P, "id": ID_P, "stage": _p("string", "The new stage.")},
        ["board", "id", "stage"],
    ),
    "cards.update": _entry(
        "write",
        EVERYONE,
        "Change a card's due date, notes or work link, or one of the board's link and feedback fields "
        "(see 'boards'). Not the stage: use cards.move.",
        cards_update,
        {
            "board": BOARD_P,
            "id": ID_P,
            "due_date": _p("string", "The new due date, or '' to clear it."),
            "notes": _p("string", "The new notes. This replaces them; use cards.note to add a line."),
            "work_link": _p("string", "The link to the work."),
            "fields": _p("object", 'Other fields this board allows, for example {"feedback_notes": "..."}.'),
        },
        ["board", "id"],
    ),
    "cards.note": _entry(
        "write",
        EVERYONE,
        "Add one dated line, with my name, to the end of a card's notes.",
        cards_note,
        {"board": BOARD_P, "id": ID_P, "text": _p("string", "The note.")},
        ["board", "id", "text"],
    ),
    "emails.tick": _entry(
        "write",
        EVERYONE,
        "Tick one email in a flow or campaign calendar on to its next step (To Write, Copy Done, Designed, Built), "
        "or set the step given.",
        emails_tick,
        {
            "id": _p("string", "The email's id (cards.get on its flow or calendar lists them)."),
            "status": _p("string", "The step to set."),
        },
        ["id"],
    ),
    "calls.add": _entry(
        "write",
        EVERYONE,
        "Save a call with a client: title, when, type, recording link, summary, transcript, action items, attendees.",
        calls_add,
        {
            "client": CLIENT_P,
            "title": _p("string", "The call's title."),
            "call_at": _p("string", "When, for example 2026-11-03T14:00:00Z. Default: now."),
            "call_type": _p("string", "Sales, Onboarding, Check-In, Internal or Other."),
            "recording_url": _p("string", "The recording's link."),
            "summary": _p("string", "The summary."),
            "transcript": _p("string", "The transcript."),
            "action_items": _p("string", "The action items."),
            "attendees": _p("string", "Who was on the call."),
        },
        ["client", "title"],
    ),
    "metrics.add": _entry(
        "write",
        EVERYONE,
        "Save a client's report numbers for one day or one week. A second save for the same day or week "
        "changes the numbers given and keeps the rest.",
        metrics_add,
        {
            "client": CLIENT_P,
            "period": _p("string", "'daily' or 'weekly'."),
            "date": _p("string", "The day, or any day in the week (it is saved as that week's Monday)."),
            "values": _p("object", "The numbers, for example {\"leads\": 12}. 'describe_action' lists the names."),
        },
        ["client", "period", "date", "values"],
    ),
    "brain.index": _entry(
        "read",
        EVERYONE,
        "The second brain's INDEX: its areas and their maps. Start here. " + BRAIN_RULE,
        brain_index,
    ),
    "brain.map": _entry(
        "read",
        EVERYONE,
        "One area's map: the notes in that area, under short headings. " + BRAIN_RULE,
        brain_map,
        {"area": _p("string", "The area's folder name (from brain.index), for example 'sales'.")},
        ["area"],
    ),
    "brain.search": _entry(
        "read",
        EVERYONE,
        "Find second brain notes that hold all the words given (20 at most), with the line that matches. " + BRAIN_RULE,
        brain_search,
        {
            "query": _p("string", "The words to look for."),
            "area": _p("string", "Only this area."),
        },
        ["query"],
    ),
    "brain.read": _entry(
        "read",
        EVERYONE,
        "One second brain note in full, by its name (as in a [[link]]) or its path. Raw source files "
        "(raw/...) are not in the connector; a note's Raw: line only names its source. " + BRAIN_RULE,
        brain_read,
        {"note": _p("string", "The note's name, for example 'Unhappy_Client_Call', or its path.")},
        ["note"],
    ),
    "docs.read": _entry(
        "read",
        EVERYONE,
        "One document in full (copy, script, brief: the long texts on a card or a client page), as Markdown, "
        "with its version and word count. Name it by its id, or by board + card + field, or by client + field "
        "for the client page. cards.get and clients.get show each document's first 500 characters.",
        docs_read,
        DOC_PARAMS,
    ),
    "docs.write": _entry(
        "write",
        EVERYONE,
        "Save a document's whole text as Markdown. Give the version docs.read showed (0 if not written yet). "
        "If someone saved since, nothing is saved and you are told to read it again. Client page documents: "
        "Owners and Admins.",
        docs_write,
        dict(
            DOC_PARAMS,
            body_md=_p("string", "The whole new text, in Markdown. It replaces the old text."),
            version=_p("integer", "The version you read with docs.read (0 if it is not written yet)."),
        ),
        ["body_md", "version"],
    ),
    "clients.update": _entry(
        "write",
        ADMINS,
        "Change a client's fields: status, contact, links, people, onboarding stage and the agency fields. "
        "Owners and Admins. Not the Slack channel, the form code or archive (use the OS for those).",
        clients_update,
        {"client": CLIENT_P, "fields": _p("object", 'The fields to change, for example {"status": "Paused"}.')},
        ["client", "fields"],
    ),
}


def load_spec(path: Path = ACTIONS_FILE) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())


class Registry:
    """The actions this agency type offers (mcp_actions.json), with the role checks."""

    def __init__(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        unknown = [a for a in spec.get("actions", []) if a not in ALL]
        if unknown:
            raise ValueError("mcp_actions.json names actions that do not exist: {0}".format(", ".join(unknown)))
        self.entries = {name: ALL[name] for name in spec.get("actions", [])}
        if "metrics.add" in self.entries:
            self.entries["metrics.add"] = dict(
                self.entries["metrics.add"],
                description=self.entries["metrics.add"]["description"]
                + " Daily numbers: {0}. Weekly numbers: {1}.".format(
                    ", ".join(spec.get("metrics", {}).get("daily", [])),
                    ", ".join(spec.get("metrics", {}).get("weekly", [])),
                ),
            )

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self.entries.get((name or "").strip())

    def visible_to(self, role: Optional[str]) -> List[str]:
        """The action names this access level may see. Nobody known: nothing."""
        if role not in EVERYONE:
            return []
        return [n for n, e in self.entries.items() if role in e["roles"]]

    def allowed(self, name: str, role: Optional[str], kind: str) -> bool:
        entry = self.get(name)
        return bool(entry) and role in EVERYONE and entry["kind"] == kind and role in entry["roles"]

    def summarise(self, name: str) -> Dict[str, Any]:
        e = self.entries[name]
        return {
            "name": name,
            "kind": e["kind"],
            "who": sorted(e["roles"]),
            "description": e["description"],
            "params": e["schema"],
            "run_with": "run_read_action" if e["kind"] == "read" else "run_write_action",
        }

    def validate(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Required keys there, no unknown keys, numbers and true/false the right type."""
        schema = self.entries[name]["schema"]
        props, required = schema["properties"], schema["required"]
        params = dict(params or {})
        unknown = sorted(set(params) - set(props))
        if unknown:
            raise ActionError(
                "{0} has no parameter {1}. It takes: {2}.".format(
                    name, ", ".join(unknown), ", ".join(props) or "nothing"
                )
            )
        missing = [k for k in required if params.get(k) in (None, "")]
        if missing:
            raise ActionError("{0} needs {1}.".format(name, ", ".join(missing)))
        for key, value in list(params.items()):
            kind = props[key].get("type")
            if value is None:
                continue
            if kind == "integer":
                try:
                    params[key] = int(value)
                except (TypeError, ValueError):
                    raise ActionError("{0} must be a whole number.".format(key))
            elif kind == "boolean" and not isinstance(value, bool):
                params[key] = str(value).strip().lower() in ("true", "yes", "1")
            elif kind == "object" and not isinstance(value, dict):
                try:
                    params[key] = json.loads(value) if isinstance(value, str) else None
                except ValueError:
                    params[key] = None
                if not isinstance(params[key], dict):
                    raise ActionError('{0} must be an object, for example {{"name": "value"}}.'.format(key))
            elif kind == "string" and not isinstance(value, str):
                params[key] = str(value)
        return params


Handler = Callable[..., Dict[str, Any]]
