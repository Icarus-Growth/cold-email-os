"""Inbox providers: who makes the inboxes on a sending domain. One small interface; Inboxing
(Outlook) and ScaledMail (Google) are built in. references/ has every call each one uses.
To add a provider, copy the closest class, change the calls, and add it to PROVIDERS.

The interface. `run` is the set-up run (client name, registrar, warm-up tool, live or dry);
`row` is the sending_domains row; `inboxes` are its sending_inboxes rows.

    kind                          google or outlook
    keys, where                   the .env keys it reads, and where to get each one
    dns_mode                      who sets DNS (SPF, DKIM, DMARC, forwarding):
                                    "nameservers"   the provider hosts the DNS. We point the
                                                    domain's nameservers at it (nameservers()).
                                    "provider_sets" the provider's staff connect the domain
                                                    themselves. We wait until the nameservers move.
                                    "records"       the provider gives records (dns_records());
                                                    we write them, and the forward, at the registrar.
    one_order_for_many            True = one order for every domain of the run (order() gets them all)
    order(run, items)             SPENDS. {domain: {"ref": ...} or an error}. Adopts an order that
                                  already exists, so it never orders twice.
    nameservers(run, row)         the nameservers to set ([] = not given yet)
    dns_records(run, row)         [{type, name, content, prio?}] for dns_mode "records"
    sets_own_nameservers(run)     True when the provider changes them at the registrar itself
    status(run, row)              ("active" | "waiting" | "failed", words)
    hand_over(run, row)           sends the inboxes to the warm-up tool (safe to repeat)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import sending_http as http


class InboxProvider(object):
    name = "base"
    kind = ""
    keys: List[str] = []
    where: Dict[str, str] = {}
    dns_mode = "nameservers"
    one_order_for_many = False

    def order(self, run: Any, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        raise NotImplementedError

    def nameservers(self, run: Any, row: Dict[str, Any]) -> List[str]:
        return []

    def dns_records(self, run: Any, row: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def sets_own_nameservers(self, run: Any) -> bool:
        return False

    def status(self, run: Any, row: Dict[str, Any]) -> Tuple[str, str]:
        raise NotImplementedError

    def hand_over(self, run: Any, row: Dict[str, Any]) -> None:
        return None


class Inboxing(InboxProvider):
    """Microsoft 365 (Outlook) inboxes. One POST /domains makes the domain AND its inboxes. It
    hosts the DNS (SPF, DKIM, DMARC, the forward) and gives the nameservers to point at."""

    name = "inboxing"
    kind = "outlook"
    base = "https://v2.inboxing.com/api/v2"
    keys = ["INBOXING_API_KEY"]
    where = {"INBOXING_API_KEY": "Inboxing, Settings, API",
             "INBOXING_REGISTRAR_CREDENTIAL_ID": "optional: Inboxing, Settings, Registrars (then Inboxing sets the "
                                                 "nameservers itself)"}
    dns_mode = "nameservers"

    def _h(self) -> Dict[str, str]:
        return {"X-API-Key": http.key("INBOXING_API_KEY")}

    def _find(self, domain_or_id: str) -> Optional[Dict[str, Any]]:
        try:
            return http.call("inboxing", "GET", "{0}/domains/{1}".format(self.base, http.quote(domain_or_id)),
                             headers=self._h())
        except http.VendorError as e:
            if e.status == 404:
                return None
            raise

    def _credential(self) -> str:
        import os
        return (os.environ.get("INBOXING_REGISTRAR_CREDENTIAL_ID") or "").strip()

    def order(self, run: Any, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for item in items:
            row, inboxes = item["row"], item["inboxes"]
            try:
                found = self._find(row["domain"])  # POST /domains has no idempotency key: look first
                if found:
                    out[row["domain"]] = {"ref": found.get("id"), "note": "the order was already there"}
                    continue
                slots = http.call("inboxing", "GET", self.base + "/slots", headers=self._h()) or {}
                if int(((slots.get("system") or {}).get("can_provision")) or 0) < 1:
                    raise http.VendorNotReady("Inboxing has no free domain slot. Buying a slot is a spend outside "
                                              "this plan: free or buy one in Inboxing, then run again.")
                body: Dict[str, Any] = {
                    "domain": row["domain"], "user_count": len(inboxes),
                    "names": [{"first_name": i.get("first_name") or "", "last_name": i.get("last_name") or "",
                               "email_prefix": i["address"].split("@", 1)[0]} for i in inboxes],
                }
                if row.get("forward_to"):
                    body.update(redirect_type="REGULAR", redirect_url=row["forward_to"])
                if self._credential():
                    body["registrar_credential_id"] = self._credential()
                made = http.call("inboxing", "POST", self.base + "/domains", body, headers=self._h()) or {}
                out[row["domain"]] = {"ref": made.get("id")}
            except Exception as e:  # noqa: BLE001 - one domain's failure never stops the others
                out[row["domain"]] = e
        return out

    def nameservers(self, run: Any, row: Dict[str, Any]) -> List[str]:
        found = self._find(row.get("provider_ref") or row["domain"]) or {}
        return list(found.get("nameservers") or [])

    def sets_own_nameservers(self, run: Any) -> bool:
        return bool(self._credential())

    def status(self, run: Any, row: Dict[str, Any]) -> Tuple[str, str]:
        s = http.call("inboxing", "GET", "{0}/domains/{1}/status".format(
            self.base, http.quote(row.get("provider_ref") or row["domain"])), headers=self._h()) or {}
        state = str(s.get("status") or "").lower()
        if state == "active":
            return "active", "Inboxing says active"
        if state == "failed":
            return "failed", "Inboxing set-up failed: {0}".format(s.get("failure_reason") or "no reason given")
        return "waiting", "Inboxing status is '{0}' (it takes 4 to 6 hours)".format(state or "unknown")

    def hand_over(self, run: Any, row: Dict[str, Any]) -> None:
        """Upload through a platform connection to the client's warm-up workspace, warm-up on.
        'skip_verified' makes a second upload safe."""
        conn = run.tool.connection(run.workspace(), run.client_name)
        label = "{0} - {1}".format(conn["label"], run.client_name)
        listing = http.call("inboxing", "GET", self.base + "/platform-connections", headers=self._h())
        items = listing if isinstance(listing, list) else (listing or {}).get("data") or []
        conn_id = next((c.get("id") for c in items if c.get("platform") == conn["platform"]
                        and str(c.get("name", "")).strip().lower() == label.lower()), None)
        if not conn_id:
            made = http.call("inboxing", "POST", self.base + "/platform-connections", {
                "platform": conn["platform"], "name": label, "username": conn["username"],
                "password": conn["password"], "api_key": conn["api_key"], "workspace_id": conn["workspace_id"],
                "daily_limit": 2, "warmup_daily_limit": 2}, headers=self._h()) or {}
            conn_id = made.get("id")
        if not conn_id:
            raise http.VendorError("Inboxing gave no connection id for the warm-up tool.")
        http.call("inboxing", "POST", "{0}/domains/{1}/upload".format(
            self.base, http.quote(row.get("provider_ref") or row["domain"])),
            {"platform_connection_id": conn_id, "enable_warmup": True, "sync_tags": True, "skip_verified": True},
            headers=self._h(), not_ready=(400, 403, 409))


class ScaledMail(InboxProvider):
    """Google Workspace inboxes. One order for every domain of the run. ScaledMail's staff sign in
    to the registrar to connect each domain (DNS, forward) and to the warm-up tool to upload the
    inboxes, so the order carries both logins. There is no DNS call."""

    name = "scaledmail"
    kind = "google"
    base = "https://server.scaledmail.com/api/v1"
    keys = ["SCALEDMAIL_API_KEY", "SCALEDMAIL_ORGANIZATION_ID", "REGISTRAR_WEB_USERNAME", "REGISTRAR_WEB_PASSWORD"]
    where = {"SCALEDMAIL_API_KEY": "ScaledMail, Settings, API",
             "SCALEDMAIL_ORGANIZATION_ID": "ScaledMail, Settings (the workspace id)",
             "REGISTRAR_WEB_USERNAME": "the user name you sign in to your registrar's website with "
                                       "(ScaledMail's staff connect each domain there)",
             "REGISTRAR_WEB_PASSWORD": "the password you sign in to your registrar's website with"}
    dns_mode = "provider_sets"
    one_order_for_many = True
    registrar_links = {"porkbun": ("Porkbun", "https://porkbun.com")}

    def _h(self) -> Dict[str, str]:
        return {"Authorization": "Bearer " + http.key("SCALEDMAIL_API_KEY")}

    def _org(self) -> str:
        return http.key("SCALEDMAIL_ORGANIZATION_ID")

    def _listed(self) -> Dict[str, Dict[str, Any]]:
        body = http.call("scaledmail", "GET", "{0}/domains?organization_id={1}".format(self.base, http.quote(self._org())),
                         headers=self._h()) or {}
        return {str(d.get("domain", "")).lower(): d for d in body.get("domains") or []}

    def _body(self, run: Any, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        conn = run.tool.connection(run.workspace(), run.client_name)
        label, link = self.registrar_links.get(run.registrar.name, (run.registrar.name, ""))
        domains = []
        for item in items:
            d: Dict[str, Any] = {"domain": item["row"]["domain"], "aliases": [
                {"first_name": i.get("first_name") or "", "last_name": i.get("last_name") or i.get("first_name") or "",
                 "alias": i["address"].split("@", 1)[0]} for i in item["inboxes"]]}
            if item["row"].get("forward_to"):
                d["redirect"] = item["row"]["forward_to"]
            domains.append(d)
        return {"tag": ("agency-" + run.client_slug)[:20],
                "providers": {"google": {"mailboxes_per_domain": len(items[0]["inboxes"]), "domains": domains}},
                "sequencer": {"provider": conn["label"], "username": conn["username"], "password": conn["password"],
                              "link": conn["link"], "workspace": conn["workspace_name"]},
                "hosting": {"provider": label, "username": http.key("REGISTRAR_WEB_USERNAME"),
                            "password": http.key("REGISTRAR_WEB_PASSWORD"), "link": link}}

    def _place(self, run: Any, items: List[Dict[str, Any]]) -> str:
        url = "{0}/create-custom-order?organization_id={1}&provider=other".format(self.base, http.quote(self._org()))
        r = http.call("scaledmail", "POST", url, self._body(run, items), headers=self._h()) or {}
        return str(r.get("order_id") or r.get("id") or r.get("payment_id") or "")

    def order(self, run: Any, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        listed = self._listed()
        todo = []
        for item in items:
            found = listed.get(item["row"]["domain"].lower())
            if found:
                out[item["row"]["domain"]] = {"ref": found.get("id"), "note": "the order was already there"}
            else:
                todo.append(item)
        if not todo:
            return out
        try:
            ref = self._place(run, todo)
            for item in todo:
                out[item["row"]["domain"]] = {"ref": ref}
            return out
        except Exception as e:  # noqa: BLE001
            if len(todo) == 1:
                out[todo[0]["row"]["domain"]] = e
                return out
        for item in todo:  # the big order was refused: one order each, so one bad domain sinks only itself
            try:
                out[item["row"]["domain"]] = {"ref": self._place(run, [item])}
            except Exception as e:  # noqa: BLE001
                out[item["row"]["domain"]] = e
        return out

    def status(self, run: Any, row: Dict[str, Any]) -> Tuple[str, str]:
        found = self._listed().get(row["domain"].lower())
        if not found:
            return "waiting", "ScaledMail does not list the domain yet"
        state = str(found.get("status") or "")
        if state.lower() != "active":
            return "waiting", "ScaledMail status is '{0}' (it takes 1 to 3 days)".format(state or "unknown")
        url = "{0}/mailboxes/{1}?organization_id={2}".format(self.base, http.quote(str(found.get("id"))),
                                                             http.quote(self._org()))
        boxes = (http.call("scaledmail", "GET", url, headers=self._h()) or {}).get("mailboxes") or []
        if not boxes:
            return "waiting", "ScaledMail says active but lists no inboxes yet"
        return "active", "ScaledMail says active, {0} inboxes".format(len(boxes))


PROVIDERS: Dict[str, InboxProvider] = {"inboxing": Inboxing(), "scaledmail": ScaledMail()}


def get_provider(name: Optional[str]) -> InboxProvider:
    key = str(name or "").strip().lower()
    if key not in PROVIDERS:
        raise ValueError("No inbox provider named '{0}'. Built in: {1}.".format(name, ", ".join(sorted(PROVIDERS))))
    return PROVIDERS[key]
