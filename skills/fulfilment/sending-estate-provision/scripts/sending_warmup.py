"""Warm-up tools: where the inboxes warm up (and later send). One small interface; PlusVibe is
built in. references/warmup-plusvibe.md has every call used. To add another tool (for example
one your agency already sends from), copy the PlusVibe class and add it to TOOLS.

The interface:

    keys, where                     the .env keys it reads, and where to get each one
    ensure_workspace(name)          the client's own workspace id: found by name, made if missing
    accounts(workspace, domain)     [{id, email}] of the inboxes on one domain that have arrived
    start(workspace, ids, profile)  sets the warm-up numbers and turns warm-up on
    step_down(workspace, ids, n)    lowers the daily warm-up to n (Google, after 14 days)
    connection(workspace)           the login an inbox provider uses to upload inboxes here
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import sending_http as http


class WarmupTool(object):
    name = "base"
    keys: List[str] = []
    where: Dict[str, str] = {}

    def ensure_workspace(self, name: str) -> str:
        raise NotImplementedError

    def accounts(self, workspace: str, domain: str) -> List[Dict[str, str]]:
        raise NotImplementedError

    def start(self, workspace: str, ids: List[str], profile: Dict[str, Any]) -> None:
        raise NotImplementedError

    def step_down(self, workspace: str, ids: List[str], per_day: int) -> None:
        raise NotImplementedError

    def connection(self, workspace: str, workspace_name: str) -> Dict[str, Any]:
        raise NotImplementedError


class PlusVibe(WarmupTool):
    name = "plusvibe"
    base = "https://api.plusvibe.ai/api/v1"
    link = "https://app.plusvibe.ai"
    keys = ["PLUSVIBE_API_KEY", "PLUSVIBE_LOGIN_EMAIL", "PLUSVIBE_LOGIN_PASSWORD"]
    where = {"PLUSVIBE_API_KEY": "PlusVibe, Settings, API Access (use the account key, not a workspace key)",
             "PLUSVIBE_LOGIN_EMAIL": "the email you sign in to PlusVibe with (inbox providers upload inboxes as you)",
             "PLUSVIBE_LOGIN_PASSWORD": "the password you sign in to PlusVibe with"}

    def _h(self) -> Dict[str, str]:
        return {"x-api-key": http.key("PLUSVIBE_API_KEY")}

    def ensure_workspace(self, name: str) -> str:
        """There is no 'find by name', and 'add' is not safe to repeat: always list first."""
        listing = http.call("plusvibe", "GET", self.base + "/authenticate", headers=self._h()) or {}
        spaces = list(listing.get("workspaces") or [])
        for ws in spaces:
            if str(ws.get("name", "")).strip().lower() == name.strip().lower():
                return str(ws.get("_id") or ws.get("id"))
        if not spaces:
            raise http.VendorError("The PlusVibe key reaches no workspace. Use the account key.")
        made = http.call("plusvibe", "POST", self.base + "/workspaces/add",
                         {"workspace_id": str(spaces[0].get("_id") or spaces[0].get("id")), "workspace_name": name},
                         headers=self._h()) or {}
        wid = str(made.get("_id") or made.get("id") or "")
        if not wid:
            raise http.VendorError("PlusVibe made no workspace for '{0}'.".format(name))
        return wid

    def accounts(self, workspace: str, domain: str) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        skip = 0
        while True:
            url = "{0}/account/list?{1}".format(self.base, http.query({"workspace_id": workspace, "limit": 100,
                                                                        "skip": skip}))
            body = http.call("plusvibe", "GET", url, headers=self._h())
            page = list((body.get("accounts") if isinstance(body, dict) else body) or [])
            for a in page:
                email = str(a.get("email", "")).lower()
                if email.endswith("@" + domain.lower()):
                    out.append({"id": str(a.get("_id") or a.get("id") or ""), "email": email})
            if len(page) < 100:
                return out
            skip += 100

    def start(self, workspace: str, ids: List[str], profile: Dict[str, Any]) -> None:
        if profile.get("ramp_per_day"):
            fields = {"warmup_max_daily_limit": int(profile["max_per_day"]),
                      "warmup_initial_daily_limit": int(profile["start_per_day"]),
                      "warmup_pace_increment": int(profile["ramp_per_day"]), "bulk_warmup_is_slow_rampup": "yes"}
        else:
            fields = {"warmup_max_daily_limit": int(profile["max_per_day"]),
                      "warmup_initial_daily_limit": int(profile["max_per_day"]),
                      "warmup_pace_increment": 1, "bulk_warmup_is_slow_rampup": "no"}
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            http.call("plusvibe", "PUT", self.base + "/account/bulk-update",
                      dict(fields, workspace_id=workspace, ids=chunk), headers=self._h())
            http.call("plusvibe", "PATCH", self.base + "/account/bulk-update-warmup",
                      {"workspace_id": workspace, "ids": chunk, "warmup_status": "ACTIVE"}, headers=self._h())

    def step_down(self, workspace: str, ids: List[str], per_day: int) -> None:
        for i in range(0, len(ids), 100):
            http.call("plusvibe", "PUT", self.base + "/account/bulk-update",
                      {"workspace_id": workspace, "ids": ids[i:i + 100], "warmup_max_daily_limit": int(per_day),
                       "bulk_warmup_is_slow_rampup": "no"}, headers=self._h())

    def connection(self, workspace: str, workspace_name: str) -> Dict[str, Any]:
        return {"platform": "plusvibe", "label": "PlusVibe", "link": self.link, "workspace_id": workspace,
                "workspace_name": workspace_name, "username": http.key("PLUSVIBE_LOGIN_EMAIL"),
                "password": http.key("PLUSVIBE_LOGIN_PASSWORD"), "api_key": http.key("PLUSVIBE_API_KEY")}


TOOLS: Dict[str, WarmupTool] = {"plusvibe": PlusVibe()}


def get_tool(name: Optional[str]) -> WarmupTool:
    key = str(name or "").strip().lower()
    if key not in TOOLS:
        raise ValueError("No warm-up tool named '{0}'. Built in: {1}.".format(name, ", ".join(sorted(TOOLS))))
    return TOOLS[key]
