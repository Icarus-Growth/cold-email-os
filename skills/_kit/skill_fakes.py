"""A fake database, a fake Slack and fake channels, for the skills' offline tests.

    python3 -m pytest skills          (from the repo root)

The fake database understands the same calls as shared/supabase_client.py (select,
select_all, get, insert, update, upsert, request) and the Data API filter words the
skills use: eq., neq., is.null, not.is.null, in.(a,b), gt., gte., lt., lte., ilike.
"""

from __future__ import annotations

import copy
import itertools
import re
from typing import Any, Dict, List, Optional

_ids = itertools.count(1)


def new_id() -> str:
    return "00000000-0000-4000-8000-{0:012d}".format(next(_ids))


class FakeSlack:
    def __init__(self) -> None:
        self.posts: List[Dict[str, Any]] = []

    def post(self, channel: str, bot_name: str, text: str, blocks: Optional[list] = None,
             thread_ts: Optional[str] = None) -> str:
        self.posts.append({"channel": channel, "bot_name": bot_name, "text": text, "blocks": blocks,
                           "thread_ts": thread_ts})
        return "ts-{0}".format(len(self.posts))

    def call(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True}


class FakeConfig:
    """Every automation channel set up, with the id 'chan-<key>'."""

    KEYS = ("new-tasks", "task-updates", "amendments", "review", "approved", "daily-summary",
            "pipeline-errors", "needs-a-person")

    def channel_id(self, key: str) -> str:
        return "chan-" + key if key in self.KEYS else ""


def _cmp(value: Any, op: str, arg: str) -> bool:
    if op == "is":
        return (value is None) if arg == "null" else str(value).lower() == arg
    if op == "in":
        items = [x.strip().strip('"') for x in arg.strip("()").split(",")]
        return str(value) in items
    if value is None:
        return False
    if op == "eq":
        return str(value).lower() == arg.lower() if isinstance(value, bool) else str(value) == arg
    if op == "neq":
        return str(value) != arg
    if op == "ilike":
        rx = "^" + re.escape(arg).replace("\\*", ".*").replace("%", ".*") + "$"
        return re.match(rx, str(value), re.I) is not None
    try:
        a, b = float(value), float(arg)
    except (TypeError, ValueError):
        a, b = str(value), arg  # type: ignore[assignment]
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}.get(op, False)


def matches(row: Dict[str, Any], filters: Optional[Dict[str, str]]) -> bool:
    for col, rule in (filters or {}).items():
        if col in ("select", "order", "limit", "offset", "on_conflict"):
            continue
        neg = rule.startswith("not.")
        if neg:
            rule = rule[4:]
        op, _, arg = rule.partition(".")
        ok = _cmp(row.get(col), op, arg)
        if ok == neg:
            return False
    return True


class FakeDB:
    def __init__(self, tables: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}
        self.writes: List[tuple] = []
        self.fail_on: Dict[str, Exception] = {}

    def _rows(self, table: str) -> List[Dict[str, Any]]:
        if table in self.fail_on:
            raise self.fail_on[table]
        return self.tables.setdefault(table, [])

    def select(self, table: str, filters: Optional[Dict[str, str]] = None, columns: str = "*",
               order: Optional[str] = None, limit: Optional[int] = None, offset: Optional[int] = None):
        rows = [copy.deepcopy(r) for r in self._rows(table) if matches(r, filters)]
        if order:
            for part in reversed(order.split(",")):
                col, _, way = part.partition(".")
                rows.sort(key=lambda r: (r.get(col) is None, str(r.get(col) or "")), reverse=(way == "desc"))
        rows = rows[offset or 0:]
        return rows[:limit] if limit is not None else rows

    def select_all(self, table: str, filters: Optional[Dict[str, str]] = None, columns: str = "*",
                   order: str = "id", page_size: int = 500, max_pages: int = 20):
        return self.select(table, filters, columns, order)

    def get(self, table: str, row_id: str, columns: str = "*"):
        rows = self.select(table, {"id": "eq." + str(row_id)}, limit=1)
        return rows[0] if rows else None

    def insert(self, table: str, values: Any):
        many = values if isinstance(values, list) else [values]
        out = []
        for v in many:
            row = dict(v)
            row.setdefault("id", new_id())
            self._rows(table).append(row)
            self.writes.append(("insert", table, row["id"]))
            out.append(copy.deepcopy(row))
        return out if isinstance(values, list) else out[0]

    def update(self, table: str, row_id: str, values: Dict[str, Any]):
        for r in self._rows(table):
            if str(r.get("id")) == str(row_id):
                r.update(values)
                self.writes.append(("update", table, row_id))
                return copy.deepcopy(r)
        return {}

    def upsert(self, table: str, values: Any, on_conflict: str):
        many = values if isinstance(values, list) else [values]
        keys = [k.strip() for k in on_conflict.split(",")]
        out = []
        for v in many:
            hit = None
            for r in self._rows(table):
                if all(str(r.get(k)) == str(v.get(k)) for k in keys):
                    hit = r
                    break
            if hit is not None:
                hit.update(v)
                self.writes.append(("update", table, hit.get("id")))
                out.append(copy.deepcopy(hit))
            else:
                out.append(self.insert(table, v))
        return out if isinstance(values, list) else out[0]

    def request(self, method: str, path: str, params: Optional[Dict[str, str]] = None, body: Any = None,
                prefer: Optional[str] = None):
        if method == "GET":
            return self.select(path, params)
        if method == "POST" and params and params.get("on_conflict"):
            return self.upsert(path, body, params["on_conflict"])
        if method == "POST":
            r = self.insert(path, body)
            return r if isinstance(r, list) else [r]
        if method == "PATCH":
            out = []
            for r in self._rows(path):
                if matches(r, params):
                    r.update(body)
                    out.append(copy.deepcopy(r))
            return out
        raise NotImplementedError(method)

    def rpc(self, function: str, args: Optional[Dict[str, Any]] = None):
        raise NotImplementedError(function)
