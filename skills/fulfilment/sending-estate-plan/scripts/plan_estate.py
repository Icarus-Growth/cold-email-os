"""Plan one client's sending domains and inboxes, write the plan to the Inbox set-ups board and
ask for approval in Slack. It buys nothing.

    python3 skills/fulfilment/sending-estate-plan/scripts/plan_estate.py --client "Acme Dental"
    python3 skills/fulfilment/sending-estate-plan/scripts/plan_estate.py --client "Acme Dental" --volume 20000
    python3 skills/fulfilment/sending-estate-plan/scripts/plan_estate.py --client "Acme Dental" --preview   (writes nothing)
    python3 skills/fulfilment/sending-estate-plan/scripts/plan_estate.py --client "Acme Dental" --senders "Jane Doe, Sam Lee"

What it writes: one card per inbox provider on the Inbox set-ups board (inbox_batches), in stage
'10 - Approval Needed'; one sending_domains row per domain and one sending_inboxes row per inbox.
Run it again and it fills only what is missing on the open card. Nothing else changes.
"""

import sys
from pathlib import Path

for _up in Path(__file__).resolve().parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
import skillkit  # noqa: E402

HERE = Path(__file__).resolve().parent
for _d in (HERE, HERE.parents[1] / "sending-domain-names" / "scripts"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import argparse  # noqa: E402
from datetime import date  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

import sending_math as math  # noqa: E402
import sending_naming as naming  # noqa: E402
from sending_registrars import get_registrar  # noqa: E402

SKILL = "sending-estate-plan"
BOARD = "inbox_batches"
APPROVAL_STAGE = "10 - Approval Needed"
VOLUME_COLUMN = "monthly_send_volume"  # clients.<this>: the emails a month the client pays for
FORM_SENDERS = "sender_names"           # the onboarding form question: who the emails come from
PROVISION = "python3 skills/fulfilment/sending-estate-provision/scripts/provision_estate.py"


def client_volume(client: Dict[str, Any]) -> Optional[Any]:
    """The monthly send volume on the client row, or None. Read with care: the column may not
    exist yet in an older database."""
    value = client.get(VOLUME_COLUMN)
    return None if value in (None, "", 0, "0") else value


def form_answer(db: Any, client_id: str, question: str) -> Optional[str]:
    """One answer from the client's newest onboarding form, or None."""
    try:
        rows = db.select("onboarding_forms", {"client_id": "eq." + str(client_id)}, order="submitted_at.desc", limit=1)
    except Exception:  # noqa: BLE001 - the form is a nice-to-have here
        return None
    answers = (rows[0].get("answers") if rows else None) or {}
    raw = answers.get(question)
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, list):
        raw = ", ".join(str(x) for x in raw)
    return str(raw).strip() or None if raw is not None else None


def insert_many(db: Any, table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Insert in batches of at most 500 rows. Returns the rows as written (with their ids)."""
    out: List[Dict[str, Any]] = []
    for group in skillkit.batches(rows):
        out += db.request("POST", table, body=group, prefer="return=representation") or []
    return out


def make_plan(ctx: Any, client_ref: Any, volume: Any = None, style: Optional[str] = None,
              senders: Optional[str] = None, enterprise: bool = False, preview: bool = False,
              today: Optional[date] = None, cfg: Optional[Dict[str, Any]] = None,
              names_cfg: Optional[Dict[str, Any]] = None, registrar: Any = None) -> Dict[str, Any]:
    db = ctx.db
    cfg = cfg or math.load_config()
    names_cfg = names_cfg or naming.load_config()
    today = today or date.today()
    reg = registrar or get_registrar(names_cfg.get("registrar"))

    # 1. The client and the numbers. A plain stop here writes nothing.
    client = naming.find_client(db, client_ref)
    cid = str(client["id"])
    name = client.get("client_name") or "the client"
    vol = volume if volume not in (None, "") else client_volume(client)
    if vol is None:
        raise math.PlanError("{0} has no monthly send volume. Add it on the client page in the OS (the '{1}' "
                             "field), or run again with --volume 20000.".format(name, VOLUME_COLUMN))
    counts = math.estate_counts(vol, cfg)
    who = math.parse_senders(senders or form_answer(db, cid, FORM_SENDERS),
                             form_answer(db, cid, "full_name") or client.get("contact_name"))

    # 2. What is already planned. An open card in Approval Needed is filled up, never doubled.
    open_cards = db.select(BOARD, {"client_id": "eq." + cid, "stage": "eq." + APPROVAL_STAGE,
                                   "archived_at": "is.null"})
    batches: Dict[str, Dict[str, Any]] = {}
    for kind, k in counts["kinds"].items():
        card = next((c for c in open_cards if c.get("inbox_provider") == k["provider"]), None)
        have = db.select_all("sending_domains", {"batch_id": "eq." + str(card["id"])}, order="created_at") if card else []
        if len(have) > k["domains"]:
            raise math.PlanError("The open {0} card already has {1} domains, more than the {2} needed now. Archive "
                                 "that card in the OS, then plan again.".format(math.KIND_LABEL[kind], len(have),
                                                                                 k["domains"]))
        batches[kind] = {"kind": kind, "counts": k, "card": card, "have": have, "new": []}

    # 3. New names, checked free at the registrar, never used before.
    missing = {kind: b["counts"]["domains"] - len(b["have"]) for kind, b in batches.items()}
    total = sum(missing.values())
    names: Dict[str, Any] = {"style": None, "checked": 0}
    if total:
        taken = naming.taken_domains(db) | reg.owned()
        names = naming.propose_for_client(total, style or names_cfg.get("default_style"), reg.check_many, names_cfg,
                                          taken, company_name=name, website=client.get("website"), seed=cid)
        picked = list(names["domains"])
        for kind in batches:
            batches[kind]["new"] = picked[:missing[kind]]
            picked = picked[missing[kind]:]

    # 4. Inboxes and money, per card.
    main = naming.domain_of(client.get("website"))
    ready = math.ready_date(today, cfg, enterprise)
    for kind, b in batches.items():
        k = b["counts"]
        domains = [r["domain"] for r in b["have"]] + [d["domain"] for d in b["new"]]
        prices = [r.get("planned_price_usd") for r in b["have"]] + [d.get("price") for d in b["new"]]
        b["domains"] = domains
        b["cost"] = math.cost_estimate(prices, domains, k, cfg)
        one_each = math.assign_senders(domains, who)
        b["inboxes"] = {d: math.inbox_names(one_each[d] if k["inboxes_per_domain"] <= 2 else who,
                                            k["inboxes_per_domain"]) for d in domains}
        b["batch_name"] = "{0} - {1} {2} domains - {3}".format(name, k["domains"], math.KIND_LABEL[kind],
                                                              today.isoformat())
        b["notes"] = plan_notes(counts, kind, b, cfg, reg.name, today, enterprise)

    plan = {"ok": True, "client_id": cid, "client_name": name, "counts": counts, "senders": who,
            "style": names.get("style"), "ready_on": ready.isoformat(), "preview": preview, "cards": []}
    if preview:
        for kind, b in batches.items():
            plan["cards"].append({"kind": kind, "provider": b["counts"]["provider"], "domains": b["domains"],
                                  "cost": b["cost"], "batch_name": b["batch_name"]})
        return plan

    # 5. Write: the card, then the domain rows, then the inbox rows.
    for kind, b in batches.items():
        k = b["counts"]
        fields = {"batch_name": b["batch_name"], "domain_count": k["domains"], "inbox_count": k["inboxes"],
                  "inbox_provider": k["provider"], "domain_registrar": reg.name, "due_date": ready.isoformat(),
                  "notes": b["notes"]}
        if b["card"]:
            card = db.update(BOARD, b["card"]["id"], fields) or dict(b["card"], **fields)
        else:
            card = db.insert(BOARD, dict(fields, client_id=cid, stage=APPROVAL_STAGE))
        bid = str(card["id"])
        insert_many(db, "sending_domains", [{
            "batch_id": bid, "client_id": cid, "domain": d["domain"], "inbox_kind": kind,
            "inbox_provider": k["provider"], "registrar": reg.name, "name_style": d.get("style"),
            "planned_price_usd": d.get("price"), "inboxes_planned": k["inboxes_per_domain"], "status": "planned",
            "warm_days": math.warm_days(cfg, enterprise),
            "forward_to": "https://" + main if main else None} for d in b["new"]])
        rows = db.select_all("sending_domains", {"batch_id": "eq." + bid}, order="created_at")
        with_inboxes = {r.get("domain_id") for r in db.select_all("sending_inboxes", {"batch_id": "eq." + bid})}
        insert_many(db, "sending_inboxes", [{
            "domain_id": r["id"], "batch_id": bid, "client_id": cid, "address": "{0}@{1}".format(i["local"], r["domain"]),
            "first_name": i["first_name"], "last_name": i["last_name"], "inbox_kind": kind, "status": "planned",
            "warmup_tool": cfg.get("warmup_tool")}
            for r in rows if r["id"] not in with_inboxes for i in b["inboxes"].get(r["domain"], [])])
        link = skillkit.card_link(ctx.settings(), BOARD, bid)
        skillkit.ask_for_approval(ctx, "Inbox set-up for {0} needs approval".format(name),
                                  approval_lines(name, kind, b, counts, reg.name, ready, bid), link)
        plan["cards"].append({"kind": kind, "card_id": bid, "provider": k["provider"], "domains": b["domains"],
                              "cost": b["cost"], "link": link})
    return plan


def plan_notes(counts: Dict[str, Any], kind: str, b: Dict[str, Any], cfg: Dict[str, Any], registrar: str,
               today: date, enterprise: bool) -> str:
    k, c = b["counts"], b["cost"]
    return "\n".join([
        "Plan made by the sending-estate-plan skill on {0}.".format(today.isoformat()),
        "Monthly volume: {0:,} emails = {1:,} a day over {2} sending days.".format(
            counts["monthly_volume"], counts["daily_volume"], counts["sending_days"]),
        "This card: {0:,} a day on {1}. {2} inboxes needed at {3} a day each, plus {4}% spare = {5}.".format(
            k["daily_volume"], math.KIND_LABEL[kind], k["inboxes_needed"], k["sends_per_inbox_per_day"],
            counts["spare_buffer_percent"], k["inboxes_with_spare"]),
        "Buys: {0} domains x {1} inboxes = {2} inboxes. Inbox provider: {3}. Registrar: {4}.".format(
            k["domains"], k["inboxes_per_domain"], k["inboxes"], k["provider"], registrar),
        "Warm-up: {0}. Warm {1} days before any cold email. Warm-up never stops.".format(
            math.warmup_words(kind, cfg), math.warm_days(cfg, enterprise)),
        "Cost estimate: {0:,.2f} USD for the domains (first year), then {1:,.2f} USD a month for the inboxes.".format(
            c["domains_first_year_usd"], c["inboxes_month_usd"]),
    ])


def approval_lines(name: str, kind: str, b: Dict[str, Any], counts: Dict[str, Any], registrar: str, ready: date,
                   bid: str) -> List[str]:
    k, c = b["counts"], b["cost"]
    inbox_cost = "{0:,.2f} USD a month for the inboxes".format(c["inboxes_month_usd"]) if c["inbox_price_known"] \
        else "the inbox price is not set in config.json"
    return [
        "*Client:* {0}".format(name),
        "*Buys:* {0} domains at {1}, and {2} {3} inboxes at {4} ({5} a domain).".format(
            k["domains"], registrar, k["inboxes"], math.KIND_LABEL[kind], k["provider"], k["inboxes_per_domain"]),
        "*Cost estimate:* {0:,.2f} USD now for the domains (one year), then {1}.".format(
            c["domains_first_year_usd"], inbox_cost),
        "*Why this size:* {0:,} emails a month = {1:,} a day. This card sends {2:,} a day: {3} a day from each "
        "inbox, with {4}% spare.".format(counts["monthly_volume"], counts["daily_volume"], k["daily_volume"],
                                          k["sends_per_inbox_per_day"], counts["spare_buffer_percent"]),
        "*Domains:* {0}".format(", ".join(b["domains"][:8]) + (" and {0} more".format(len(b["domains"]) - 8)
                                                                if len(b["domains"]) > 8 else "")),
        "*Ready to send:* about {0}, after the warm-up.".format(ready.isoformat()),
        "*After approval:* run `{0} --batch {1} --live`.".format(PROVISION, bid),
    ]


def summary(plan: Dict[str, Any]) -> str:
    c = plan["counts"]
    lines = ["{0}: {1:,} emails a month = {2:,} a day. {3} domains, {4} inboxes. Room for {5:,} a month.".format(
        plan["client_name"], c["monthly_volume"], c["daily_volume"], c["total_domains"], c["total_inboxes"],
        c["monthly_capacity"])]
    for card in plan["cards"]:
        cost = card["cost"]
        lines.append("- {0} at {1}: {2} domains. Estimate {3:,.2f} USD now, then {4:,.2f} USD a month. {5}".format(
            math.KIND_LABEL[card["kind"]], card["provider"], len(card["domains"]), cost["domains_first_year_usd"],
            cost["inboxes_month_usd"], card.get("link") or ""))
        lines.append("  " + ", ".join(card["domains"]))
    lines.append("Senders: " + ", ".join("{0} {1}".format(s["first_name"], s["last_name"]).strip()
                                         for s in plan["senders"]))
    if plan["preview"]:
        lines.append("Preview: nothing was written and nothing was posted.")
    else:
        lines.append("Written to the Inbox set-ups board in '{0}'. The approval ask is in the review channel. "
                     "Nothing is bought until a person moves the card on.".format(APPROVAL_STAGE))
    return "\n".join(lines)


def main(argv: Any = None) -> int:
    ap = argparse.ArgumentParser(description="Plan sending domains and inboxes, and ask for approval.")
    ap.add_argument("--client", required=True, help="the client's name or row id")
    ap.add_argument("--volume", help="emails a month (default: the client's monthly send volume)")
    ap.add_argument("--style", help="domain names: branded, generic or mix")
    ap.add_argument("--senders", help="who the emails come from, for example \"Jane Doe, Sam Lee\"")
    ap.add_argument("--enterprise", action="store_true", help="the targets are big companies: warm longer")
    ap.add_argument("--preview", action="store_true", help="show the plan, write nothing, post nothing")
    args = ap.parse_args(argv)
    reg = get_registrar(naming.load_config().get("registrar"))
    ctx = skillkit.context(needs=list(reg.keys) + ([] if args.preview else ["SLACK_BOT_TOKEN"]), where=reg.where)
    try:
        plan = make_plan(ctx, args.client, args.volume, args.style, args.senders, args.enterprise, args.preview,
                         registrar=reg)
    except (math.PlanError, naming.NamingError) as e:
        print("Stopped: {0}".format(e))
        return 2
    except Exception as e:  # noqa: BLE001
        skillkit.report_failure(ctx, SKILL, "make the plan", e)
        raise
    print(summary(plan))
    return 0


if __name__ == "__main__":
    skillkit.main_guard(main)
