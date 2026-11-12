"""Registrars: where sending domains are checked and bought. One small interface, one class per
registrar. Porkbun is built in. To add another registrar, copy the Porkbun class, change the
calls, and add it to REGISTRARS. references/registrar-porkbun.md has every Porkbun call used.

The interface (every method is one or two vendor calls through sending_http.call):

    keys                         the .env keys it reads, and `where` says where to get each one
    check_many(names)            {name: Availability}. Read only. Used by the naming step.
    owned()                      every domain already in the account. Read only.
    balance_usd()                the prepaid credit, or None when the registrar bills a card.
    lookup(domain)               the domain in the account ({} when it is not there). Read only.
    quote(domain)                {available, price, premium, years} for one name. Read only.
    buy(domain, cost_usd, key)   SPENDS. `key` makes a retry replay, never buy twice.
    set_nameservers(domain, ns)  points the domain at the inbox provider.
    set_dns_records(domain, rs)  writes DNS records (for a provider that hands records over).
    add_forward(domain, url)     sends web visits to the client's own site.
    default_ns_suffix            how its own nameservers end (to see when they moved away).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

import sending_http as http
from sending_naming import Availability


class Registrar(object):
    name = "base"
    keys: List[str] = []
    where: Dict[str, str] = {}
    default_ns_suffix = ""

    def check_many(self, names: List[str]) -> Dict[str, Availability]:
        raise NotImplementedError

    def owned(self) -> Set[str]:
        raise NotImplementedError

    def balance_usd(self) -> Optional[float]:
        return None

    def lookup(self, domain: str) -> Dict[str, Any]:
        raise NotImplementedError

    def quote(self, domain: str) -> Dict[str, Any]:
        raise NotImplementedError

    def buy(self, domain: str, cost_usd: float, idempotency_key: str) -> Dict[str, Any]:
        raise NotImplementedError

    def set_nameservers(self, domain: str, nameservers: List[str]) -> Any:
        raise NotImplementedError

    def set_dns_records(self, domain: str, records: List[Dict[str, Any]]) -> Any:
        raise NotImplementedError

    def add_forward(self, domain: str, url: str) -> Any:
        raise NotImplementedError


class Porkbun(Registrar):
    """Porkbun API v3. Buying pays from the account's prepaid credit, not a card."""

    name = "porkbun"
    base = "https://api.porkbun.com/api/json/v3"
    keys = ["PORKBUN_API_KEY", "PORKBUN_SECRET_KEY"]
    where = {"PORKBUN_API_KEY": "porkbun.com, Account, API Access (turn on 'Opt In All Domains' there too)",
             "PORKBUN_SECRET_KEY": "porkbun.com, Account, API Access (shown once, when you make the key)"}
    default_ns_suffix = ".ns.porkbun.com"

    def _auth(self) -> Dict[str, str]:
        return {"apikey": http.key("PORKBUN_API_KEY"), "secretapikey": http.key("PORKBUN_SECRET_KEY")}

    def _post(self, path: str, extra: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
        body = dict(self._auth(), **(extra or {}))
        return http.call("porkbun", "POST", self.base + path, body, headers=headers)

    def check_many(self, names: List[str]) -> Dict[str, Availability]:
        """The bulk check: 25 names a call. A name the registry did not answer is left out
        (unknown is never 'free')."""
        out: Dict[str, Availability] = {}
        for i in range(0, len(names), 25):
            chunk = names[i:i + 25]
            answers = (self._post("/domain/checkDomain", {"domains": chunk}) or {}).get("domains") or {}
            for n in chunk:
                a = answers.get(n)
                if not a:
                    continue
                free = str(a.get("avail", "")).lower() == "yes"
                price = a.get("price")
                out[n] = Availability(free, float(price) if price not in (None, "") else None,
                                      premium=str(a.get("premium", "no")).lower() == "yes",
                                      reason=None if free else "already registered")
        return out

    def owned(self) -> Set[str]:
        out: Set[str] = set()
        start = 0
        while True:
            page = (self._post("/domain/listAll", {"start": str(start)}) or {}).get("domains") or []
            out.update(str(d.get("domain", "")).lower() for d in page)
            if len(page) < 1000:
                return out
            start += 1000

    def balance_usd(self) -> Optional[float]:
        body = http.call("porkbun", "GET", self.base + "/account/balance", headers={
            "X-API-Key": http.key("PORKBUN_API_KEY"), "X-Secret-API-Key": http.key("PORKBUN_SECRET_KEY")})
        return float((body or {}).get("balance") or 0) / 100.0

    def lookup(self, domain: str) -> Dict[str, Any]:
        try:
            return (self._post("/domain/get/" + domain) or {}).get("domain") or {}
        except http.VendorError as e:
            if e.status == 404 or e.code == "DOMAIN_NOT_FOUND":
                return {}
            raise

    def quote(self, domain: str) -> Dict[str, Any]:
        r = (self._post("/domain/checkDomain/" + domain) or {}).get("response") or {}
        return {"available": str(r.get("avail", "")).lower() == "yes",
                "price": float(r.get("price") or 0),
                "premium": str(r.get("premium", "no")).lower() == "yes",
                "years": max(1, int(r.get("minDuration") or 1))}

    def buy(self, domain: str, cost_usd: float, idempotency_key: str) -> Dict[str, Any]:
        """SPENDS. `cost` is whole cents and must equal the quote, or Porkbun refuses."""
        return self._post("/domain/create/" + domain,
                          {"cost": int(round(cost_usd * 100)), "agreeToTerms": "yes", "whoisPrivacy": True},
                          headers={"Idempotency-Key": idempotency_key[:255]})

    def set_nameservers(self, domain: str, nameservers: List[str]) -> Any:
        return self._post("/domain/updateNs/" + domain, {"ns": list(nameservers)})

    def set_dns_records(self, domain: str, records: List[Dict[str, Any]]) -> Any:
        """One create per record. A record that is already there (DUPLICATE_RECORD) is fine,
        so a second run changes nothing. Porkbun warns when its nameservers are not in use:
        then nothing would resolve, so a warning is an error here."""
        for rec in records:
            try:
                r = self._post("/dns/create/" + domain, {"name": rec.get("name", ""), "type": rec["type"],
                                                          "content": rec["content"], "ttl": int(rec.get("ttl") or 600),
                                                          "prio": int(rec.get("prio") or 0)})
            except http.VendorError as e:
                if e.code == "DUPLICATE_RECORD":
                    continue
                raise
            if (r or {}).get("warnings"):
                raise http.VendorError("Porkbun stored the {0} record but it will not resolve: {1}".format(
                    rec["type"], r["warnings"]))
        return True

    def add_forward(self, domain: str, url: str) -> Any:
        have = (self._post("/domain/getUrlForwarding/" + domain) or {}).get("forwards") or []
        if any(str(f.get("location", "")).rstrip("/") == url.rstrip("/") for f in have):
            return True
        return self._post("/domain/addUrlForward/" + domain, {"subdomain": "", "location": url, "type": "permanent",
                                                               "includePath": "no", "wildcard": "no"})


REGISTRARS: Dict[str, Registrar] = {"porkbun": Porkbun()}


def get_registrar(name: Optional[str]) -> Registrar:
    key = str(name or "").strip().lower()
    if key not in REGISTRARS:
        raise ValueError("No registrar named '{0}'. Built in: {1}.".format(name, ", ".join(sorted(REGISTRARS))))
    return REGISTRARS[key]
