"""
The one way Python code in this repo reads and writes the database.

It talks to the Supabase Data API with the secret key, so it skips the team-only
rules. Use it only in server jobs (the Modal app) and local scripts, never in a
browser.

    from shared.supabase_client import Supabase

    db = Supabase()                       # reads SUPABASE_URL and SUPABASE_SECRET_KEY
    card = db.get("tasks", "<row id>")
    rows = db.select("team", {"status": "eq.Active"}, order="full_name")
    every = db.select_all("stage_log", {"changed_at": "gt.2026-10-26T08:00:00Z"})
    db.update("clients", "<row id>", {"slack_channel_id": "<channel id>"})

Filters use the Data API's own words: "eq.<value>", "gt.<value>", "is.null",
"in.(a,b)". `select_all` reads in pages of at most 500 rows and stops after 20 pages,
so no job ever reads a table in one go.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

PAGE_SIZE = 500
MAX_PAGES = 20


class SupabaseError(RuntimeError):
    """The Data API said no, or the address or key is missing."""


def load_dotenv(path: str = ".env") -> None:
    """Put the values from a local .env file into the environment, for local scripts.
    Values already set are kept. Never prints a value."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if key.strip() and value:
                os.environ.setdefault(key.strip(), value)


class Supabase:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None, timeout: int = 30) -> None:
        self.url = (url or os.environ.get("SUPABASE_URL") or "").rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SECRET_KEY") or ""
        self.timeout = timeout
        if not self.url or not self.key:
            raise SupabaseError("SUPABASE_URL and SUPABASE_SECRET_KEY must both be set")

    # ------------------------------------------------------------------ low level

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, str]] = None,
        body: Any = None,
        prefer: Optional[str] = None,
    ) -> Any:
        url = "{0}/rest/v1/{1}".format(self.url, path)
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="(),.:*")
        headers = {
            "apikey": self.key,
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")[:300]
            raise SupabaseError("{0} {1} failed ({2}): {3}".format(method, path, e.code, detail))
        except urllib.error.URLError as e:
            raise SupabaseError("{0} {1} could not reach the database: {2}".format(method, path, e.reason))
        return json.loads(raw) if raw else None

    # ------------------------------------------------------------------ reads

    def select(
        self,
        table: str,
        filters: Optional[Dict[str, str]] = None,
        columns: str = "*",
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params = {"select": columns}
        params.update(filters or {})
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset:
            params["offset"] = str(offset)
        return self.request("GET", table, params) or []

    def select_all(
        self,
        table: str,
        filters: Optional[Dict[str, str]] = None,
        columns: str = "*",
        order: str = "id",
        page_size: int = PAGE_SIZE,
        max_pages: int = MAX_PAGES,
    ) -> List[Dict[str, Any]]:
        """Every matching row, read in pages. Stops after `max_pages` pages."""
        page_size = min(page_size, PAGE_SIZE)
        rows: List[Dict[str, Any]] = []
        for page in range(max_pages):
            batch = self.select(table, filters, columns, order, limit=page_size, offset=page * page_size)
            rows.extend(batch)
            if len(batch) < page_size:
                break
        return rows

    def get(self, table: str, row_id: str, columns: str = "*") -> Optional[Dict[str, Any]]:
        rows = self.select(table, {"id": "eq." + str(row_id)}, columns, limit=1)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ writes

    def insert(self, table: str, values: Dict[str, Any]) -> Dict[str, Any]:
        rows = self.request("POST", table, body=values, prefer="return=representation")
        return rows[0] if rows else {}

    def update(self, table: str, row_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        rows = self.request("PATCH", table, {"id": "eq." + str(row_id)}, body=values, prefer="return=representation")
        return rows[0] if rows else {}

    def upsert(self, table: str, values: Dict[str, Any], on_conflict: str) -> Dict[str, Any]:
        """Add the row, or change the row that has the same `on_conflict` columns. Columns
        not in `values` are kept."""
        rows = self.request(
            "POST",
            table,
            {"on_conflict": on_conflict},
            body=values,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0] if rows else {}

    def rpc(self, function: str, args: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("POST", "rpc/" + function, body=args or {})
