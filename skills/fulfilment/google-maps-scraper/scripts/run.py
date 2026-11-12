"""Google Maps scraper: runs the planned searches (keyword x place) through Serper and saves
each business found in lead_companies. Run it from the repo root. Reads .env; never prints a key.

    python3 skills/fulfilment/google-maps-scraper/scripts/run.py --client "Acme Dental"
    python3 skills/fulfilment/google-maps-scraper/scripts/run.py --client "Acme Dental" --live
    python3 skills/fulfilment/google-maps-scraper/scripts/run.py --client "Acme Dental" \
        --add "dentist" --in "Austin, TX" --in "Dallas, TX"          (plan two searches, then run)
    python3 skills/fulfilment/google-maps-scraper/scripts/run.py --client "Acme Dental" --status

1. Each search is one row in lead_searches (the tam-mapper skill plans them, or --add does).
2. Without --live it spends nothing and writes nothing: it shows the searches and the credits.
3. With --live: above the limit in config.json, it asks for approval first (a card in Review
   and a post in the review channel). A person approves by moving the card on.
4. It runs the searches that are not done, at most 500 a batch. Each search row is marked done
   as soon as it is saved, so a crash starts again at the next search that is not done.
5. A business is saved once per client: the same place id or the same web domain is skipped.

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
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Callable, Dict, List, Optional  # noqa: E402

SKILL = "google-maps-scraper"
SKILL_DIR = Path(__file__).resolve().parents[1]
KEY = "SERPER_API_KEY"
WHERE = {KEY: "serper.dev, sign in, Dashboard, API Key"}
NEEDS = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "SLACK_BOT_TOKEN", KEY]
SERPER_URL = "https://google.serper.dev/places"


# --------------------------------------------------------------------------- shared block
# The same block is in each list-building skill, so each skill folder works on its own.

APPROVAL_BOARD = "tasks"
APPROVAL_STAGE = "30 - In Review"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class VendorError(RuntimeError):
    """The outside tool did not answer. The row is left as it was, so the next run tries again."""


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


# --------------------------------------------------------------------------- Serper (one vendor function)


def serper_places(query: str, page: int, country: str, key: str, timeout: int = 30) -> List[Dict[str, Any]]:
    """One Google Maps search page through Serper. The tests replace this function."""
    body = json.dumps({"q": query, "gl": country, "page": page}).encode()
    req = urllib.request.Request(SERPER_URL, data=body, method="POST",
                                 headers={"X-API-KEY": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise VendorError("Serper said {0}: {1}".format(e.code, e.read().decode(errors="ignore")[:200]))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise VendorError("Serper could not be reached: {0}".format(e))
    return list(data.get("places") or [])


# --------------------------------------------------------------------------- the work


def company_row(place: Dict[str, Any], search: Dict[str, Any]) -> Dict[str, Any]:
    """One Serper place -> one lead_companies row. Pure."""
    website = (place.get("website") or "").strip()
    return {
        "client_id": search["client_id"],
        "campaign_id": search.get("campaign_id"),
        "search_id": search["id"],
        "company_name": (place.get("title") or "").strip() or "(no name)",
        "website": website or None,
        "domain": domain_of(website) or None,
        "place_id": str(place.get("placeId") or place.get("cid") or "") or None,
        "phone": place.get("phoneNumber") or None,
        "address": place.get("address") or None,
        "category": place.get("category") or None,
        "rating": place.get("rating"),
        "review_count": place.get("ratingCount"),
        "industry": search.get("industry"),
        "location": search.get("location"),
        "segment": search.get("segment"),
        "source": "google maps",
    }


def todo_searches(db: Any, client_id: str, cfg: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    """Searches not done yet: 'to do', or 'failed' with tries left. Oldest first."""
    return db.select("lead_searches", {"client_id": "eq." + client_id, "status": "in.(to do,failed)",
                                       "attempts": "lt.{0}".format(int(cfg["max_attempts"])),
                                       "archived_at": "is.null"}, order="created_at", limit=limit)


def count_todo(db: Any, client_id: str, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return db.select_all("lead_searches", {"client_id": "eq." + client_id, "status": "in.(to do,failed)",
                                           "attempts": "lt.{0}".format(int(cfg["max_attempts"])),
                                           "archived_at": "is.null"}, columns="id,keyword,location", order="id")


def credits_for(searches: int, cfg: Dict[str, Any]) -> int:
    return int(searches) * int(cfg["pages_per_search"]) * int(cfg["credits_per_page"])


def spent_since(db: Any, client_id: str, since: str) -> int:
    rows = db.select_all("lead_searches", {"client_id": "eq." + client_id, "searched_at": "gte." + since},
                         columns="credits_used", order="id")
    return sum(int(r.get("credits_used") or 0) for r in rows)


def existing(db: Any, client_id: str, column: str, values: List[str]) -> set:
    """Which of these place ids (or domains) the client already has."""
    out = set()
    values = sorted({v for v in values if v})
    for group in skillkit.batches(values, 100):
        rows = db.select("lead_companies", {"client_id": "eq." + client_id, column: quoted_in(group)},
                         columns=column)
        out |= {str(r.get(column)) for r in rows}
    return out


def run_search(db: Any, search: Dict[str, Any], cfg: Dict[str, Any], key: str,
               fetch: Callable[..., List[Dict[str, Any]]]) -> Dict[str, int]:
    """One search: every page, then the new businesses saved, then the search marked done.
    A vendor error marks the search 'failed' (one more try next run, up to max_attempts)."""
    query = "{0} in {1}".format(search["keyword"], search["location"])
    places: List[Dict[str, Any]] = []
    pages = 0
    try:
        for page in range(1, int(cfg["pages_per_search"]) + 1):
            got = fetch(query, page, cfg["country"], key)
            pages += 1
            places += got
            if len(got) < int(cfg["results_per_full_page"]):
                break  # a short page is the last page
    except VendorError as e:
        db.update("lead_searches", search["id"], {
            "status": "failed", "attempts": int(search.get("attempts") or 0) + 1, "error": str(e)[:300],
            "credits_used": int(search.get("credits_used") or 0) + pages * int(cfg["credits_per_page"]),
            "searched_at": now_iso()})
        return {"failed": 1, "found": 0, "new": 0, "credits": pages * int(cfg["credits_per_page"])}

    rows = [company_row(p, search) for p in places]
    skipped_no_site = 0
    if not cfg.get("keep_without_website"):
        skipped_no_site = sum(1 for r in rows if not r["domain"])
        rows = [r for r in rows if r["domain"]]
    have_places = existing(db, search["client_id"], "place_id", [r["place_id"] for r in rows if r["place_id"]])
    have_domains = existing(db, search["client_id"], "domain", [r["domain"] for r in rows if r["domain"]])
    new_rows = []
    for r in rows:
        if (r["place_id"] and r["place_id"] in have_places) or (r["domain"] and r["domain"] in have_domains):
            continue
        new_rows.append(r)
        if r["place_id"]:
            have_places.add(r["place_id"])
        if r["domain"]:
            have_domains.add(r["domain"])
    for group in skillkit.batches(new_rows):
        db.insert("lead_companies", group)
    credits = pages * int(cfg["credits_per_page"])
    db.update("lead_searches", search["id"], {
        "status": "done", "attempts": int(search.get("attempts") or 0) + 1, "error": None,
        "results_count": len(places), "new_count": len(new_rows),
        "credits_used": int(search.get("credits_used") or 0) + credits, "searched_at": now_iso()})
    return {"failed": 0, "found": len(places), "new": len(new_rows), "credits": credits,
            "no_site": skipped_no_site}


def plan_rows(client: Dict[str, Any], keywords: List[str], places: List[str]) -> List[Dict[str, Any]]:
    """--add "dentist" --in "Austin, TX": one search row per keyword per place. Pure."""
    rows, seen = [], set()
    for k in keywords:
        for p in places:
            k2, p2 = " ".join(k.split()), " ".join(p.split())
            if k2 and p2 and (k2.lower(), p2.lower()) not in seen:
                seen.add((k2.lower(), p2.lower()))
                rows.append({"client_id": client["id"], "keyword": k2, "location": p2,
                             "segment": "{0} | {1}".format(k2, p2), "status": "to do", "attempts": 0,
                             "credits_used": 0, "created_at": now_iso()})
    return rows


def add_searches(db: Any, client: Dict[str, Any], rows: List[Dict[str, Any]]) -> int:
    """Adds the searches the client does not have yet. Returns how many were new."""
    have = {(r.get("keyword", "").lower(), r.get("location", "").lower())
            for r in db.select_all("lead_searches", {"client_id": "eq." + client["id"]},
                                   columns="keyword,location", order="id")}
    new = [r for r in rows if (r["keyword"].lower(), r["location"].lower()) not in have]
    for group in skillkit.batches(new):
        db.insert("lead_searches", group)
    return len(new)


def status(db: Any, client: Dict[str, Any]) -> Dict[str, Any]:
    rows = db.select_all("lead_searches", {"client_id": "eq." + client["id"], "archived_at": "is.null"},
                         columns="status,results_count,new_count,credits_used", order="id")
    out = {"to do": 0, "done": 0, "failed": 0}
    for r in rows:
        out[r.get("status") or "to do"] = out.get(r.get("status") or "to do", 0) + 1
    return {"client": client["client_name"], "searches": out,
            "businesses_found": sum(int(r.get("results_count") or 0) for r in rows),
            "new_businesses_saved": sum(int(r.get("new_count") or 0) for r in rows),
            "credits_used": sum(int(r.get("credits_used") or 0) for r in rows)}


def run(ctx: skillkit.Context, client: str = "", live: bool = False, add: Optional[List[str]] = None,
        places: Optional[List[str]] = None, show_status: bool = False, config_path: Optional[str] = None,
        fetch: Optional[Callable[..., List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """The skill. The automations app calls it as run(ctx, client=..., live=True)."""
    skillkit.need([KEY], WHERE)
    cfg = load_config(config_path)
    db = ctx.db
    c = find_client(db, client)
    if show_status:
        return dict(status(db, c), ok=True)
    if add or places:
        if not (add and places):
            raise ValueError("To plan searches, give at least one --add keyword and one --in place.")
        planned = plan_rows(c, add, places)
        if not live:
            return {"ok": True, "dry_run": True, "would_add_searches": len(planned),
                    "message": "Dry run: nothing written. Add --live to plan and run these searches."}
        added = add_searches(db, c, planned)
    else:
        added = 0
    todo = count_todo(db, c["id"], cfg)
    per_run = min(len(todo), int(cfg["batch_size"]) * int(cfg["max_batches_per_run"]))
    needed = credits_for(per_run, cfg)
    what = "{0:,} Google Maps searches for {1} (keyword x place), {2} page(s) each".format(
        per_run, c["client_name"], cfg["pages_per_search"])
    if not todo:
        return {"ok": True, "message": "Nothing to do: every search for {0} is done. Plan more with the "
                                       "tam-mapper skill or --add.".format(c["client_name"]),
                "searches_added": added}
    if not live:
        return {"ok": True, "dry_run": True, "searches_to_run": per_run, "searches_waiting": len(todo),
                "credits_needed": needed, "examples": ["{0} in {1}".format(r["keyword"], r["location"])
                                                       for r in todo[:5]],
                "message": "Dry run: nothing spent. Add --live to run. Above {0} credits a person "
                           "approves first.".format(cfg["approval_above"])}
    allowed = spend_gate(ctx, c, needed, "credits", what, cfg, lambda since: spent_since(db, c["id"], since))
    key = os.environ[KEY]
    fetch = fetch or serper_places
    totals = {"searches": 0, "failed": 0, "found": 0, "new": 0, "credits": 0, "no_site": 0}
    one_search = credits_for(1, cfg)

    def work(rows: List[Dict[str, Any]]) -> int:
        n = 0
        for s in rows:
            if totals["credits"] + one_search > allowed:
                return n
            out = run_search(db, s, cfg, key, fetch)
            totals["searches"] += 1
            for k in ("failed", "found", "new", "credits", "no_site"):
                totals[k] += int(out.get(k) or 0)
            n += 1
        return n

    size = min(int(cfg["batch_size"]), skillkit.BATCH_MAX)
    skillkit.run_in_batches(lambda limit: todo_searches(db, c["id"], cfg, limit), work, size=size,
                            max_batches=int(cfg["max_batches_per_run"]))
    left = len(count_todo(db, c["id"], cfg))
    link = skillkit.os_link(ctx.settings(), "clients/" + c["id"])
    text = ("*Google Maps scraper: {0}*\n{1:,} searches run, {2:,} businesses found, {3:,} new saved, "
            "{4:,} credits used.\n{5:,} searches still to do.{6}\nNext: run the website-classifier skill on the new "
            "businesses.").format(c["client_name"], totals["searches"], totals["found"], totals["new"],
                                  totals["credits"], left,
                                  "\n{0:,} searches failed (they are tried once more on the next run).".format(
                                      totals["failed"]) if totals["failed"] else "")
    skillkit.post(ctx, "daily-summary", "🗺️ Google Maps Scraper", text, link=link, button="Open the client")
    if totals["failed"] and totals["failed"] == totals["searches"]:
        skillkit.report_failure(ctx, SKILL, "search", VendorError("every search failed; check the Serper key "
                                                                   "and credits"), link)
    return {"ok": True, "searches_added": added, "searches_run": totals["searches"], "failed": totals["failed"],
            "businesses_found": totals["found"], "new_saved": totals["new"], "skipped_no_website": totals["no_site"],
            "credits_used": totals["credits"], "searches_left": left}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run the planned Google Maps searches and save the businesses.")
    ap.add_argument("--client", required=True, help="The client's name or row id")
    ap.add_argument("--live", action="store_true", help="Really spend credits (without it: a dry run)")
    ap.add_argument("--add", action="append", default=[], help="A keyword to plan (repeat for more)")
    ap.add_argument("--in", dest="places", action="append", default=[], help="A place to plan (repeat for more)")
    ap.add_argument("--status", action="store_true", help="Show the searches done, to do and failed")
    args = ap.parse_args(argv)
    ctx = skillkit.context(needs=NEEDS, where=WHERE)
    try:
        out = run(ctx, client=args.client, live=args.live, add=args.add, places=args.places,
                  show_status=args.status)
    except ValueError as e:
        print(str(e))
        return 2
    print(skillkit.dump(out))
    return 0


if __name__ == "__main__":
    skillkit.main_guard(main)
