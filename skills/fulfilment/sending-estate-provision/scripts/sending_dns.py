"""DNS reads for the set-up: where a domain's nameservers point, and the auth gate (SPF, DKIM,
DMARC, MX) that must pass before any warm-up starts. references/auth-records-gate.md says why.

Lookups use Google Public DNS over HTTPS (dns.google/resolve), so nothing extra is installed.
Read only. They go through sending_http.call, so a dry run and the tests never reach the network.
"""

from __future__ import annotations

from typing import Any, Dict, List

import sending_http as http

DOH = "https://dns.google/resolve"
TYPES = {"A": 1, "NS": 2, "CNAME": 5, "MX": 15, "TXT": 16}
DKIM_SELECTORS = ("default", "google", "selector1", "selector2")
SPF_INCLUDE = {"google": "include:_spf.google.com", "outlook": "include:spf.protection.outlook.com"}


def lookup(name: str, rtype: str) -> List[str]:
    """The answers for one name and type, lower case, without the end dot. [] when none."""
    body = http.call("dns", "GET", "{0}?{1}".format(DOH, http.query({"name": name, "type": rtype})),
                     retries_on_429=1, timeout=15)
    want = TYPES.get(rtype.upper())
    out = []
    for a in (body or {}).get("Answer") or []:
        if want is not None and a.get("type") != want:
            continue
        out.append(str(a.get("data", "")).replace('" "', "").strip().strip('"').lower().rstrip("."))
    return out


def nameservers(domain: str) -> List[str]:
    return sorted(set(lookup(domain, "NS")))


def check_auth(domain: str, kind: str) -> Dict[str, Any]:
    """The gate: SPF that names the inbox provider, a DKIM key, a DMARC record and an MX record.
    Microsoft 365 puts its DKIM key behind a CNAME; that counts."""
    spf = next((t for t in lookup(domain, "TXT") if t.startswith("v=spf1")), "")
    want = SPF_INCLUDE.get(kind)
    selector = ""
    for s in DKIM_SELECTORS:
        name = "{0}._domainkey.{1}".format(s, domain)
        if any("v=dkim1" in t or "p=" in t for t in lookup(name, "TXT")) or lookup(name, "CNAME"):
            selector = s
            break
    dmarc = next((t for t in lookup("_dmarc." + domain, "TXT") if t.startswith("v=dmarc1")), "")
    policy = ""
    for part in dmarc.split(";"):
        part = part.strip()
        if part.startswith("p="):
            policy = part[2:]
    result = {"spf": bool(spf) and (want is None or want in spf), "dkim": bool(selector), "dmarc": bool(dmarc),
              "mx": bool(lookup(domain, "MX")), "dkim_selector": selector, "dmarc_policy": policy}
    result["missing"] = [k.upper() for k in ("spf", "dkim", "dmarc", "mx") if not result[k]]
    return result
