"""Fake Slack, a fake database and the repo's real rule files, for the offline tests.

python3 -m pytest apps/os/automations/tests      (from the repo root)
"""

from __future__ import annotations

import copy
import itertools
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

AUTOMATIONS = Path(__file__).resolve().parents[1]
REPO = AUTOMATIONS.parents[2]
MIGRATIONS = REPO / "apps/os/backend/supabase/migrations"
for p in (str(AUTOMATIONS), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from common import Config, load_json  # noqa: E402
from shared.slack_notify import SlackError, clean_bot_name  # noqa: E402
from shared.supabase_client import Supabase, SupabaseError  # noqa: E402

OS = "https://os.example.com"


def config() -> Config:
    """The repo's own alert_rules.json, with test ids filled into channels.json."""
    channels = load_json(AUTOMATIONS / "channels.json")
    for key, entry in channels["channels"].items():
        entry["id"] = "chan-" + key
    return Config(load_json(AUTOMATIONS / "alert_rules.json"), channels)


# --------------------------------------------------------------------------- the database files


def sql_text() -> str:
    return "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))


def ladders() -> Dict[str, List[str]]:
    """{table: [stage labels in order]} read from the change files."""
    sql = sql_text()
    enums = {
        m.group(1): re.findall(r"'([^']+)'", m.group(2))
        for m in re.finditer(r"create type public\.(\w+) as enum \((.*?)\);", sql, re.S)
    }
    out = {}
    for m in re.finditer(r"create table public\.(\w+) \((.*?)\n\);", sql, re.S):
        col = re.search(r"\n\s*(stage|onboarding_stage)\s+public\.(\w+)", m.group(2))
        if col and col.group(2) in enums:
            out[m.group(1)] = enums[col.group(2)]
    return out


def columns(table: str) -> List[str]:
    sql = sql_text()
    cols: List[str] = []
    m = re.search(r"create table public\.{0} \((.*?)\n\);".format(table), sql, re.S)
    if m:
        cols += re.findall(r"^\s+(\w+)\s+\w", m.group(1), re.M)
    for alter in re.finditer(r"alter table public\.{0}\s+(.*?);".format(table), sql, re.S):
        cols += re.findall(r"add column (?:if not exists )?(\w+)", alter.group(1))
    return cols


# --------------------------------------------------------------------------- fake database


class FakeDB(Supabase):
    """Rows in memory. Inherits the real paging (select_all) and get()."""

    #: Tables whose stage column the stand-in stage log trigger watches (0002).
    LOGGED = {"tasks", "campaigns", "inbox_batches", "creatives", "videos", "flows", "campaign_calendars"}

    def __init__(self, tables: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        super().__init__("https://db.example.com", "test-key")
        self.tables = copy.deepcopy(tables or {})
        self.reads: List[Dict[str, Any]] = []
        self.updates: List[Any] = []
        self.inserts: List[Any] = []
        self.rpcs: List[Any] = []
        self._ids = itertools.count(1)

    @staticmethod
    def _ok(row: Dict[str, Any], filters: Dict[str, str]) -> bool:
        for col, f in filters.items():
            op, _, val = f.partition(".")
            have = row.get(col)
            if op == "eq" and str(have).lower() != val.lower():
                return False
            if op == "ilike" and val.strip("*").lower() not in str(have or "").lower():
                return False
            if op == "is" and val == "null" and have is not None:
                return False
            if f == "not.is.null" and have is None:
                return False
            if op == "gt":
                if have is None or datetime.fromisoformat(str(have).replace("Z", "+00:00")) <= datetime.fromisoformat(
                    val
                ):
                    return False
        return True

    def select(self, table, filters=None, columns="*", order=None, limit=None, offset=None):
        self.reads.append({"table": table, "limit": limit, "offset": offset})
        rows = [r for r in self.tables.get(table, []) if self._ok(r, filters or {})]
        if order:
            rows.sort(key=lambda r: str(r.get(order.split(".")[0])), reverse=order.endswith(".desc"))
        start = offset or 0
        rows = rows[start : start + limit] if limit is not None else rows[start:]
        if columns != "*":
            keep = [c.strip() for c in columns.split(",")]
            rows = [{c: r.get(c) for c in keep} for r in rows]
        return copy.deepcopy(rows)

    def _log_stage(self, table: str, before: Dict[str, Any], after: Dict[str, Any], values: Dict[str, Any]) -> None:
        """What the database's stage log trigger does (0002, 0012): a row for a new card or a new stage,
        with the mover named in the same change."""
        col = "onboarding_stage" if table == "clients" else "stage"
        if table not in self.LOGGED and table != "clients":
            return
        if before and before.get(col) == after.get(col):
            return
        if col not in after:
            return
        self.tables.setdefault("stage_log", []).append(
            {
                "id": next(self._ids),
                "board": table,
                "record_id": after.get("id"),
                "client_id": after.get("id") if table == "clients" else after.get("client_id"),
                "from_stage": before.get(col) if before else None,
                "to_stage": after.get(col),
                "changed_by_id": values.get(col + "_changed_by_id"),
                "changed_at": datetime.now().isoformat(),
            }
        )

    def update(self, table, row_id, values):
        self.updates.append((table, row_id, values))
        for r in self.tables.get(table, []):
            if str(r.get("id")) == str(row_id):
                before = dict(r)
                r.update(values)
                self._log_stage(table, before, r, values)
                return dict(r)
        return {}

    def insert(self, table, values):
        self.inserts.append((table, values))
        row = dict(values)
        row.setdefault("id", "new-{0}".format(next(self._ids)))
        self.tables.setdefault(table, []).append(row)
        self._log_stage(table, {}, row, values)
        return dict(row)

    def rpc(self, function, args=None):
        """Stand-ins for the database's document functions (contract 0013)."""
        args = args or {}
        self.rpcs.append((function, args))
        docs = self.tables.setdefault("documents", [])
        if function == "open_document":
            key = (args["p_client"], args["p_board"], args["p_card"], args["p_field"])
            for d in docs:
                if (d["client_id"], d.get("board"), d.get("card_id"), d["field_key"]) == key:
                    return dict(d)
            row = {"id": "doc-{0}".format(next(self._ids)), "client_id": key[0], "board": key[1], "card_id": key[2],
                   "field_key": key[3], "body_md": "", "word_count": 0, "version": 1, "updated_by": None,
                   "archived_at": None}  # fmt: skip
            docs.append(row)
            return dict(row)
        if function == "save_document":
            row = next(d for d in docs if d["id"] == args["p_id"])
            if args["p_version"] != row["version"]:
                raise SupabaseError('POST rpc/save_document failed (400): {"message":"document_conflict"}')
            versions = self.tables.setdefault("document_versions", [])
            versions.append({k: row[k] for k in ("version", "body_md", "word_count")} | {"document_id": row["id"]})
            row.update(body_md=args["p_body_md"], word_count=args["p_word_count"], version=row["version"] + 1,
                       updated_by=args.get("p_saved_by"), updated_at=datetime.now().isoformat())  # fmt: skip
            return row["version"]
        raise AssertionError("no stand-in for rpc " + function)

    def upsert(self, table, values, on_conflict):
        keys = on_conflict.split(",")
        for r in self.tables.get(table, []):
            if all(str(r.get(k)) == str(values.get(k)) for k in keys):
                r.update(values)
                return dict(r)
        return self.insert(table, values)


# --------------------------------------------------------------------------- fake Slack


class FakeSlack:
    def __init__(self) -> None:
        self.posts: List[Dict[str, Any]] = []
        self.calls: List[Any] = []
        self.fail_channels: set = set()
        self.taken_names: set = set()
        self.users_by_email: Dict[str, str] = {}
        self._ts = itertools.count(1)

    def post(self, channel, bot_name, text, blocks=None, thread_ts=None):
        clean_bot_name(bot_name)
        if channel in self.fail_channels:
            raise SlackError("chat.postMessage failed: channel_not_found", "channel_not_found")
        ts = "100.{0}".format(next(self._ts))
        self.posts.append(
            {"channel": channel, "bot_name": bot_name, "text": text, "blocks": blocks, "thread_ts": thread_ts, "ts": ts}
        )
        return ts

    def call(self, method, payload):
        self.calls.append((method, payload))
        if method == "conversations.create":
            if payload["name"] in self.taken_names:
                raise SlackError("conversations.create failed: name_taken", "name_taken")
            return {"channel": {"id": "new-" + payload["name"], "name": payload["name"]}}
        if method == "users.lookupByEmail":
            if payload["email"] not in self.users_by_email:
                raise SlackError("users.lookupByEmail failed: users_not_found", "users_not_found")
            return {"user": {"id": self.users_by_email[payload["email"]]}}
        if method == "conversations.open":
            return {"channel": {"id": "dm-" + payload["users"]}}
        return {"ok": True}

    def in_channel(self, key: str) -> List[Dict[str, Any]]:
        return [p for p in self.posts if p["channel"] == "chan-" + key]


# --------------------------------------------------------------------------- sample rows

TEAM = [
    {
        "id": "t-owner",
        "full_name": "Olive Owner",
        "email": "owner@example.com",
        "access": "Owner",
        "status": "Active",
        "slack_user_id": "UOWNER",
    },
    {
        "id": "t-maker",
        "full_name": "Max Maker",
        "email": "max@example.com",
        "access": "Member",
        "status": "Active",
        "slack_user_id": "UMAKER",
    },
    {
        "id": "t-am",
        "full_name": "Ana Manager",
        "email": "ana@example.com",
        "access": "Admin",
        "status": "Active",
        "slack_user_id": "UANA",
    },
    {
        "id": "t-noslack",
        "full_name": "Nia Noslack",
        "email": "nia@example.com",
        "access": "Member",
        "status": "Active",
        "slack_user_id": None,
    },
]
CLIENT = {
    "id": "c-1",
    "client_name": "Example Client A",
    "account_manager_id": "t-am",
    "form_code": "abc123",
    "drive_folder_url": "https://drive.example.com/a",
    "slack_channel_id": None,
}
SETTINGS = {
    "id": 1,
    "os_url": OS,
    "onboarding_url": "onboarding.example.com",
    "agency_name": "Your Agency",
    "time_zone": "Europe/London",
    "daily_summary_hour": 8,
    "stuck_after_days": 3,
}


def world(**extra: List[Dict[str, Any]]) -> FakeDB:
    tables = {"team": TEAM, "clients": [CLIENT], "settings": [SETTINGS]}
    tables.update(extra)
    return FakeDB(tables)
