"""Catch-all verifier: the deep check (BounceBan, an SMTP-level check) for the contacts whose
domain came back catch-all. On a catch-all domain the cheap verifier is only guessing, so the
deep check is aimed there and nowhere else. Run it from the repo root. Reads .env; never prints a key.

    python3 skills/fulfilment/catch-all-verifier/scripts/run.py --client "Acme Dental"
    python3 skills/fulfilment/catch-all-verifier/scripts/run.py --client "Acme Dental" --live

1. Contacts to do: email_status 'catch-all' (the email-guesser sets it) and no deep_checked_at.
2. Per domain, the first check is the scout. If it comes back 'unknown', the deep check cannot
   read this domain either: no more credits are spent there, and the contacts are 'unknown'.
3. If the scout can tell good from bad, each contact's candidates are checked best first, up to
   max_checks_per_person. One resolved colleague shows the company's pattern: it goes first for
   the others.
4. Deliverable with a score of send_score or more = valid. An address nobody checked is never
   the answer. On a domain the deep check can read, all checked candidates undeliverable means
   "none valid", and that is written as the result.
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
import time  # noqa: E402
import unicodedata  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: E402

SKILL = "catch-all-verifier"
SKILL_DIR = Path(__file__).resolve().parents[1]
KEY = "BOUNCEBAN_API_KEY"
WHERE = {KEY: "bounceban.com, sign in, API (left menu), API key"}
NEEDS = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "SLACK_BOT_TOKEN", KEY]
BB_URL = "https://api.bounceban.com/v1/verify/single"


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


# --------------------------------------------------------------------------- patterns (same as email-guesser)

TITLES = frozenset({"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "rev"})
SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "phd", "md", "mba", "cpa", "esq", "dds", "dmd"})
PARTICLES = frozenset({"van", "von", "de", "del", "della", "der", "den", "di", "da", "dos", "la", "le", "st"})
PATTERNS: List[Tuple[str, Callable[[str, str], str]]] = [
    ("first.last", lambda f, l: f + "." + l), ("first", lambda f, l: f), ("firstlast", lambda f, l: f + l),
    ("flast", lambda f, l: f[0] + l), ("first_last", lambda f, l: f + "_" + l), ("f.last", lambda f, l: f[0] + "." + l),
    ("firstl", lambda f, l: f + l[0]), ("last", lambda f, l: l), ("last.first", lambda f, l: l + "." + f),
    ("lastfirst", lambda f, l: l + f), ("lastf", lambda f, l: l + f[0]), ("first-last", lambda f, l: f + "-" + l),
    ("fl", lambda f, l: f[0] + l[0]),
]


def _slug(token: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFKD", token or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", folded.lower())


def split_name(full_name: str) -> Tuple[str, str]:
    tokens = [t for t in re.split(r"[\s,]+", full_name or "") if _slug(t)]
    tokens = [t for t in tokens if _slug(t) not in TITLES and _slug(t) not in SUFFIXES]
    if not tokens:
        return "", ""
    rest = [_slug(t) for t in tokens[1:]]
    if not rest:
        return _slug(tokens[0]), ""
    tail = [rest[-1]]
    for t in reversed(rest[:-1]):
        if t in PARTICLES:
            tail.insert(0, t)
        else:
            break
    return _slug(tokens[0]), "".join(tail)


def contact_name(row: Dict[str, Any]) -> str:
    return (row.get("full_name") or " ".join(x for x in (row.get("first_name"), row.get("last_name")) if x) or "").strip()


def pattern_of(email: str, full_name: str) -> str:
    first, last = split_name(full_name)
    local = (email or "").split("@")[0].lower()
    if not first or not local:
        return ""
    for pid, build in PATTERNS:
        if (last or pid == "first") and build(first, last or first) == local:
            return pid
    return ""


def candidates_of(row: Dict[str, Any]) -> List[Dict[str, str]]:
    """The addresses to check for one contact: the email-guesser's ranked candidates, or the
    contact's own email. Pure."""
    raw = row.get("email_candidates")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    out = []
    for c in raw or []:
        email = (c.get("email") if isinstance(c, dict) else str(c)).strip().lower()
        if "@" in email:
            out.append({"email": email, "pattern": (c.get("pattern") if isinstance(c, dict) else "") or
                        pattern_of(email, contact_name(row))})
    given = (row.get("email") or "").strip().lower()
    if given and given not in [c["email"] for c in out]:
        out.insert(0, {"email": given, "pattern": pattern_of(given, contact_name(row)) or "given"})
    return out


# --------------------------------------------------------------------------- BounceBan (one vendor function)


def deep_check(email: str, key: str, max_wait: float = 30.0) -> Tuple[str, int]:
    """One BounceBan deep check: (deliverable | undeliverable | risky | unknown, score 0-100).
    It waits for a slow check up to max_wait seconds. The tests replace this function."""
    def get(url: str) -> Dict[str, Any]:
        req = urllib.request.Request(url, headers={"Authorization": key})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise VendorError("BounceBan said {0}: {1}".format(e.code, e.read().decode(errors="ignore")[:200]))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise VendorError("BounceBan could not be reached: {0}".format(e))

    data = get(BB_URL + "?" + urllib.parse.urlencode({"email": email, "mode": "deepverify"}))
    waited, step = 0.0, 2.0
    while data.get("status") in ("verifying", "queue") and data.get("id") and waited < max_wait:
        time.sleep(step)
        waited += step
        step = min(step * 1.5, 8.0)
        data = get(BB_URL + "/status?" + urllib.parse.urlencode({"id": data["id"]}))
    if data.get("status") in ("verifying", "queue"):
        return "unknown", 0
    return str(data.get("result") or "unknown"), int(data.get("score") or 0)


# --------------------------------------------------------------------------- one company domain


def answer(status: str, deep: str, evidence: str, credits: int, verdict: Optional[str],
           email: Optional[str] = None, pattern: Optional[str] = None, score: Optional[int] = None) -> Dict[str, Any]:
    out = {"email_status": status, "deep_status": deep, "email_evidence": evidence[:500], "deep_credits": credits,
           "final_verdict": verdict, "email_score": score}
    if email:
        out["email"] = email
        out["email_pattern"] = pattern if pattern and pattern != "given" else None
    return out


def verify_domain(domain: str, people: List[Dict[str, Any]], known: str, cfg: Dict[str, Any],
                  check: Callable[[str], Tuple[str, int]]) -> Dict[str, Dict[str, Any]]:
    """Every contact at one catch-all domain -> {contact id: columns to write}. Pure apart from
    `check`. A VendorError goes up: then nothing at this domain is written."""
    out: Dict[str, Dict[str, Any]] = {}
    per = int(cfg["credits_per_check"])
    most = int(cfg["max_checks_per_person"])
    send = int(cfg["send_score"])
    readable: Optional[bool] = None
    scout = ""
    learned = known
    people = sorted(people, key=lambda p: 0 if p.get("email") else 1)
    for p in people:
        given = (p.get("email") or "").strip().lower()
        cands = candidates_of(p)
        if learned:
            cands = sorted(cands, key=lambda c: 0 if c["pattern"] == learned else 1)
        cands = cands[:most]
        if not cands:
            out[p["id"]] = answer("skipped", "none", "No address to check.", 0, None)
            continue
        if readable is False:
            out[p["id"]] = answer("unknown", "unknown", "Not checked: the deep check cannot read {0} (the first check, "
                                                        "{1}, came back unknown). Not an answer.".format(domain, scout),
                                  0, "risky" if given else None)
            continue
        checked: List[Tuple[Dict[str, str], str, int]] = []
        for cand in cands:
            res, score = check(cand["email"])
            checked.append((cand, res, score))
            if readable is None:
                readable = res in ("deliverable", "undeliverable")
                scout = cand["email"]
                if not readable:
                    break
            if res == "deliverable":
                break
        credits = len(checked) * per
        good = [c for c in checked if c[1] == "deliverable"]
        risky = [c for c in checked if c[1] == "risky"]
        if good:
            cand, res, score = good[0]
            ok = score >= send
            if ok:
                learned = learned or cand["pattern"]
            out[p["id"]] = answer("valid" if ok else "risky", "deliverable",
                                  "Deep check (BounceBan): deliverable, score {0}{1}.".format(
                                      score, "" if ok else " (below send_score {0})".format(send)),
                                  credits, "send" if ok else "risky", cand["email"], cand["pattern"], score)
        elif risky:
            cand, res, score = risky[0]
            out[p["id"]] = answer("risky", "risky", "Deep check (BounceBan): risky, score {0}.".format(score),
                                  credits, "risky", cand["email"], cand["pattern"], score)
        elif readable:
            not_checked = len(candidates_of(p)) - len(checked)
            if given and len(cands) == 1:
                out[p["id"]] = answer("invalid", "undeliverable", "Deep check (BounceBan): undeliverable, score {0}."
                                      .format(checked[0][2]), credits, "skip", score=checked[0][2])
            else:
                out[p["id"]] = answer("none", "undeliverable", "Deep check (BounceBan): {0} of {1} candidates "
                                      "undeliverable. None valid.{2}".format(
                                          len(checked), len(checked) + not_checked,
                                          " {0} were not checked (max_checks_per_person); an unchecked address is not "
                                          "an answer.".format(not_checked) if not_checked else ""), credits, None)
        else:
            out[p["id"]] = answer("unknown", "unknown", "Deep check (BounceBan): {0} came back unknown. The deep check "
                                                        "cannot read this domain. Not an answer.".format(checked[0][0]["email"]),
                                  credits, "risky" if given else None)
    return out


def max_credits(groups: Dict[str, List[Dict[str, Any]]], cfg: Dict[str, Any]) -> int:
    """The most a set of domains can cost. Pure."""
    most, per = int(cfg["max_checks_per_person"]), int(cfg["credits_per_check"])
    return sum(min(len(candidates_of(p)), most) * per for people in groups.values() for p in people)


# --------------------------------------------------------------------------- the run


def todo_filter(client_id: str, cfg: Dict[str, Any]) -> Dict[str, str]:
    return {"client_id": "eq." + client_id, "email_status": "in.({0})".format(",".join(cfg["check_statuses"])),
            "deep_checked_at": "is.null", "archived_at": "is.null"}


def group_by_domain(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        cands = candidates_of(r)
        d = domain_of(r.get("domain")) or (domain_of(cands[0]["email"]) if cands else "")
        groups.setdefault(d, []).append(r)
    return groups


def known_patterns(db: Any, client_id: str, domains: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for group in skillkit.batches([d for d in domains if d], 100):
        rows = db.select("lead_contacts", {"client_id": "eq." + client_id, "domain": quoted_in(group),
                                           "email_status": "eq.valid"}, columns="domain,email,email_pattern,full_name,"
                                                                                "first_name,last_name")
        for r in rows:
            pid = r.get("email_pattern") or pattern_of(r.get("email") or "", contact_name(r))
            if pid and r["domain"] not in out:
                out[r["domain"]] = pid
    return out


def spent_since(db: Any, client_id: str, since: str) -> int:
    rows = db.select_all("lead_contacts", {"client_id": "eq." + client_id, "deep_checked_at": "gte." + since},
                         columns="deep_credits", order="id")
    return sum(int(r.get("deep_credits") or 0) for r in rows)


def run(ctx: skillkit.Context, client: str = "", live: bool = False, config_path: Optional[str] = None,
        check: Optional[Callable[[str], Tuple[str, int]]] = None) -> Dict[str, Any]:
    """The skill. The automations app calls it as run(ctx, client=..., live=True)."""
    skillkit.need([KEY], WHERE)
    cfg = load_config(config_path)
    db = ctx.db
    c = find_client(db, client)
    per_run = int(cfg["batch_size"]) * int(cfg["max_batches_per_run"])
    todo = db.select_all("lead_contacts", todo_filter(c["id"], cfg), order="created_at")[:per_run]
    if not todo:
        return {"ok": True, "message": "Nothing to do: no contact of {0} waits for the deep check.".format(
            c["client_name"])}
    groups = group_by_domain(todo)
    needed = max_credits(groups, cfg)
    what = "Deep check (BounceBan) of {0:,} contacts on {1:,} catch-all domains for {2}; a domain the check " \
           "cannot read costs one check".format(len(todo), len(groups), c["client_name"])
    if not live:
        return {"ok": True, "dry_run": True, "contacts": len(todo), "domains": len(groups), "credits_at_most": needed,
                "message": "Dry run: nothing spent. Add --live to run. Above {0} credits a person approves "
                           "first.".format(cfg["approval_above"])}
    allowed = spend_gate(ctx, c, needed, "credits", what, cfg, lambda since: spent_since(db, c["id"], since))
    key = os.environ[KEY]
    check = check or (lambda email: deep_check(email, key, float(cfg["max_wait_seconds"])))
    totals = {"checked": 0, "valid": 0, "risky": 0, "none": 0, "invalid": 0, "unknown": 0, "skipped": 0, "credits": 0}
    errors: List[str] = []
    seen: set = set()

    def write(row: Dict[str, Any], fields: Dict[str, Any]) -> None:
        fields["deep_checked_at"] = now_iso()
        db.update("lead_contacts", row["id"], fields)
        totals["checked"] += 1
        totals[fields["email_status"]] = totals.get(fields["email_status"], 0) + 1
        totals["credits"] += int(fields.get("deep_credits") or 0)

    def work(rows: List[Dict[str, Any]]) -> int:
        rows = [r for r in rows if r["id"] not in seen]
        seen.update(r["id"] for r in rows)
        grouped = group_by_domain(rows)
        known = known_patterns(db, c["id"], list(grouped))
        jobs, used = [], totals["credits"]
        for d, people in grouped.items():
            cost = max_credits({d: people}, cfg)
            if used + cost > allowed:
                continue  # left for the next run
            used += cost
            jobs.append((d, people))

        def one(job: Tuple[str, List[Dict[str, Any]]]) -> Tuple[str, Optional[Dict[str, Dict[str, Any]]], str]:
            d, people = job
            try:
                return d, verify_domain(d, people, known.get(d, ""), cfg, check), ""
            except VendorError as e:
                return d, None, str(e)

        n = 0
        with ThreadPoolExecutor(max_workers=max(1, int(cfg["workers"]))) as pool:
            for d, answers, err in pool.map(one, jobs):
                if answers is None:
                    errors.append("{0}: {1}".format(d or "(no domain)", err))
                    continue
                by_id = {p["id"]: p for p in grouped[d]}
                for pid, fields in answers.items():
                    write(by_id[pid], fields)
                    n += 1
        return n

    size = min(int(cfg["batch_size"]), skillkit.BATCH_MAX)
    skillkit.run_in_batches(lambda limit: db.select("lead_contacts", todo_filter(c["id"], cfg), order="created_at",
                                                    limit=limit),
                            work, size=size, max_batches=int(cfg["max_batches_per_run"]))
    link = skillkit.os_link(ctx.settings(), "clients/" + c["id"])
    if errors:
        skillkit.report_failure(ctx, SKILL, "deep check", VendorError("; ".join(errors[:3])), link)
    left = len(db.select_all("lead_contacts", todo_filter(c["id"], cfg), columns="id", order="id"))
    text = ("*Catch-all verifier: {0}*\n{1:,} contacts deep-checked: {2:,} valid, {3:,} risky, {4:,} none valid, "
            "{5:,} invalid, {6:,} unknown (the domain cannot be read).\n{7:,} credits used. {8:,} contacts still to "
            "check.{9}\nNext: the contacts marked 'send' are ready for a campaign.").format(
        c["client_name"], totals["checked"], totals["valid"], totals["risky"], totals["none"], totals["invalid"],
        totals["unknown"], totals["credits"], left,
        "\n{0} domains were not done (BounceBan did not answer). They are tried again on the next run.".format(
            len(errors)) if errors else "")
    if totals["checked"]:
        skillkit.post(ctx, "daily-summary", "🔬 Catch-all Verifier", text, link=link, button="Open the client")
    return {"ok": not errors, "checked": totals["checked"], "valid": totals["valid"], "risky": totals["risky"],
            "none_valid": totals["none"], "invalid": totals["invalid"], "unknown": totals["unknown"],
            "credits_used": totals["credits"], "contacts_left": left, "errors": errors}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Deep-check the contacts on catch-all domains.")
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
