"""The naming rules for sending domains. Pure: no network, no database.

The rules (config.json holds the lists; references/naming-rules.md says why):

1. Three tiers, tried in order: prefix + brand (trybrand.com), brand + suffix (brandhq.com),
   then prefix + brand + suffix (trybrandhq.com) only when tiers 1 and 2 cannot fill the count.
   Inside a tier, shorter names go first.
2. .com first. Then the same tier 1 and 2 names on .co. Then tier 3.
3. Rejected: longer than 40 characters, a banned part (mega, ultra, grp), or a blocked word
   anywhere in the name, also across the join ("the" + "rapist").
4. Never the client's own domain, never a domain another client uses, never one the agency
   already owns. The caller gives that list as `taken`.
5. A name is proposed only when the registrar says it is free, not premium, and under the
   price ceiling. The caller gives the check as `check_many` (one call for many names).

Styles: "branded" builds from the client's brand, "generic" from neutral root words (so the
domains can outlive the client), "mix" is half each, generic first.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

CONFIG_FILE = Path(__file__).resolve().parents[1] / "config.json"

BRANDED, GENERIC, MIX = "branded", "generic", "mix"
STYLE_WORDS = {
    "branded": BRANDED, "only branded": BRANDED, "brand": BRANDED,
    "generic": GENERIC, "only generic": GENERIC,
    "mix": MIX, "mix of both": MIX, "mixed": MIX, "both": MIX,
}
LEGAL_WORDS = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
               "gmbh", "plc", "pty", "pte", "sa", "srl", "bv", "ag", "llp", "lp"}
TWO_LEVEL_ENDINGS = {"co.uk", "org.uk", "me.uk", "ltd.uk", "com.au", "net.au", "co.nz", "co.za",
                     "com.br", "com.mx", "co.in", "com.sg", "co.jp", "com.cn"}
MAIL_DOMAINS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
                "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com"}


class NamingError(ValueError):
    """The inputs cannot give the names asked for. The message says why, in plain words."""


class Availability(object):
    """What the registrar said about one name."""

    __slots__ = ("available", "price", "premium", "reason")

    def __init__(self, available: bool, price: Optional[float] = None, premium: bool = False,
                 reason: Optional[str] = None) -> None:
        self.available = bool(available)
        self.price = price
        self.premium = bool(premium)
        self.reason = reason


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    return json.loads(Path(path or CONFIG_FILE).read_text())


# --------------------------------------------------------------------------- words


def slugify(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def domain_of(website: Any) -> Optional[str]:
    """'https://www.Acme.com/about' -> 'acme.com'. An email gives its domain. None for blank."""
    raw = str(website or "").strip().lower()
    if not raw or " " in raw:
        return None
    if "@" in raw:
        raw = raw.split("@", 1)[1]
    raw = re.sub(r"^[a-z]+://", "", raw)
    raw = raw.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].split(":", 1)[0]
    if raw.startswith("www."):
        raw = raw[4:]
    return raw if "." in raw else None


def name_part(domain: Optional[str]) -> Optional[str]:
    """The name without its ending: 'acme.co.uk' -> 'acme', 'app.acme.com' -> 'acme'."""
    if not domain:
        return None
    labels = [x for x in domain.split(".") if x]
    if len(labels) < 2:
        return slugify(labels[0]) if labels else None
    if ".".join(labels[-2:]) in TWO_LEVEL_ENDINGS and len(labels) >= 3:
        return slugify(labels[-3])
    return slugify(labels[-2])


def brand_keyword(company_name: Any = None, website: Any = None) -> str:
    """The brand word: the website's name first, else the company name without legal words."""
    from_site = name_part(domain_of(website))
    if from_site:
        return from_site
    words = [w for w in re.findall(r"[a-z0-9]+", str(company_name or "").lower()) if w not in LEGAL_WORDS]
    keyword = "".join(words)
    if not keyword:
        raise NamingError("The client has no website and no company name. Add one, then run again.")
    return keyword


def normalise_style(answer: Any, default: str = BRANDED) -> str:
    key = str(answer or "").strip().lower()
    if not key:
        return default
    if key in STYLE_WORDS:
        return STYLE_WORDS[key]
    raise NamingError("Unknown name style '{0}'. Use branded, generic or mix.".format(answer))


def generic_roots(cfg: Dict[str, Any], seed: Optional[str]) -> List[str]:
    """The generic root words, shuffled the same way every time for one client."""
    roots = list(cfg["generic_roots"])
    random.Random(seed or "sending").shuffle(roots)
    return roots


# --------------------------------------------------------------------------- screening


def blocked_part(sld: str, cfg: Dict[str, Any]) -> Optional[str]:
    """The first blocked word inside `sld` that no safe word covers ('skill' covers 'kill')."""
    text = sld.lower()
    for term in cfg["blocked_parts"]:
        start = text.find(term)
        while start != -1:
            end = start + len(term)
            if not _covered(text, start, end, cfg["safe_words"]):
                return term
            start = text.find(term, start + 1)
    return None


def _covered(text: str, start: int, end: int, safe_words: Sequence[str]) -> bool:
    for safe in safe_words:
        s = text.find(safe)
        while s != -1:
            if s <= start and s + len(safe) >= end:
                return True
            s = text.find(safe, s + 1)
    return False


def screen(sld: str, tld: str, cfg: Dict[str, Any]) -> Optional[str]:
    """Why this name must not be used, or None when it passes every rule."""
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", sld or ""):
        return "letters, numbers and dashes only"
    if len(sld) > int(cfg["max_name_length"]):
        return "longer than {0} characters".format(cfg["max_name_length"])
    for part in cfg["banned_parts"]:
        if part in sld:
            return "has the banned part '{0}'".format(part)
    hit = blocked_part(sld, cfg)
    if hit:
        return "has the blocked word '{0}'".format(hit)
    if tld in cfg["never_tlds"]:
        return "{0} hurts delivery".format(tld)
    if tld not in cfg["tlds"]:
        return "{0} is not an allowed ending".format(tld)
    return None


# --------------------------------------------------------------------------- candidates


def tier_names(keyword: str, tier: int, cfg: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """Every (name, prefix, suffix) of one tier, shortest first, list order breaking ties."""
    kw = slugify(keyword)
    if not kw:
        raise NamingError("The brand word is empty.")
    if tier == 1:
        names = [(p + kw, p, "") for p in cfg["prefixes"]]
    elif tier == 2:
        names = [(kw + s, "", s) for s in cfg["suffixes"]]
    elif tier == 3:
        names = [(p + kw + s, p, s) for p in cfg["prefixes"] for s in cfg["suffixes"]]
    else:
        raise NamingError("The tier must be 1, 2 or 3.")
    order = {n[0]: i for i, n in enumerate(names)}
    return sorted(names, key=lambda n: (len(n[0]), order[n[0]]))


def candidates(keywords: Sequence[str], style: str, cfg: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Every candidate in the order to try: tiers 1+2 on each ending, then tier 3 on each ending.
    Several keywords take turns, so no single root word fills the list."""
    for tier_group in ((1, 2), (3,)):
        for tld in cfg["tlds"]:
            lists = []
            for kw in keywords:
                lists.append([(t, n) for t in tier_group for n in tier_names(kw, t, cfg)])
            depth = max((len(x) for x in lists), default=0)
            for i in range(depth):
                for k, names in enumerate(lists):
                    if i < len(names):
                        tier, (sld, prefix, suffix) = names[i]
                        yield {"domain": sld + tld, "sld": sld, "tld": tld, "tier": tier,
                               "keyword": slugify(keywords[k]), "prefix": prefix, "suffix": suffix, "style": style}


# --------------------------------------------------------------------------- proposal


def propose(count: int, keywords: Sequence[str], style: str, check_many: Callable[[List[str]], Dict[str, Availability]],
            cfg: Dict[str, Any], taken: Set[str], max_per_keyword: Optional[int] = None,
            max_per_affix: Optional[int] = None, batch_size: int = 25) -> Dict[str, Any]:
    """Up to `count` names in one style: screened, not taken, and free at the registrar.
    `taken` grows with each pick, so the other half of a mix can never pick the same name."""
    out: Dict[str, Any] = {"domains": [], "checked": 0, "rejected": []}
    if count <= 0:
        return out
    if not keywords:
        raise NamingError("There are no words to build names from.")
    per_kw: Dict[str, int] = {}
    per_affix: Dict[str, int] = {}
    source = candidates(keywords, style, cfg)
    max_checks = int(cfg.get("max_checks") or 400)
    errors_in_a_row = 0
    done = False

    def affixes(c: Dict[str, Any]) -> List[str]:
        return (["p:" + c["prefix"]] if c["prefix"] else []) + (["s:" + c["suffix"]] if c["suffix"] else [])

    def capped(c: Dict[str, Any], kw_extra: Dict[str, int], affix_extra: Dict[str, int]) -> bool:
        kw = c["keyword"]
        if max_per_keyword is not None and per_kw.get(kw, 0) + kw_extra.get(kw, 0) >= max_per_keyword:
            return True
        if max_per_affix is not None:
            return any(per_affix.get(a, 0) + affix_extra.get(a, 0) >= max_per_affix for a in affixes(c))
        return False

    while len(out["domains"]) < count and not done and out["checked"] < max_checks:
        want = min(batch_size, max(5, 2 * (count - len(out["domains"]))), max_checks - out["checked"])
        batch: List[Dict[str, Any]] = []
        kw_extra: Dict[str, int] = {}
        affix_extra: Dict[str, int] = {}
        while len(batch) < want:
            c = next(source, None)
            if c is None:
                done = True
                break
            if capped(c, kw_extra, affix_extra):
                continue
            why = screen(c["sld"], c["tld"], cfg)
            if not why and c["domain"] in taken:
                why = "already used, or the client's own domain"
            if why:
                out["rejected"].append({"domain": c["domain"], "reason": why})
                continue
            batch.append(c)
            kw_extra[c["keyword"]] = kw_extra.get(c["keyword"], 0) + 1
            for a in affixes(c):
                affix_extra[a] = affix_extra.get(a, 0) + 1
        if not batch:
            break
        names = [c["domain"] for c in batch]
        out["checked"] += len(names)
        try:
            answers = check_many(names)
            errors_in_a_row = 0
        except Exception as e:  # noqa: BLE001 - the registrar's own failure, not "taken"
            errors_in_a_row += 1
            out["rejected"] += [{"domain": n, "reason": "the check failed: {0}".format(e)} for n in names]
            if errors_in_a_row >= 3:
                raise NamingError("The registrar check failed 3 times in a row. Last error: {0}".format(e))
            continue
        ceilings = cfg.get("max_first_year_price_usd") or {}
        for c in batch:
            if len(out["domains"]) >= count:
                break
            if capped(c, {}, {}):
                continue
            a = answers.get(c["domain"])
            why = None
            if a is None:
                why = "the registrar did not answer"
            elif not a.available:
                why = a.reason or "not free"
            elif a.premium:
                why = "a premium name"
            elif a.price is not None and c["tld"] in ceilings and a.price > float(ceilings[c["tld"]]):
                why = "costs {0:.2f} USD, over the {1} USD limit".format(a.price, ceilings[c["tld"]])
            if why:
                out["rejected"].append({"domain": c["domain"], "reason": why})
                continue
            picked = dict(c, price=a.price)
            out["domains"].append(picked)
            taken.add(c["domain"])
            per_kw[c["keyword"]] = per_kw.get(c["keyword"], 0) + 1
            for x in affixes(c):
                per_affix[x] = per_affix.get(x, 0) + 1
    return out


def split_for_style(count: int, style: str) -> Dict[str, int]:
    if style == BRANDED:
        return {BRANDED: count, GENERIC: 0}
    if style == GENERIC:
        return {BRANDED: 0, GENERIC: count}
    return {BRANDED: count // 2, GENERIC: count - count // 2}


def propose_for_client(count: int, style: str, check_many: Callable[[List[str]], Dict[str, Availability]],
                       cfg: Dict[str, Any], taken: Set[str], company_name: Any = None, website: Any = None,
                       brand: Optional[str] = None, seed: Optional[str] = None) -> Dict[str, Any]:
    """The whole naming step for one client. Raises NamingError when the count cannot be met,
    so a plan is never made short."""
    if count <= 0:
        raise NamingError("The number of domains must be 1 or more.")
    style = normalise_style(style, cfg.get("default_style") or BRANDED)
    own = domain_of(website)
    if own:
        taken.add(own)
    taken.update(d.lower() for d in cfg.get("never_use") or [])
    counts = split_for_style(count, style)
    keyword = None
    b = {"domains": [], "checked": 0, "rejected": []}
    g = {"domains": [], "checked": 0, "rejected": []}
    if counts[BRANDED]:
        keyword = slugify(brand) if brand else brand_keyword(company_name, website)
        b = propose(counts[BRANDED], [keyword], BRANDED, check_many, cfg, taken)
    if counts[GENERIC]:
        g = propose(counts[GENERIC], generic_roots(cfg, seed), GENERIC, check_many, cfg, taken,
                    max_per_keyword=int(cfg["generic_max_per_root"]), max_per_affix=int(cfg["generic_max_per_affix"]))
    bl, gl, merged = list(b["domains"]), list(g["domains"]), []
    while bl or gl:
        if gl:
            merged.append(gl.pop(0))
        if bl:
            merged.append(bl.pop(0))
    result = {"domains": merged, "checked": b["checked"] + g["checked"], "rejected": b["rejected"] + g["rejected"],
              "style": style, "brand": keyword}
    if len(merged) < count:
        raise NamingError("Only {0} of {1} names are free ({2} checked). Use --style mix or generic, or give "
                          "another brand word with --brand.".format(len(merged), count, result["checked"]))
    return result


def taken_domains(db: Any) -> Set[str]:
    """Every domain no new plan may use: every sending domain of every client, each client's
    own website and email domain, and the old comma list on the client row. Read only."""
    taken: Set[str] = set()
    try:
        rows = db.select_all("sending_domains", columns="domain")
    except Exception as e:  # noqa: BLE001
        raise NamingError("The sending_domains table cannot be read ({0}). Run the database update that "
                          "adds it, then run again.".format(str(e)[:120]))
    taken.update(str(r.get("domain") or "").lower() for r in rows if r.get("domain"))
    for c in db.select_all("clients", columns="id,website,contact_email,sending_domains"):
        for d in (domain_of(c.get("website")), domain_of(c.get("contact_email"))):
            if d and d not in MAIL_DOMAINS:
                taken.add(d)
        for d in str(c.get("sending_domains") or "").replace(";", ",").split(","):
            d = domain_of(d.strip())
            if d:
                taken.add(d)
    return taken


def unchecked(names: Iterable[str]) -> Dict[str, Availability]:
    """The 'check' for --offline: every name passes, marked unchecked."""
    return {n: Availability(True, None, reason="unchecked") for n in names}


def find_client(db: Any, ref: Any) -> Dict[str, Any]:
    """One client by row id or by name (case does not count). Stops on none or on two or more."""
    ref = str(ref or "").strip()
    if not ref:
        raise NamingError("Say which client: its name or its row id.")
    if re.fullmatch(r"[0-9a-fA-F-]{36}", ref):
        row = db.get("clients", ref)
        if row:
            if row.get("archived_at"):
                raise NamingError("{0} is archived. Restore the client in the OS first.".format(
                    row.get("client_name") or ref))
            return row
    rows = db.select("clients", {"client_name": "ilike." + ref.replace("*", ""), "archived_at": "is.null"}, limit=5)
    if not rows:
        raise NamingError("No client named '{0}'. Check the name in the OS, or use the client's row id.".format(ref))
    if len(rows) > 1:
        raise NamingError("{0} clients match '{1}': {2}. Use the row id.".format(
            len(rows), ref, ", ".join("{0} ({1})".format(r.get("client_name"), r.get("id")) for r in rows)))
    return rows[0]
