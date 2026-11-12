"""Website classifier: reads each company's home page and asks the AI if the company fits the
client's ideal customer, with a reason and a quote. Writes the answer on the lead_companies row.
Run it from the repo root. Reads .env; never prints a key.

    python3 skills/fulfilment/website-classifier/scripts/run.py --client "Acme Dental"
    python3 skills/fulfilment/website-classifier/scripts/run.py --client "Acme Dental" --live
    python3 skills/fulfilment/website-classifier/scripts/run.py --client "Acme Dental" --live --icp clients/acme-dental/icp.json
    python3 skills/fulfilment/website-classifier/scripts/run.py --client "Acme Dental" --live --retry-errors

1. The rule: --rule, else "fit_rule" in the ideal customer file, else the client's target market.
2. Free checks first (no AI cost): no website, an excluded word in the name or category, a site
   that does not answer, a parked domain, a page with almost no text.
3. Then one AI call per company: fit, not fit or unsure, a confidence, a reason and a quote from
   the page. Below min_confidence in config.json the answer is 'unsure', for a person to check.
4. A site that cannot be read is 'error', never 'not fit'.
5. At most 500 companies a batch. Each answer is written at once, so a crash starts again at
   the next company with no answer.

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
import html as htmllib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: E402

SKILL = "website-classifier"
SKILL_DIR = Path(__file__).resolve().parents[1]
KEY = "ANTHROPIC_API_KEY"
WHERE = dict(skillkit.AI_WHERE)
NEEDS = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "SLACK_BOT_TOKEN", KEY]

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["fit", "not fit", "unsure"]},
        "confidence": {"type": "integer"},
        "reason": {"type": "string"},
        "evidence": {"type": "string"},
        "size_band": {"type": "string"},
    },
    "required": ["verdict", "confidence", "reason", "evidence", "size_band"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- shared block
# The same block is in each list-building skill, so each skill folder works on its own.

APPROVAL_BOARD = "tasks"
APPROVAL_STAGE = "30 - In Review"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


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


# --------------------------------------------------------------------------- the home page


class FetchError(RuntimeError):
    """The site did not answer, or did not answer with a page."""


def page_text(raw_html: str) -> Tuple[str, str, str]:
    """(title, description, visible text) of one HTML page. Pure."""
    title = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
    desc = re.search(r"<meta[^>]+name=[\"']description[\"'][^>]*content=[\"'](.*?)[\"']", raw_html, re.I | re.S) or \
        re.search(r"<meta[^>]+content=[\"'](.*?)[\"'][^>]*name=[\"']description[\"']", raw_html, re.I | re.S)
    body = re.sub(r"<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", raw_html, flags=re.I | re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)

    def clean(t: str) -> str:
        return " ".join(htmllib.unescape(t or "").split())

    return clean(title.group(1) if title else ""), clean(desc.group(1) if desc else ""), clean(body)


def fetch_homepage(url: str, timeout: int, max_bytes: int) -> Tuple[str, str, str]:
    """The home page, read with a short timeout and a size cap. The tests replace this function."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; website-check)",
                                               "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(max_bytes)
            charset = r.headers.get_content_charset() or "utf-8"
            kind = r.headers.get_content_type() or ""
    except urllib.error.HTTPError as e:
        raise FetchError("the site answered {0}".format(e.code))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchError("the site did not answer ({0})".format(getattr(e, "reason", e)))
    if "html" not in kind and "text" not in kind:
        raise FetchError("the address is not a web page ({0})".format(kind))
    return page_text(raw.decode(charset, errors="ignore"))


def ask_judge(prompt: str, system: str) -> Dict[str, Any]:
    """One AI call. The tests replace this function."""
    return skillkit.ask_ai(prompt, system=system, schema=SCHEMA, max_tokens=800, effort="low")


# --------------------------------------------------------------------------- one company


def site_url(row: Dict[str, Any]) -> str:
    url = (row.get("website") or "").strip() or (row.get("domain") or "").strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def build_prompt(row: Dict[str, Any], rule: str, icp: Dict[str, Any], page: Tuple[str, str, str],
                 max_chars: int) -> str:
    title, desc, text = page
    sizes = ", ".join(icp.get("sizes") or []) or "any"
    exclude = ", ".join(icp.get("exclude") or []) or "none"
    return "\n".join([
        "THE RULE (does this company fit?): " + rule,
        "Company sizes the client wants (staff): " + sizes,
        "Never a fit: " + exclude,
        "",
        "Company: {0}".format(row.get("company_name") or ""),
        "Google Maps category: {0}".format(row.get("category") or "unknown"),
        "Web address: {0}".format(site_url(row)),
        "Page title: " + title,
        "Page description: " + desc,
        "Home page text (cut to {0} characters):".format(max_chars),
        text[:max_chars],
    ])


def judge_company(row: Dict[str, Any], rule: str, icp: Dict[str, Any], system: str, cfg: Dict[str, Any],
                  fetch: Callable[..., Tuple[str, str, str]], judge: Callable[[str, str], Dict[str, Any]]
                  ) -> Dict[str, Any]:
    """The answer for one company, as the columns to write. An AI failure raises AIError (the
    row is then left for the next run). Everything else is an answer."""
    def done(status: str, conf: Optional[int], reason: str, evidence: str = "", method: str = "free check",
             size: Optional[str] = None) -> Dict[str, Any]:
        out = {"fit_status": status, "fit_confidence": conf, "fit_reason": reason[:500],
               "fit_evidence": evidence[:500] or None, "fit_method": method, "fit_checked_at": now_iso()}
        if size:
            out["size_band"] = size
        return out

    url = site_url(row)
    if not url:
        return done("error", None, "No website, so the site cannot be checked.")
    words = " {0} {1} ".format(row.get("company_name") or "", row.get("category") or "").lower()
    for bad in icp.get("exclude") or []:
        if re.search(r"\b" + re.escape(bad.lower()) + r"\b", words):
            return done("not fit", 100, "The name or category has the excluded word '{0}'.".format(bad))
    try:
        page = fetch(url, int(cfg["fetch_timeout_seconds"]), int(cfg["fetch_max_bytes"]))
    except FetchError as e:
        return done("error", None, "The site could not be read: {0}.".format(e))
    joined = " ".join(page).lower()
    for phrase in cfg.get("parked_phrases") or []:
        if phrase.lower() in joined:
            return done("not fit", 100, "The domain is parked or for sale.", phrase)
    if len(page[2]) < int(cfg["min_text_chars"]):
        return done("error", None, "The home page has too little text to judge ({0} characters).".format(len(page[2])))
    answer = judge(build_prompt(row, rule, icp, page, int(cfg["max_page_chars"])), system)
    verdict = answer.get("verdict") if answer.get("verdict") in ("fit", "not fit", "unsure") else "unsure"
    conf = max(0, min(100, int(answer.get("confidence") or 0)))
    reason = str(answer.get("reason") or "")
    if verdict != "unsure" and conf < int(cfg["min_confidence"]):
        reason = "Low confidence ({0}), so a person checks it. The AI leaned '{1}': {2}".format(conf, verdict, reason)
        verdict = "unsure"
    size = str(answer.get("size_band") or "").strip()
    return done(verdict, conf, reason, str(answer.get("evidence") or ""), "ai",
                size if size and size.lower() != "unknown" else None)


# --------------------------------------------------------------------------- the run


def read_rule(rule: Optional[str], icp: Dict[str, Any], client: Dict[str, Any]) -> str:
    text = (rule or icp.get("fit_rule") or client.get("target_market") or "").strip()
    if not text:
        raise ValueError("No rule to judge by. Give --rule \"...\", or a fit_rule in the ideal customer file "
                         "(--icp), or fill in the client's target market in the OS.")
    return text


def read_icp(icp: Any) -> Dict[str, Any]:
    if not icp:
        return {}
    if isinstance(icp, dict):
        return icp
    p = Path(icp)
    if not p.exists():
        raise ValueError("The ideal customer file '{0}' does not exist.".format(icp))
    try:
        return json.loads(p.read_text())
    except ValueError as e:
        raise ValueError("The ideal customer file is not valid JSON: {0}".format(e))


def todo_filter(client_id: str, retry_errors: bool) -> Dict[str, str]:
    f = {"client_id": "eq." + client_id, "archived_at": "is.null"}
    if retry_errors:
        f["fit_status"] = "eq.error"
    else:
        f["fit_checked_at"] = "is.null"
    return f


def spent_since(db: Any, client_id: str, since: str) -> int:
    return len(db.select_all("lead_companies", {"client_id": "eq." + client_id, "fit_method": "eq.ai",
                                                "fit_checked_at": "gte." + since}, columns="id", order="id"))


def run(ctx: skillkit.Context, client: str = "", live: bool = False, rule: Optional[str] = None,
        icp: Any = None, retry_errors: bool = False, config_path: Optional[str] = None,
        fetch: Optional[Callable[..., Tuple[str, str, str]]] = None,
        judge: Optional[Callable[[str, str], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The skill. The automations app calls it as run(ctx, client=..., live=True)."""
    skillkit.need([KEY], WHERE)
    cfg = load_config(config_path)
    db = ctx.db
    c = find_client(db, client)
    plan = read_icp(icp)
    the_rule = read_rule(rule, plan, c)
    system = (SKILL_DIR / "references" / "judge.md").read_text()
    todo_all = db.select_all("lead_companies", todo_filter(c["id"], retry_errors), columns="id", order="id")
    per_run = min(len(todo_all), int(cfg["batch_size"]) * int(cfg["max_batches_per_run"]))
    if not todo_all:
        return {"ok": True, "message": "Nothing to do: every company for {0} has an answer.".format(c["client_name"])}
    cost = per_run * float(cfg["usd_per_ai_check"])
    what = "Check {0:,} company websites for {1} with the AI, against: {2} (about {3:.2f} USD)".format(
        per_run, c["client_name"], the_rule[:160], cost)
    if not live:
        return {"ok": True, "dry_run": True, "companies_to_check": per_run, "companies_waiting": len(todo_all),
                "ai_checks_needed": per_run, "about_usd": round(cost, 2), "rule": the_rule,
                "message": "Dry run: nothing spent. Add --live to run. Above {0} AI checks a person approves "
                           "first.".format(cfg["approval_above"])}
    allowed = spend_gate(ctx, c, per_run, "AI checks", what, cfg, lambda since: spent_since(db, c["id"], since))
    fetch = fetch or fetch_homepage
    judge = judge or ask_judge
    totals = {"checked": 0, "fit": 0, "not fit": 0, "unsure": 0, "error": 0, "ai": 0, "ai_failed": 0}
    stop: List[str] = []
    seen_ids: set = set()  # with --retry-errors a row can stay 'error'; it is tried once a run

    def one(row: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], str]:
        try:
            return row, judge_company(row, the_rule, plan, system, cfg, fetch, judge), ""
        except skillkit.AIError as e:
            return row, None, str(e)

    def work(rows: List[Dict[str, Any]]) -> int:
        if stop:
            return 0
        rows = [r for r in rows if r["id"] not in seen_ids][: max(0, allowed - totals["ai"])]
        seen_ids.update(r["id"] for r in rows)
        n = 0
        with ThreadPoolExecutor(max_workers=max(1, int(cfg["workers"]))) as pool:
            results = list(pool.map(one, rows))
        for row, fields, err in results:
            if fields is None:
                totals["ai_failed"] += 1
                if not stop:
                    stop.append(err)
                continue
            db.update("lead_companies", row["id"], fields)
            totals["checked"] += 1
            totals[fields["fit_status"]] += 1
            totals["ai"] += 1 if fields["fit_method"] == "ai" else 0
            n += 1
        return n

    size = min(int(cfg["batch_size"]), skillkit.BATCH_MAX)
    skillkit.run_in_batches(lambda limit: db.select("lead_companies", todo_filter(c["id"], retry_errors),
                                                    order="created_at", limit=limit),
                            work, size=size, max_batches=int(cfg["max_batches_per_run"]))
    link = skillkit.os_link(ctx.settings(), "clients/" + c["id"])
    if stop:
        skillkit.report_failure(ctx, SKILL, "AI check", skillkit.AIError(stop[0]), link)
    left = len(db.select_all("lead_companies", todo_filter(c["id"], False), columns="id", order="id"))
    text = ("*Website classifier: {0}*\n{1:,} companies checked: {2:,} fit, {3:,} not fit, {4:,} unsure "
            "(a person checks these), {5:,} could not be read.\n{6:,} AI checks used. {7:,} companies still "
            "to check.\nNext: add the people at the companies that fit, then run the email-guesser skill.").format(
        c["client_name"], totals["checked"], totals["fit"], totals["not fit"], totals["unsure"], totals["error"],
        totals["ai"], left)
    if totals["checked"]:
        skillkit.post(ctx, "daily-summary", "🔎 Website Classifier", text, link=link, button="Open the client")
    return {"ok": not stop, "checked": totals["checked"], "fit": totals["fit"], "not_fit": totals["not fit"],
            "unsure": totals["unsure"], "error": totals["error"], "ai_checks_used": totals["ai"],
            "ai_failed": totals["ai_failed"], "companies_left": left,
            "message": ("The AI call failed, so the run stopped: {0}".format(stop[0]) if stop else "Done.")}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Check each company website against the client's ideal customer.")
    ap.add_argument("--client", required=True, help="The client's name or row id")
    ap.add_argument("--live", action="store_true", help="Really call the AI (without it: a dry run)")
    ap.add_argument("--rule", help="The rule, in one sentence (else the ideal customer file, else the client's "
                                   "target market)")
    ap.add_argument("--icp", help="The ideal customer JSON file (fit_rule, exclude, sizes)")
    ap.add_argument("--retry-errors", action="store_true", help="Check again the sites that could not be read")
    args = ap.parse_args(argv)
    ctx = skillkit.context(needs=NEEDS, where=WHERE)
    try:
        out = run(ctx, client=args.client, live=args.live, rule=args.rule, icp=args.icp,
                  retry_errors=args.retry_errors)
    except ValueError as e:
        print(str(e))
        return 2
    print(skillkit.dump(out))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    skillkit.main_guard(main)
