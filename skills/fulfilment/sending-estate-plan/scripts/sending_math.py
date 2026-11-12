"""The sizing sum, the inbox names and the warm-up rules. Pure: no network, no database.

The sum (config.json holds every number):

    daily volume        = monthly volume / sending days a month             (round up)
    daily per kind      = daily volume x split percent                      (Google, Outlook)
    inboxes needed      = daily per kind / sends per inbox a day            (round up)
    inboxes with spare  = inboxes needed x (100 + spare buffer percent) / 100 (round up)
    domains             = inboxes with spare / inboxes per domain           (round up)
    inboxes             = domains x inboxes per domain                      (full domains only)

Warm-up: an inbox warms before any cold email. Google starts at 5 warm-up emails a day and adds
5 a day up to 50, then drops to 30 after 14 days. Outlook stays at 2 a day. Warm-up never stops.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

CONFIG_FILE = Path(__file__).resolve().parents[1] / "config.json"
KINDS = ("google", "outlook")
KIND_LABEL = {"google": "Google", "outlook": "Outlook"}


class PlanError(ValueError):
    """The plan cannot be made. The message says why, in plain words."""


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    return json.loads(Path(path or CONFIG_FILE).read_text())


def _up(a: int, b: int) -> int:
    """a / b, rounded up, in whole numbers."""
    return -(-a // b)


def as_volume(value: Any) -> int:
    """The monthly volume as a whole number above 0, or a plain error."""
    try:
        v = int(str(value).replace(",", "").replace("_", "").strip())
    except (TypeError, ValueError):
        raise PlanError("The monthly send volume '{0}' is not a whole number.".format(value))
    if v <= 0:
        raise PlanError("The monthly send volume must be more than 0.")
    return v


def estate_counts(monthly_volume: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """How many domains and inboxes of each kind a monthly volume needs."""
    volume = as_volume(monthly_volume)
    days = int(cfg["sending_days_per_month"])
    if not 1 <= days <= 31:
        raise PlanError("sending_days_per_month in config.json must be 1 to 31.")
    buffer = int(cfg.get("spare_buffer_percent") or 0)
    split = {k: int((cfg.get("split_percent") or {}).get(k) or 0) for k in KINDS}
    if sum(split.values()) != 100:
        raise PlanError("split_percent in config.json must add up to 100 (now {0}).".format(sum(split.values())))
    daily = _up(volume, days)
    kinds: Dict[str, Any] = {}
    left = daily
    active = [k for k in KINDS if split[k] > 0]
    for i, kind in enumerate(active):
        kind_daily = left if i == len(active) - 1 else min(left, _up(daily * split[kind], 100))
        left -= kind_daily
        per_day = int(cfg["sends_per_inbox_per_day"][kind])
        per_domain = int(cfg["inboxes_per_domain"][kind])
        provider = cfg["providers"][kind]
        allowed = (cfg.get("allowed_inboxes_per_domain") or {}).get(provider)
        if per_day <= 0 or per_domain <= 0:
            raise PlanError("sends_per_inbox_per_day and inboxes_per_domain must be more than 0.")
        if allowed and per_domain not in allowed:
            raise PlanError("{0} sells {1} inboxes per domain only, not {2}. Change inboxes_per_domain.".format(
                provider, ", ".join(map(str, allowed)), per_domain))
        needed = _up(kind_daily, per_day)
        with_spare = _up(needed * (100 + buffer), 100)
        domains = _up(with_spare, per_domain)
        kinds[kind] = {"daily_volume": kind_daily, "sends_per_inbox_per_day": per_day, "inboxes_needed": needed,
                       "inboxes_with_spare": with_spare, "inboxes_per_domain": per_domain, "domains": domains,
                       "inboxes": domains * per_domain, "provider": provider}
    return {
        "monthly_volume": volume, "sending_days": days, "daily_volume": daily, "spare_buffer_percent": buffer,
        "kinds": kinds,
        "total_domains": sum(k["domains"] for k in kinds.values()),
        "total_inboxes": sum(k["inboxes"] for k in kinds.values()),
        "monthly_capacity": sum(k["inboxes"] * k["sends_per_inbox_per_day"] for k in kinds.values()) * days,
    }


# --------------------------------------------------------------------------- warm-up


def warmup_profile(kind: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    if kind not in (cfg.get("warmup") or {}):
        raise PlanError("config.json has no warm-up rule for '{0}'.".format(kind))
    return dict(cfg["warmup"][kind])


def warmup_on_day(kind: str, day: int, cfg: Dict[str, Any]) -> int:
    """Warm-up emails per inbox on `day` (0 = the first day)."""
    p = warmup_profile(kind, cfg)
    if p.get("step_down_after_days") is not None and day >= int(p["step_down_after_days"]):
        return int(p["after_step_down_per_day"])
    if p.get("ramp_per_day"):
        return int(min(p["max_per_day"], p["start_per_day"] + p["ramp_per_day"] * day))
    return int(p["max_per_day"])


def warm_days(cfg: Dict[str, Any], enterprise: bool = False) -> int:
    return int(cfg["warm_days_enterprise"] if enterprise else cfg["warm_days_before_sending"])


def ready_date(today: date, cfg: Dict[str, Any], enterprise: bool = False) -> date:
    return today + timedelta(days=int(cfg.get("setup_days") or 0) + warm_days(cfg, enterprise))


def warmup_words(kind: str, cfg: Dict[str, Any]) -> str:
    p = warmup_profile(kind, cfg)
    if p.get("ramp_per_day"):
        text = "{0} a day, +{1} a day up to {2}".format(p["start_per_day"], p["ramp_per_day"], p["max_per_day"])
    else:
        text = "{0} a day, flat".format(p["max_per_day"])
    if p.get("step_down_after_days") is not None:
        text += ", then {0} a day after {1} days".format(p["after_step_down_per_day"], p["step_down_after_days"])
    return text


# --------------------------------------------------------------------------- senders and inbox names

_NO_NAME = re.compile(r"^(no preference|none|n/?a|you decide|up to you|either|any|anyone|not sure|tbd|no)\b", re.I)
_TITLES = {"ceo", "cto", "coo", "cfo", "cmo", "cro", "founder", "cofounder", "co-founder", "president", "director",
           "head", "vp", "svp", "evp", "manager", "partner", "owner", "md", "principal", "chief", "officer", "lead",
           "sales", "marketing", "partnerships", "growth", "of", "the", "senior", "sr", "jr", "mr", "mrs", "ms", "dr"}


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _tokens(chunk: str) -> List[str]:
    return [t for t in re.findall(r"[A-Za-z][A-Za-z'\-]*", _ascii(chunk)) if t.lower().strip("'-") not in _TITLES]


def _proper(token: str) -> str:
    token = token.strip("'-")
    return token.capitalize() if (token.islower() or token.isupper()) else token[:1].upper() + token[1:]


def _sender(tokens: Sequence[str]) -> Optional[Dict[str, str]]:
    if not tokens:
        return None
    return {"first_name": _proper(tokens[0]), "last_name": _proper(tokens[-1]) if len(tokens) > 1 else ""}


def parse_senders(text: Any, fallback_name: Any = None) -> List[Dict[str, str]]:
    """'Jane Doe, CEO and Sam Lee, Head of Sales' -> two senders. Titles are dropped. 'No
    preference' or an empty answer falls back to `fallback_name` (the person who filled the form)."""
    fallback = _sender(_tokens(str(fallback_name or "")))
    raw = str(text or "").strip()
    found: List[Dict[str, str]] = []
    if raw and not _NO_NAME.match(raw):
        for line in re.split(r"[\n;]+", raw):
            for piece in re.split(r"\s+(?:and|&)\s+|/|\+", line):
                s = _sender(_tokens(re.split(r",|\s[-–—]\s|\(", piece, maxsplit=1)[0]))
                if s:
                    found.append(s)
    out: List[Dict[str, str]] = []
    for s in found:
        if not s["last_name"] and fallback and fallback["last_name"]:
            s = {"first_name": s["first_name"], "last_name": fallback["last_name"]} \
                if fallback["first_name"].lower() == s["first_name"].lower() else dict(fallback)
        if s not in out:
            out.append(s)
    if not out and fallback:
        out = [fallback]
    if not out:
        raise PlanError("No sender name. Give one with --senders \"Jane Doe\", or fill in who the emails come "
                        "from on the client's onboarding form.")
    return out


def _clean(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _ascii(value).lower())


def name_variants(sender: Dict[str, str]) -> List[str]:
    """Inbox name parts for one sender, most natural first."""
    f, l = _clean(sender.get("first_name", "")), _clean(sender.get("last_name", ""))
    if not f:
        raise PlanError("A sender needs a first name.")
    if not l:
        return [f, "hi." + f, "hello." + f, f + ".team"]
    return [f, f + "." + l, f + l, f[0] + "." + l, f + l[0], f[0] + l, l + "." + f, f + "_" + l, f + "-" + l,
            l + f, l[0] + "." + f, f + "." + l[0], l + f[0], f[0] + "_" + l]


def inbox_names(senders: Sequence[Dict[str, str]], count: int) -> List[Dict[str, str]]:
    """`count` inboxes for one domain. Senders take turns; each name part is used once, then
    numbered ('jane.doe2', 'jane.doe3'). Every address on the domain is different."""
    if count <= 0:
        return []
    if not senders:
        raise PlanError("At least one sender is needed.")
    variants = [name_variants(s) for s in senders]
    out: List[Dict[str, str]] = []
    used: set = set()

    def add(i: int, local: str) -> None:
        if len(out) < count and local not in used:
            used.add(local)
            out.append({"local": local, "first_name": senders[i]["first_name"], "last_name": senders[i]["last_name"]})

    for j in range(max(len(v) for v in variants)):
        for i, vs in enumerate(variants):
            if j < len(vs):
                add(i, vs[j])
    n = 2
    while len(out) < count:
        for i, vs in enumerate(variants):
            add(i, "{0}{1}".format(vs[1] if len(vs) > 1 else vs[0], n))
        n += 1
    return out


def assign_senders(domains: Sequence[str], senders: Sequence[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """One sender for each domain, taking turns, so each sender gets about the same number of
    domains. (A domain with many inboxes, like Outlook's 49, uses every sender instead.)"""
    n = len(senders)
    return {d: [dict(senders[(i + i // n) % n])] for i, d in enumerate(domains)}


# --------------------------------------------------------------------------- money


def cost_estimate(domain_prices: Sequence[Optional[float]], domains: Sequence[str], kind: Dict[str, Any],
                  cfg: Dict[str, Any]) -> Dict[str, float]:
    """An estimate only, shown in the approval message: domains for one year, then inboxes a month."""
    est = cfg.get("cost_estimate") or {}
    fallback = est.get("domain_year_usd_if_unknown") or {}
    year = 0.0
    for price, d in zip(domain_prices, domains):
        tld = "." + d.split(".", 1)[1] if "." in d else ""
        year += float(price) if price is not None else float(fallback.get(tld) or 0)
    rate = (est.get("inbox_month_usd") or {}).get(kind["provider"]) or {}
    units = kind["inboxes"] if rate.get("per") == "inbox" else kind["domains"]
    month = float(rate.get("usd") or 0) * units
    return {"domains_first_year_usd": round(year, 2), "inboxes_month_usd": round(month, 2),
            "first_month_usd": round(year + month, 2), "inbox_price_known": bool(rate.get("usd"))}
