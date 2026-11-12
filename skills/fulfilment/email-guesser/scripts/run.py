"""Email guesser: finds the work email of each contact that has a name and a company domain,
by testing the likely address patterns with the cheap verifier (MillionVerifier). It never
writes an untested guess as the answer: the email column is filled only when a check proved
it, and the status, the evidence and the checks used are written next to it.
Run it from the repo root. Reads .env; never prints a key.

    python3 skills/fulfilment/email-guesser/scripts/run.py --client "Acme Dental"
    python3 skills/fulfilment/email-guesser/scripts/run.py --client "Acme Dental" --live

1. Contacts to do: no guess_checked_at yet. A contact that already has an email gets one check.
2. Per company domain: free checks first (a free-mail domain, no mail server). Then one test
   address that cannot exist. If it comes back good, the domain accepts any address
   (catch-all): the cheap check is only guessing there, so no more cheap checks are spent. The
   ranked candidates are saved for the catch-all-verifier.
3. One resolved colleague shows the company's pattern. A pattern already proved for this
   domain goes first. Else the first person is the pathfinder: the patterns are tried in order
   of how common they are, and the first good one sets the pattern for the others.
4. Checks stop at the first good address. "None valid" (every candidate invalid) is a real
   result, and it is written as one.
5. At most 500 contacts a batch. Each answer is written at once, so a crash starts again at the
   next contact with no answer.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import sys
from pathlib import Path

for _up in Path(__file__).resolve().parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
import skillkit  # noqa: E402

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import unicodedata  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: E402

SKILL = "email-guesser"
SKILL_DIR = Path(__file__).resolve().parents[1]
KEY = "MILLIONVERIFIER_API_KEY"
WHERE = {KEY: "app.millionverifier.com, sign in, API (left menu), API key"}
NEEDS = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "SLACK_BOT_TOKEN", KEY]
MV_URL = "https://api.millionverifier.com/api/v3/"
DOH_URL = "https://dns.google/resolve"


# --------------------------------------------------------------------------- shared block
# The same block is in each list-building skill, so each skill folder works on its own.

APPROVAL_BOARD = "tasks"
APPROVAL_STAGE = "30 - In Review"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class VendorError(RuntimeError):
    """The outside tool did not answer. The rows are left as they were, so the next run tries again."""


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """config.json, without the "_about" notes."""
    p = Path(path) if path else SKILL_DIR / "config.json"
    data = json.loads(p.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_client(db: Any, client: Any) -> Dict[str, Any]:
    """The client row, from its exact name (any case) or its row id. A plain error if not one."""
    text = str(client or "").strip()
    if not text:
        raise ValueError("Say which client: give its name or its row id.")
    if UUID_RE.match(text):
        row = db.get("clients", text)
        rows = [row] if row else []
    else:
        rows = db.select("clients", {"client_name": "ilike." + text.replace("*", "")}, limit=5)
    if not rows:
        raise ValueError("No client is named '{0}'. Check the name on the Clients screen, "
                         "or use the search-client skill.".format(text))
    if len(rows) > 1:
        raise ValueError("More than one client is named '{0}'. Use the row id.".format(text))
    return rows[0]


def domain_of(text: Any) -> str:
    """'https://www.Acme.example.com/about?x=1' -> 'acme.example.com'. '' if none. Pure."""
    t = str(text or "").strip().lower()
    if "@" in t:
        t = t.rsplit("@", 1)[1]
    t = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", t).split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    t = t[4:] if t.startswith("www.") else t
    t = t.strip(".")
    return t if "." in t and re.match(r"^[a-z0-9.\-]+$", t) else ""


def quoted_in(values: List[str]) -> str:
    """A Data API 'in' filter: in.("a","b")."""
    return 'in.({0})'.format(",".join('"{0}"'.format(str(v).replace('"', "")) for v in values))


def spend_gate(ctx: skillkit.Context, client: Dict[str, Any], needed: int, unit: str, what: str,
               cfg: Dict[str, Any], spent_since: Callable[[str], int]) -> int:
    """How much this run may spend. Under the limit in config.json it goes ahead. Above it, a
    PERSON must approve a card first: the skill makes the card in '30 - In Review' and asks
    in the review channel, then stops (NotApproved). The next run reads the approval from the
    stage log and spends at most what was approved, less what was spent since."""
    limit = int(cfg.get("approval_above", 0))
    if needed <= limit:
        return needed
    db = ctx.db
    prefix = "Approve spend: {0} for {1}".format(SKILL, client["client_name"])
    found = db.select(APPROVAL_BOARD, {"client_id": "eq." + client["id"], "task_name": "ilike." + prefix + "*",
                                       "archived_at": "is.null"}, order="created_at.desc", limit=1)
    task = found[0] if found else None
    settings = ctx.settings()
    if task:
        m = re.search(r"up to ([\d,]+) ", task.get("task_name") or "")
        approved = int(m.group(1).replace(",", "")) if m else 0
        fact = skillkit.approval(db, APPROVAL_BOARD, task["id"], APPROVAL_STAGE)
        if fact:
            left = approved - spent_since(str(fact.get("changed_at") or ""))
            if left >= needed:
                return left
            task = None  # used up: ask again on a new card
        elif approved >= needed:
            raise skillkit.NotApproved(
                "Waiting for approval. A person must move the card '{0}' from '{1}' to '100 - Complete'. {2}".format(
                    task["task_name"], APPROVAL_STAGE, skillkit.card_link(settings, APPROVAL_BOARD, task["id"])).strip())
    name = "{0} (up to {1:,} {2})".format(prefix, needed, unit)
    lines = ["What: {0}.".format(what),
             "Cost: up to {0:,} {1}.".format(needed, unit),
             "Your limit without approval (config.json): {0:,} {1}.".format(limit, unit)]
    fields = {"task_name": name, "client_id": client["id"], "stage": APPROVAL_STAGE, "notes": "\n".join(lines)}
    if task:
        db.update(APPROVAL_BOARD, task["id"], fields)
    else:
        fields["created_at"] = now_iso()
        task = db.insert(APPROVAL_BOARD, fields)
    link = skillkit.card_link(settings, APPROVAL_BOARD, task["id"])
    skillkit.ask_for_approval(ctx, "Spend needs approval: {0} for {1}".format(SKILL, client["client_name"]),
                              lines, link)
    raise skillkit.NotApproved(
        "This run needs up to {0:,} {1}, above your limit of {2:,}. I asked for approval in the review "
        "channel. A person approves by moving the card '{3}' to '100 - Complete'. Then run this again.".format(
            needed, unit, limit, name))


# --------------------------------------------------------------------------- names and patterns

FREE_MAIL = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "hotmail.co.uk", "outlook.com",
    "live.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com",
    "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com", "tiktok.com", "youtube.com",
    "linktr.ee", "calendly.com", "wixsite.com", "squarespace.com", "godaddysites.com",
})
TITLES = frozenset({"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "rev"})
SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "phd", "md", "mba", "cpa", "esq", "dds", "dmd"})
PARTICLES = frozenset({"van", "von", "de", "del", "della", "der", "den", "di", "da", "dos", "la", "le", "st"})

# The patterns, most common first. f = first name, l = last name.
PATTERNS: List[Tuple[str, Callable[[str, str], str]]] = [
    ("first.last", lambda f, l: f + "." + l),
    ("first", lambda f, l: f),
    ("firstlast", lambda f, l: f + l),
    ("flast", lambda f, l: f[0] + l),
    ("first_last", lambda f, l: f + "_" + l),
    ("f.last", lambda f, l: f[0] + "." + l),
    ("firstl", lambda f, l: f + l[0]),
    ("last", lambda f, l: l),
    ("last.first", lambda f, l: l + "." + f),
    ("lastfirst", lambda f, l: l + f),
    ("lastf", lambda f, l: l + f[0]),
    ("first-last", lambda f, l: f + "-" + l),
    ("fl", lambda f, l: f[0] + l[0]),
]
PATTERN_IDS = [p for p, _ in PATTERNS]


def _slug(token: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFKD", token or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", folded.lower())


def split_name(full_name: str) -> Tuple[str, str]:
    """'Dr. Jane van der Berg Jr.' -> ('jane', 'vanderberg'). "O'Brien" -> 'obrien'. Pure."""
    tokens = [t for t in re.split(r"[\s,]+", full_name or "") if _slug(t)]
    tokens = [t for t in tokens if _slug(t) not in TITLES and _slug(t) not in SUFFIXES]
    if not tokens:
        return "", ""
    first = _slug(tokens[0])
    rest = [_slug(t) for t in tokens[1:]]
    if not rest:
        return first, ""
    tail = [rest[-1]]
    for t in reversed(rest[:-1]):
        if t in PARTICLES:
            tail.insert(0, t)
        else:
            break
    return first, "".join(tail)


def contact_name(row: Dict[str, Any]) -> str:
    return (row.get("full_name") or " ".join(x for x in (row.get("first_name"), row.get("last_name")) if x) or "").strip()


def pattern_of(email: str, full_name: str) -> str:
    """Which pattern turns this person's name into this address, or "". Pure."""
    first, last = split_name(full_name)
    local = (email or "").split("@")[0].lower()
    if not first or not local:
        return ""
    for pid, build in PATTERNS:
        if (last or pid == "first") and build(first, last or first) == local:
            return pid
    return ""


def candidates(full_name: str, domain: str, first_patterns: List[str], cap: int) -> List[Dict[str, str]]:
    """The likely addresses, best first: a pattern proved for this domain, then the common ones. Pure."""
    first, last = split_name(full_name)
    if not first:
        return []
    order = [p for p in first_patterns if p in PATTERN_IDS] + [p for p in PATTERN_IDS if p not in first_patterns]
    build = dict(PATTERNS)
    out, seen = [], set()
    for pid in order:
        if not last and pid != "first":
            continue
        local = build[pid](first, last)
        email = "{0}@{1}".format(local, domain)
        if len(local) >= 2 and email not in seen:
            seen.add(email)
            out.append({"email": email, "pattern": pid})
    return out[:max(1, cap)]


# --------------------------------------------------------------------------- outside tools (one function each)


def cheap_check(email: str, key: str, timeout: int = 30) -> str:
    """One MillionVerifier check: ok, catch_all, invalid, unknown, disposable or error.
    The tests replace this function."""
    q = urllib.parse.urlencode({"api": key, "email": email, "timeout": 20})
    try:
        with urllib.request.urlopen(MV_URL + "?" + q, timeout=timeout) as r:
            data = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise VendorError("MillionVerifier said {0}".format(e.code))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise VendorError("MillionVerifier could not be reached: {0}".format(e))
    if data.get("error"):
        raise VendorError("MillionVerifier: {0}".format(str(data["error"])[:200]))
    return str(data.get("result") or "unknown")


def has_mail_server(domain: str, timeout: int = 10) -> Optional[bool]:
    """True if the domain has an MX record, False if it has none, None if the lookup failed.
    Free: a public DNS lookup over HTTPS. The tests replace this function."""
    q = urllib.parse.urlencode({"name": domain, "type": "MX"})
    try:
        with urllib.request.urlopen(DOH_URL + "?" + q, timeout=timeout) as r:
            data = json.loads(r.read().decode() or "{}")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if data.get("Status") == 3:
        return False
    if data.get("Status") != 0:
        return None
    return any(a.get("type") == 15 for a in data.get("Answer") or [])


# --------------------------------------------------------------------------- one company domain


def result(status: str, evidence: str, email: Optional[str] = None, pattern: Optional[str] = None,
           cands: Optional[List[Dict[str, str]]] = None, credits: int = 0, catch_all: bool = False,
           source: Optional[str] = None) -> Dict[str, Any]:
    verdict = {"valid": "send", "invalid": "skip"}.get(status)  # verdict words: send, risky, skip
    return {"email": email, "email_pattern": pattern, "email_status": status, "email_evidence": evidence[:500],
            "email_candidates": cands or None, "catch_all": catch_all, "guess_credits": credits,
            "final_verdict": verdict, "email_source": source}


def guess_domain(domain: str, people: List[Dict[str, Any]], known: str, cfg: Dict[str, Any],
                 check: Callable[[str], str], mx: Callable[[str], Optional[bool]]) -> Dict[str, Dict[str, Any]]:
    """Every contact at one domain -> {contact id: columns to write}. Pure apart from `check` and `mx`.
    A VendorError goes up: then nothing at this domain is written."""
    out: Dict[str, Dict[str, Any]] = {}
    cap = int(cfg["max_candidates"])
    if domain in FREE_MAIL:
        for p in people:
            out[p["id"]] = result("skipped", "{0} is a free mail domain, not the company's own.".format(domain))
        return out
    if mx(domain) is False:
        for p in people:
            out[p["id"]] = result("none", "{0} has no mail server (no MX record). No address there can work. "
                                          "None valid.".format(domain))
        return out
    probe_email = "zz-{0}@{1}".format(secrets.token_hex(6), domain)
    probe = check(probe_email)
    probe_credit = 1
    domain_catch_all = probe in ("ok", "catch_all")
    learned = known
    # Contacts with an email first (their check can show the pattern), then the others.
    people = sorted(people, key=lambda p: 0 if p.get("email") else 1)

    def catch_all_answer(p: Dict[str, Any], why: str, credits: int) -> Dict[str, Any]:
        given = (p.get("email") or "").strip().lower()
        cands = [{"email": given, "pattern": pattern_of(given, contact_name(p)) or "given"}] if given else \
            candidates(contact_name(p), domain, [learned] if learned else [], int(cfg["deep_candidates"]))
        return result("catch-all", "{0} The cheap check only guesses on a catch-all domain. {1} candidate(s) are "
                                   "saved for the catch-all-verifier.".format(why, len(cands)),
                      cands=cands, credits=credits, catch_all=True, source="given" if given else None)

    for p in people:
        name = contact_name(p)
        credits = probe_credit
        probe_credit = 0  # the test address is paid once, by the first contact
        given = (p.get("email") or "").strip().lower()
        if not given and not split_name(name)[0]:
            out[p["id"]] = result("skipped", "No name, so there is nothing to guess from.", credits=credits)
            continue
        if domain_catch_all:
            out[p["id"]] = catch_all_answer(p, "The domain accepts any address: a test address that cannot exist "
                                               "came back '{0}'.".format(probe), credits)
            continue
        if given:
            r = check(given)
            credits += 1
            pid = pattern_of(given, name)
            if r == "ok":
                learned = learned or pid
                out[p["id"]] = result("valid", "Cheap check (MillionVerifier): ok.", given, pid or None,
                                      credits=credits, source="given")
            elif r in ("invalid", "disposable"):
                out[p["id"]] = result("invalid", "Cheap check (MillionVerifier): {0}.".format(r), given, pid or None,
                                      credits=credits, source="given")
            elif r == "catch_all":
                out[p["id"]] = catch_all_answer(p, "Cheap check (MillionVerifier): catch_all.", credits)
            else:
                out[p["id"]] = result("unknown", "Cheap check (MillionVerifier): {0}. Not proved.".format(r), given,
                                      pid or None, cands=[{"email": given, "pattern": pid or "given"}],
                                      credits=credits, source="given")
            continue
        cands = candidates(name, domain, [learned] if learned else [], cap)
        unknown: List[Dict[str, str]] = []
        catch_alls = 0
        found = None
        for cand in cands:
            r = check(cand["email"])
            credits += 1
            if r == "ok":
                found = cand
                break
            if r == "catch_all":
                catch_alls += 1
                if catch_alls >= int(cfg["catch_all_after"]):
                    domain_catch_all = True
                    break
            elif r not in ("invalid", "disposable"):
                unknown.append(cand)
        if found:
            via = "the pattern proved by a colleague" if learned and found["pattern"] == learned else \
                "pattern {0} of {1} tried".format(cands.index(found) + 1, len(cands))
            learned = learned or found["pattern"]
            out[p["id"]] = result("valid", "Cheap check (MillionVerifier): ok, {0}.".format(via), found["email"],
                                  found["pattern"], credits=credits, source="guessed")
        elif domain_catch_all:
            out[p["id"]] = catch_all_answer(p, "{0} candidates came back 'catch_all'.".format(catch_alls), credits)
        elif unknown:
            out[p["id"]] = result("unknown", "No address proved real. {0} came back unknown; the rest invalid. "
                                             "Not an answer yet.".format(len(unknown)),
                                  cands=unknown, credits=credits, source="guessed")
        else:
            out[p["id"]] = result("none", "All {0} likely addresses came back invalid. None valid.".format(len(cands)),
                                  credits=credits, source="guessed")
    return out


def max_credits(groups: Dict[str, List[Dict[str, Any]]], cfg: Dict[str, Any]) -> int:
    """The most a set of domains can cost: one test address per domain, plus every candidate. Pure."""
    total = 0
    for people in groups.values():
        total += 1 + sum(1 if p.get("email") else int(cfg["max_candidates"]) for p in people)
    return total


# --------------------------------------------------------------------------- the run


def todo_filter(client_id: str) -> Dict[str, str]:
    return {"client_id": "eq." + client_id, "guess_checked_at": "is.null", "archived_at": "is.null"}


def with_domains(db: Any, rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Contacts grouped by company domain (their own domain, else their company's, else their
    email's). Contacts with no domain go under ""."""
    ids = sorted({r["company_id"] for r in rows if r.get("company_id") and not r.get("domain")})
    company_domain: Dict[str, str] = {}
    for group in skillkit.batches(ids, 100):
        for c in db.select("lead_companies", {"id": quoted_in(group)}, columns="id,domain"):
            company_domain[c["id"]] = c.get("domain") or ""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        d = domain_of(r.get("domain")) or domain_of(company_domain.get(r.get("company_id") or "")) or \
            domain_of(r.get("email"))
        groups.setdefault(d, []).append(r)
    return groups


def known_patterns(db: Any, client_id: str, domains: List[str]) -> Dict[str, str]:
    """A pattern already proved at each domain, from a colleague with a valid email."""
    out: Dict[str, str] = {}
    for group in skillkit.batches([d for d in domains if d], 100):
        rows = db.select("lead_contacts", {"client_id": "eq." + client_id, "domain": quoted_in(group),
                                           "email_status": "eq.valid"}, columns="domain,email,email_pattern,full_name,"
                                                                                "first_name,last_name")
        for r in rows:
            pid = r.get("email_pattern") or pattern_of(r.get("email") or "", contact_name(r))
            if pid in PATTERN_IDS and r["domain"] not in out:
                out[r["domain"]] = pid
    return out


def spent_since(db: Any, client_id: str, since: str) -> int:
    rows = db.select_all("lead_contacts", {"client_id": "eq." + client_id, "guess_checked_at": "gte." + since},
                         columns="guess_credits", order="id")
    return sum(int(r.get("guess_credits") or 0) for r in rows)


def run(ctx: skillkit.Context, client: str = "", live: bool = False, config_path: Optional[str] = None,
        check: Optional[Callable[[str], str]] = None,
        mx: Optional[Callable[[str], Optional[bool]]] = None) -> Dict[str, Any]:
    """The skill. The automations app calls it as run(ctx, client=..., live=True)."""
    skillkit.need([KEY], WHERE)
    cfg = load_config(config_path)
    db = ctx.db
    c = find_client(db, client)
    per_run = int(cfg["batch_size"]) * int(cfg["max_batches_per_run"])
    todo = db.select_all("lead_contacts", todo_filter(c["id"]), order="created_at")[:per_run]
    if not todo:
        return {"ok": True, "message": "Nothing to do: every contact for {0} has been checked.".format(c["client_name"])}
    groups = with_domains(db, todo)
    needed = max_credits({d: g for d, g in groups.items() if d}, cfg)
    what = "Find the email of {0:,} contacts at {1:,} companies for {2} (MillionVerifier checks; most stop " \
           "after a few)".format(len(todo), len([d for d in groups if d]), c["client_name"])
    if not live:
        return {"ok": True, "dry_run": True, "contacts": len(todo), "domains": len([d for d in groups if d]),
                "credits_at_most": needed,
                "message": "Dry run: nothing spent. Add --live to run. Above {0} credits a person approves "
                           "first.".format(cfg["approval_above"])}
    allowed = spend_gate(ctx, c, needed, "credits", what, cfg, lambda since: spent_since(db, c["id"], since))
    key = os.environ[KEY]
    check = check or (lambda email: cheap_check(email, key))
    mx = mx or has_mail_server
    totals = {"checked": 0, "valid": 0, "invalid": 0, "catch-all": 0, "unknown": 0, "none": 0, "skipped": 0,
              "credits": 0}
    errors: List[str] = []
    seen: set = set()

    def work(rows: List[Dict[str, Any]]) -> int:
        rows = [r for r in rows if r["id"] not in seen]
        seen.update(r["id"] for r in rows)
        grouped = with_domains(db, rows)
        known = known_patterns(db, c["id"], list(grouped))
        jobs, used = [], totals["credits"]
        for d, people in grouped.items():
            if not d:
                continue
            cost = max_credits({d: people}, cfg)
            if used + cost > allowed:
                continue  # left for the next run
            used += cost
            jobs.append((d, people))
        n = 0
        for p in grouped.get("", []):
            write(p, result("skipped", "No company domain, so there is nothing to guess from."))
            n += 1

        def one(job: Tuple[str, List[Dict[str, Any]]]) -> Tuple[str, Optional[Dict[str, Dict[str, Any]]], str]:
            d, people = job
            try:
                return d, guess_domain(d, people, known.get(d, ""), cfg, check, mx), ""
            except VendorError as e:
                return d, None, str(e)

        with ThreadPoolExecutor(max_workers=max(1, int(cfg["workers"]))) as pool:
            for d, answers, err in pool.map(one, jobs):
                if answers is None:
                    errors.append("{0}: {1}".format(d, err))
                    continue
                by_id = {p["id"]: p for p in grouped[d]}
                for pid, fields in answers.items():
                    fields["domain"] = d
                    write(by_id[pid], fields)
                    n += 1
        return n

    def write(row: Dict[str, Any], fields: Dict[str, Any]) -> None:
        fields = {k: v for k, v in fields.items() if not (k in ("email", "email_source") and v is None)}
        fields["guess_checked_at"] = now_iso()
        db.update("lead_contacts", row["id"], fields)
        totals["checked"] += 1
        totals[fields["email_status"]] = totals.get(fields["email_status"], 0) + 1
        totals["credits"] += int(fields.get("guess_credits") or 0)

    size = min(int(cfg["batch_size"]), skillkit.BATCH_MAX)
    skillkit.run_in_batches(lambda limit: db.select("lead_contacts", todo_filter(c["id"]), order="created_at",
                                                    limit=limit),
                            work, size=size, max_batches=int(cfg["max_batches_per_run"]))
    link = skillkit.os_link(ctx.settings(), "clients/" + c["id"])
    if errors:
        skillkit.report_failure(ctx, SKILL, "cheap check", VendorError("; ".join(errors[:3])), link)
    left = len(db.select_all("lead_contacts", todo_filter(c["id"]), columns="id", order="id"))
    text = ("*Email guesser: {0}*\n{1:,} contacts checked: {2:,} valid, {3:,} on catch-all domains (for the "
            "catch-all-verifier), {4:,} unknown, {5:,} none valid, {6:,} invalid, {7:,} skipped.\n{8:,} credits "
            "used. {9:,} contacts still to check.{10}\nNext: run the catch-all-verifier skill for the catch-all "
            "ones.").format(c["client_name"], totals["checked"], totals["valid"], totals["catch-all"],
                            totals["unknown"], totals["none"], totals["invalid"], totals["skipped"], totals["credits"],
                            left, "\n{0} companies were not done (the verifier did not answer). They are tried "
                                  "again on the next run.".format(len(errors)) if errors else "")
    if totals["checked"]:
        skillkit.post(ctx, "daily-summary", "📧 Email Guesser", text, link=link, button="Open the client")
    return {"ok": not errors, "checked": totals["checked"], "valid": totals["valid"],
            "catch_all": totals["catch-all"], "unknown": totals["unknown"], "none_valid": totals["none"],
            "invalid": totals["invalid"], "skipped": totals["skipped"], "credits_used": totals["credits"],
            "contacts_left": left, "errors": errors}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Find and prove the work email of each contact.")
    ap.add_argument("--client", required=True, help="The client's name or row id")
    ap.add_argument("--live", action="store_true", help="Really spend credits (without it: a dry run)")
    args = ap.parse_args(argv)
    ctx = skillkit.context(needs=NEEDS, where=WHERE)
    try:
        out = run(ctx, client=args.client, live=args.live)
    except ValueError as e:
        print(str(e))
        return 2
    print(skillkit.dump(out))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    skillkit.main_guard(main)
