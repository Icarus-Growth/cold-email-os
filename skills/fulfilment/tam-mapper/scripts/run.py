"""TAM mapper: turns a client's ideal customer (industries x places x sizes) into the search
plan the google-maps-scraper runs, estimates how big the market is, and counts what the lead
tables already hold, per segment. It plans and counts. It never searches and never spends.

    python3 skills/fulfilment/tam-mapper/scripts/run.py --client "Acme Dental" --icp clients/acme-dental/icp.json --dry-run
    python3 skills/fulfilment/tam-mapper/scripts/run.py --client "Acme Dental" --icp clients/acme-dental/icp.json
    python3 skills/fulfilment/tam-mapper/scripts/run.py --client "Acme Dental" --report

1. Read the ideal customer file (see references/icp_example.json).
2. Build the grid: one search per keyword per place. A segment is "<industry> | <place>".
3. Add the searches the client does not have yet to lead_searches (status 'to do').
4. Estimate the market: searches, credits, businesses and fits, from real results when
   there are some, else from config.json.
5. Count per segment what is in lead_searches, lead_companies and lead_contacts.

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
import re  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

SKILL = "tam-mapper"
SKILL_DIR = Path(__file__).resolve().parents[1]
NEEDS = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "SLACK_BOT_TOKEN"]
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
SCRAPER_CONFIG = SKILL_DIR.parent / "google-maps-scraper" / "config.json"


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """config.json. The search cost comes from the google-maps-scraper's config when it is
    next to this skill, so the two never disagree."""
    p = Path(path) if path else SKILL_DIR / "config.json"
    cfg = {k: v for k, v in json.loads(p.read_text()).items() if not k.startswith("_")}
    if not path and SCRAPER_CONFIG.exists():
        scraper = json.loads(SCRAPER_CONFIG.read_text())
        for k in ("pages_per_search", "credits_per_page"):
            if k in scraper:
                cfg[k] = scraper[k]
    return cfg


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_client(db: Any, client: Any) -> Dict[str, Any]:
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


# --------------------------------------------------------------------------- the ideal customer


def read_icp(icp: Any) -> Dict[str, Any]:
    """The ideal customer, from a dict or a JSON file. Checked, with plain errors. Pure apart
    from reading the file."""
    if isinstance(icp, dict):
        data = icp
    else:
        if not icp:
            raise ValueError("Give the ideal customer file: --icp clients/<client-name>/icp.json. "
                             "Copy skills/fulfilment/tam-mapper/references/icp_example.json to start.")
        p = Path(icp)
        if not p.exists():
            raise ValueError("The ideal customer file '{0}' does not exist.".format(icp))
        try:
            data = json.loads(p.read_text())
        except ValueError as e:
            raise ValueError("The ideal customer file is not valid JSON: {0}".format(e))
    industries = []
    for item in data.get("industries") or []:
        if isinstance(item, str):
            item = {"name": item, "keywords": [item]}
        name = " ".join(str(item.get("name") or "").split())
        words = [" ".join(str(k).split()) for k in item.get("keywords") or [name]]
        words = list(dict.fromkeys(w for w in words if w))
        if name and words:
            industries.append({"name": name, "keywords": words})
    places = list(dict.fromkeys(" ".join(str(p).split()) for p in data.get("locations") or [] if str(p).strip()))
    if not industries:
        raise ValueError("The ideal customer file has no industries. Add at least one, with its search keywords.")
    if not places:
        raise ValueError("The ideal customer file has no locations. Add at least one place, "
                         "for example \"Austin, TX\".")
    return {"industries": industries, "locations": places,
            "sizes": [str(s) for s in data.get("sizes") or []],
            "exclude": [str(s) for s in data.get("exclude") or []],
            "fit_rule": str(data.get("fit_rule") or "")}


def grid(client_id: str, icp: Dict[str, Any], campaign_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every search: keyword x place. Pure."""
    rows, seen = [], set()
    for ind in icp["industries"]:
        for kw in ind["keywords"]:
            for place in icp["locations"]:
                key = (kw.lower(), place.lower())
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"client_id": client_id, "campaign_id": campaign_id, "industry": ind["name"],
                             "keyword": kw, "location": place, "segment": "{0} | {1}".format(ind["name"], place),
                             "status": "to do", "attempts": 0, "credits_used": 0})
    return rows


# --------------------------------------------------------------------------- counts


def read_tables(db: Any, client_id: str) -> Dict[str, List[Dict[str, Any]]]:
    f = {"client_id": "eq." + client_id, "archived_at": "is.null"}
    return {
        "searches": db.select_all("lead_searches", f, columns="id,keyword,location,segment,status,results_count,"
                                  "new_count,credits_used", order="id"),
        "companies": db.select_all("lead_companies", f, columns="id,segment,size_band,fit_status", order="id"),
        "contacts": db.select_all("lead_contacts", f, columns="id,company_id,email_status,final_verdict",
                                  order="id"),
    }


def segment_report(t: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Counts per segment and per size. Pure."""
    seg: Dict[str, Dict[str, int]] = {}

    def row(name: Optional[str]) -> Dict[str, int]:
        return seg.setdefault(name or "(no segment)", {
            "searches": 0, "searches_done": 0, "companies": 0, "fit": 0, "not_fit": 0, "unsure": 0,
            "not_checked": 0, "contacts": 0, "emails_to_send": 0})

    for s in t["searches"]:
        r = row(s.get("segment"))
        r["searches"] += 1
        r["searches_done"] += 1 if s.get("status") == "done" else 0
    company_segment = {}
    sizes: Dict[str, int] = {}
    for c in t["companies"]:
        r = row(c.get("segment"))
        company_segment[c["id"]] = c.get("segment")
        r["companies"] += 1
        key = {"fit": "fit", "not fit": "not_fit", "unsure": "unsure"}.get(c.get("fit_status") or "", "not_checked")
        r[key] += 1
        size = c.get("size_band") or "unknown"
        sizes[size] = sizes.get(size, 0) + 1
    for p in t["contacts"]:
        r = row(company_segment.get(p.get("company_id")))
        r["contacts"] += 1
        r["emails_to_send"] += 1 if p.get("final_verdict") == "send" else 0
    return {"segments": dict(sorted(seg.items())), "by_size": dict(sorted(sizes.items()))}


def estimate(t: Dict[str, List[Dict[str, Any]]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """How big the market is. Uses the real numbers once some searches are done. Pure."""
    done = [s for s in t["searches"] if s.get("status") == "done"]
    todo = [s for s in t["searches"] if s.get("status") != "done"]
    if done:
        per_search = sum(int(s.get("new_count") or 0) for s in done) / float(len(done))
        basis = "the average of {0} searches already done".format(len(done))
    else:
        per_search = float(cfg["expected_new_per_search"])
        basis = "expected_new_per_search in config.json (no search is done yet)"
    checked = [c for c in t["companies"] if c.get("fit_status") in ("fit", "not fit")]
    fit_rate = (sum(1 for c in checked if c["fit_status"] == "fit") / float(len(checked))) if checked else \
        float(cfg["expected_fit_rate"])
    companies = len(t["companies"]) + int(round(per_search * len(todo)))
    credits = len(todo) * int(cfg["pages_per_search"]) * int(cfg["credits_per_page"])
    return {"searches_total": len(t["searches"]), "searches_to_do": len(todo),
            "credits_to_finish": credits, "businesses_estimated": companies,
            "fits_estimated": int(round(companies * fit_rate)), "fit_rate": round(fit_rate, 2),
            "new_businesses_per_search": round(per_search, 1), "based_on": basis}


def as_text(client: Dict[str, Any], est: Dict[str, Any], rep: Dict[str, Any], added: int, dry: bool) -> str:
    lines = ["TAM for {0}".format(client["client_name"]), ""]
    if dry:
        lines.append("Dry run: nothing written. {0} searches would be added.".format(added))
    else:
        lines.append("{0} new searches added to the plan.".format(added))
    lines += ["Searches: {0} in the plan, {1} still to do (about {2} credits to finish).".format(
        est["searches_total"], est["searches_to_do"], est["credits_to_finish"]),
        "Market: about {0} businesses, about {1} that fit (fit rate {2:.0%}).".format(
            est["businesses_estimated"], est["fits_estimated"], est["fit_rate"]),
        "Based on: {0}.".format(est["based_on"]), "",
        "{0:<40} {1:>9} {2:>9} {3:>5} {4:>7} {5:>6} {6:>11} {7:>8} {8:>6}".format(
            "Segment", "Searches", "Done", "Found", "Fit", "No fit", "Not checked", "Contacts", "Send")]
    for name, r in rep["segments"].items():
        lines.append("{0:<40} {1:>9} {2:>9} {3:>5} {4:>7} {5:>6} {6:>11} {7:>8} {8:>6}".format(
            name[:40], r["searches"], r["searches_done"], r["companies"], r["fit"], r["not_fit"],
            r["not_checked"] + r["unsure"], r["contacts"], r["emails_to_send"]))
    if rep["by_size"]:
        lines += ["", "By size: " + ", ".join("{0}: {1}".format(k, v) for k, v in rep["by_size"].items())]
    return "\n".join(lines)


# --------------------------------------------------------------------------- the skill


def run(ctx: skillkit.Context, client: str = "", icp: Any = None, campaign: Optional[str] = None,
        dry_run: bool = False, report_only: bool = False, config_path: Optional[str] = None) -> Dict[str, Any]:
    """The skill. The automations app calls it as run(ctx, client=..., icp={...})."""
    cfg = load_config(config_path)
    db = ctx.db
    c = find_client(db, client)
    added = 0
    if not report_only:
        plan = read_icp(icp)
        rows = grid(c["id"], plan, campaign)
        if len(rows) > int(cfg["max_searches_per_plan"]):
            raise ValueError("The plan has {0} searches, above max_searches_per_plan ({1}) in config.json. "
                             "Use fewer places or keywords, or raise the limit.".format(
                                 len(rows), cfg["max_searches_per_plan"]))
        have = {(r.get("keyword", "").lower(), r.get("location", "").lower())
                for r in db.select_all("lead_searches", {"client_id": "eq." + c["id"]},
                                       columns="keyword,location", order="id")}
        new = [r for r in rows if (r["keyword"].lower(), r["location"].lower()) not in have]
        added = len(new)
        if not dry_run:
            stamp = now_iso()
            for group in skillkit.batches(new):
                db.insert("lead_searches", [dict(r, created_at=stamp) for r in group])
    t = read_tables(db, c["id"])
    if dry_run and added:
        t["searches"] = t["searches"] + [dict(r, id="new-{0}".format(i)) for i, r in enumerate(new)]
    est = estimate(t, cfg)
    rep = segment_report(t)
    if added and not dry_run:
        link = skillkit.os_link(ctx.settings(), "clients/" + c["id"])
        skillkit.post(ctx, "daily-summary", "🧭 TAM Mapper", (
            "*TAM plan for {0}*\n{1} new searches added ({2} to do, about {3} credits).\n"
            "Market: about {4} businesses, about {5} that fit.\n"
            "Next: run the google-maps-scraper skill for this client.").format(
                c["client_name"], added, est["searches_to_do"], est["credits_to_finish"],
                est["businesses_estimated"], est["fits_estimated"]), link=link, button="Open the client")
    return {"ok": True, "dry_run": dry_run, "searches_added": added, "estimate": est, "report": rep,
            "text": as_text(c, est, rep, added, dry_run)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Plan the searches for a client's market and count what is found.")
    ap.add_argument("--client", required=True, help="The client's name or row id")
    ap.add_argument("--icp", help="The ideal customer JSON file (see references/icp_example.json)")
    ap.add_argument("--campaign", help="Optional: the campaign row id these searches are for")
    ap.add_argument("--dry-run", action="store_true", help="Show the plan, write nothing")
    ap.add_argument("--report", action="store_true", help="Only count what is in the tables")
    ap.add_argument("--json", action="store_true", help="Print JSON")
    args = ap.parse_args(argv)
    ctx = skillkit.context(needs=NEEDS)
    try:
        out = run(ctx, client=args.client, icp=args.icp, campaign=args.campaign, dry_run=args.dry_run,
                  report_only=args.report)
    except ValueError as e:
        print(str(e))
        return 2
    print(skillkit.dump(out) if args.json else out["text"])
    return 0


if __name__ == "__main__":
    skillkit.main_guard(main)
