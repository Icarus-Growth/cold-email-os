"""The set-up engine: takes an approved Inbox set-ups card from domains on paper to inboxes ready
to send. One call moves every domain of the card as far as it can go NOW, and stops each one at
the first thing it must wait for. It never sleeps. Run it again (by hand, or the daily job does)
and each domain goes on from its own status.

A domain's status, in order (sending_domains.status):

    planned -> bought -> ordered -> nameservers_set -> inboxes_active -> dns_verified -> warming -> ready
       buy      order     DNS        inboxes built      auth gate         warm-up on      warm days done

Safety, in this order:
1. Approval: a PERSON moved the card out of '10 - Approval Needed' (the stage log says who).
   No approval = nothing is read from a vendor, nothing is written, nothing is spent.
2. Dry run unless live: every vendor call goes to a recorder and a simulator. Nothing is sent.
   The dry run writes one note on each domain row: what a live run would do.
3. Spend guard: only the domains on the card, never more domains or inboxes than the card says,
   never a price above the approved price, never more than the approved total, and the
   registrar credit is checked before the first buy.
4. One domain's failure stops only that domain. It is posted once to pipeline-errors.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import skillkit
import sending_dns as dns
import sending_http as http
import sending_math as math
from sending_providers import get_provider
from sending_registrars import get_registrar
from sending_warmup import get_tool

SKILL = "sending-estate-provision"
BOARD = "inbox_batches"
APPROVAL_STAGE = "10 - Approval Needed"
ORDER = ["planned", "bought", "ordered", "nameservers_set", "inboxes_active", "dns_verified", "warming", "ready"]
DOING = {"planned": "buy the domain", "bought": "order the inboxes", "ordered": "set the DNS",
         "nameservers_set": "wait for the inboxes", "inboxes_active": "check SPF, DKIM, DMARC and MX",
         "dns_verified": "start the warm-up", "warming": "finish the warm-up"}
SPENDS = ("planned", "bought")
CARD_STAGE = [("ready", "100 - Ready To Send"), ("warming", "40 - Warming"), ("bought", "30 - Setting Up Inboxes"),
              ("planned", "20 - Buying Domains")]
UPDATE_BOT = "📬 Inbox Set-up"
STUCK_BOT = "🙋 Needs A Person"


class SpendGuard(ValueError):
    """The spend would go past what was approved. Nothing more is bought."""


class Park(Exception):
    """This domain waits for its provider's one big order (made after every domain is read)."""


class Done(object):
    def __init__(self, fields: Optional[Dict[str, Any]] = None, note: str = "",
                 inbox: Optional[List[Tuple[str, Dict[str, Any]]]] = None) -> None:
        self.fields, self.note, self.inbox = fields or {}, note, inbox or []


class Wait(object):
    def __init__(self, reason: str, minutes: Optional[int] = 30, fields: Optional[Dict[str, Any]] = None,
                 inbox: Optional[List[Tuple[str, Dict[str, Any]]]] = None) -> None:
        self.reason, self.minutes, self.fields, self.inbox = reason, minutes, fields or {}, inbox or []


def stage_no(stage: Any) -> int:
    m = re.match(r"^\s*(\d+)", str(stage or ""))
    return int(m.group(1)) if m else -1


def as_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class Run(object):
    """One set-up run of one card: what every step needs to know."""

    def __init__(self, ctx: Any, batch: Dict[str, Any], client: Dict[str, Any], domains: List[Dict[str, Any]],
                 inboxes: Dict[str, List[Dict[str, Any]]], live: bool, spend: bool, force: bool,
                 now: Callable[[], datetime], cfg: Dict[str, Any], plan_cfg: Dict[str, Any]) -> None:
        self.ctx, self.db, self.batch, self.client = ctx, ctx.db, batch, client
        self.live, self.spend, self.force, self._now = live, spend, force, now
        self.cfg, self.plan_cfg = cfg, plan_cfg
        self.client_name = client.get("client_name") or "Client"
        self.client_slug = re.sub(r"[^a-z0-9]", "", self.client_name.lower())[:16] or "client"
        self.registrar = get_registrar(batch.get("domain_registrar"))
        self.provider = get_provider(batch.get("inbox_provider"))
        self.tool = get_tool(plan_cfg.get("warmup_tool"))
        self.inboxes = inboxes
        self.tolerance = float(cfg.get("price_tolerance_usd") or 0)
        self.approved_total = sum(float(d.get("planned_price_usd") or 0) for d in domains)
        self.spent = sum(float(d.get("paid_price_usd") or 0) for d in domains)
        self.ordered = sum(len(inboxes.get(d["id"], [])) for d in domains if ORDER.index(d["status"]) >= 2)
        self.order_results: Dict[str, Any] = {}
        self.link = skillkit.card_link(ctx.settings(), BOARD, str(batch["id"]))
        self._ws: Optional[str] = None

    def now(self) -> datetime:
        return self._now()

    def iso(self) -> str:
        return self.now().isoformat()

    def workspace(self) -> str:
        """The client's workspace in the warm-up tool, found or made once per run."""
        if self._ws is None:
            self._ws = self.tool.ensure_workspace(self.client_name)
        return self._ws


# --------------------------------------------------------------------------- the entry


def provision(ctx: Any, batch_id: str, live: bool = False, spend: Optional[bool] = None, force: bool = False,
              only: Optional[List[str]] = None, now: Optional[Callable[[], datetime]] = None,
              cfg: Optional[Dict[str, Any]] = None, plan_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Move one approved card on. `live` sends real calls; `spend` (live only) allows buying.
    The daily job runs live without spend: it carries on set-ups a person already started."""
    import json
    from pathlib import Path

    db = ctx.db
    cfg = cfg or json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())
    plan_cfg = plan_cfg or math.load_config()
    now = now or (lambda: datetime.now(timezone.utc))
    spend = bool(live) if spend is None else bool(spend and live)

    batch = db.get(BOARD, str(batch_id))
    if not batch:
        raise ValueError("No Inbox set-ups card with the id '{0}'.".format(batch_id))
    # 1. Approval first. Before this line nothing is read from a vendor and nothing is written.
    skillkit.require_approval(db, BOARD, str(batch_id), APPROVAL_STAGE)
    if stage_no(batch.get("stage")) <= stage_no(APPROVAL_STAGE):
        raise skillkit.NotApproved("The card is in '{0}'. A person must move it out of '{1}' to approve it.".format(
            batch.get("stage"), APPROVAL_STAGE))

    domains = db.select_all("sending_domains", {"batch_id": "eq." + str(batch_id)}, order="created_at")
    inbox_rows = db.select_all("sending_inboxes", {"batch_id": "eq." + str(batch_id)})
    guard_counts(batch, domains, inbox_rows)
    by_domain: Dict[str, List[Dict[str, Any]]] = {}
    for i in inbox_rows:
        by_domain.setdefault(str(i["domain_id"]), []).append(i)
    client = db.get("clients", str(batch["client_id"])) or {}
    run = Run(ctx, batch, client, domains, by_domain, live, spend, force, now, cfg, plan_cfg)

    if live:
        keys = list(run.registrar.keys) + list(run.provider.keys) + list(run.tool.keys)
        where = dict(run.registrar.where, **run.provider.where)
        where.update(run.tool.where)
        skillkit.need(list(dict.fromkeys(keys)), where)

    todo = [d for d in domains if d.get("status") != "ready"]
    if only:
        wanted = {x.strip().lower() for x in only}
        todo = [d for d in todo if d["domain"].lower() in wanted]

    recorder = old = None
    results: List[Dict[str, Any]] = []
    try:
        if not live:
            recorder = http.RecordingTransport(Simulator(domains, by_domain).respond)
            old = http.set_transport(recorder)
            http.dry_run(True)
        if spend:
            check_credit(run, todo)
        for group in skillkit.batches(todo):
            results += advance_group(run, group)
    finally:
        missing = sorted(http.missing_keys) if not live else []
        if old is not None:
            http.set_transport(old)
            http.dry_run(False)

    out = {"ok": not any(r["state"] == "failed" for r in results), "live": live, "spend": spend,
           "batch_id": str(batch_id), "batch_name": batch.get("batch_name"), "domains": results,
           "stage": batch.get("stage"), "missing_keys": missing, "link": run.link,
           "vendor_calls": len(recorder.calls) if recorder else None}
    if live:
        out["stage"] = finish_card(run)
    else:
        stamp = run.iso()
        for r in results:
            db.update("sending_domains", r["id"], {"last_note": "Dry run: " + "; ".join(r["notes"])[:2000],
                                                   "checked_at": stamp})
    return out


def guard_counts(batch: Dict[str, Any], domains: List[Dict[str, Any]], inboxes: List[Dict[str, Any]]) -> None:
    """The card says how many domains and inboxes were approved. More rows than that = refuse."""
    if not domains:
        raise ValueError("The card has no sending domains. Make the plan with the sending-estate-plan skill first.")
    if len(domains) > int(batch.get("domain_count") or 0):
        raise SpendGuard("The card approves {0} domains but has {1} domain rows. Nothing was done. Fix the rows or "
                         "plan again.".format(batch.get("domain_count"), len(domains)))
    if len(inboxes) > int(batch.get("inbox_count") or 0):
        raise SpendGuard("The card approves {0} inboxes but has {1} inbox rows. Nothing was done. Fix the rows or "
                         "plan again.".format(batch.get("inbox_count"), len(inboxes)))
    bad = [d["domain"] for d in domains if d.get("status") not in ORDER]
    if bad:
        raise ValueError("Unknown status on: {0}. Use one of: {1}.".format(", ".join(bad), ", ".join(ORDER)))


def check_credit(run: Run, todo: List[Dict[str, Any]]) -> None:
    """All or nothing: refuse before the first buy if the registrar credit cannot pay for all."""
    to_buy = [d for d in todo if d.get("status") == "planned"]
    if not to_buy:
        return
    have = run.registrar.balance_usd()
    need = sum(float(d.get("planned_price_usd") or 0) for d in to_buy)
    if have is not None and have + 1e-9 < need:
        raise SpendGuard("The {0} credit is {1:.2f} USD. Buying {2} domains needs {3:.2f} USD. Nothing was bought. "
                         "Add credit at the registrar, then run again.".format(run.registrar.name, have, len(to_buy), need))


# --------------------------------------------------------------------------- the step loop


def advance_group(run: Run, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    parked: List[Dict[str, Any]] = []
    for row in rows:
        r = advance(run, row)
        if r["state"] == "parked":
            parked.append(r)
        else:
            results[row["id"]] = r
    if parked:  # one order for every waiting domain, then each goes on
        items = [{"row": p["row"], "inboxes": run.inboxes.get(p["id"], [])} for p in parked]
        try:
            run.order_results.update(run.provider.order(run, items))
        except Exception as e:  # noqa: BLE001
            for p in parked:
                run.order_results[p["domain"]] = e
        for p in parked:
            results[p["id"]] = advance(run, p["row"], p["notes"])
    return [results[r["id"]] for r in rows if r["id"] in results]


def advance(run: Run, row: Dict[str, Any], notes: Optional[List[str]] = None) -> Dict[str, Any]:
    notes = list(notes or [])
    row = dict(row)
    while True:
        status = row["status"]
        if status == "ready":
            return result(row, "done", notes)
        if (run.live and not run.force and row.get("next_check_at") and as_time(row["next_check_at"]) > run.now()):
            return result(row, "waiting", notes, row.get("waiting_for"))
        if run.live and not run.spend and status in SPENDS:
            reason = "A person must run the live set-up (--live) to {0}.".format(DOING[status])
            save(run, row, {"waiting_for": reason})
            return result(row, "waiting", notes, reason)
        try:
            outcome = STEPS[status](run, row)
        except Park:
            return dict(result(row, "parked", notes), row=row)
        except http.VendorNotReady as e:
            outcome = Wait(str(e), 30)
        except Exception as e:  # noqa: BLE001 - this domain stops here; the others go on
            words = "Could not {0}: {1}".format(DOING[status], e)
            if run.live:
                save(run, row, {"last_error": words[:1000], "waiting_for": None})
                skillkit.report_failure(run.ctx, SKILL, "{0} ({1})".format(DOING[status], row["domain"]), e, run.link)
            else:
                notes.append("would stop: " + words)
            return result(row, "failed", notes, error=words)

        if isinstance(outcome, Wait):
            if not run.live:  # a dry run never waits: it says so and walks on
                notes.append("would wait: " + outcome.reason)
                outcome = Done(outcome.fields, inbox=outcome.inbox)
            else:
                fields = dict(outcome.fields, waiting_for=outcome.reason, next_check_at=(
                    run.now() + timedelta(minutes=outcome.minutes)).isoformat() if outcome.minutes else None)
                stuck_check(run, row, outcome.reason, fields)
                save(run, row, fields, outcome.inbox)
                return result(row, "waiting", notes, outcome.reason)

        nxt = ORDER[ORDER.index(status) + 1]
        fields = dict(outcome.fields, status=nxt, step_started_at=run.iso(), waiting_for=None, next_check_at=None,
                      last_error=None)
        if outcome.note:
            notes.append(outcome.note)
            if run.live:
                fields["last_note"] = outcome.note
        save(run, row, fields, outcome.inbox)


def save(run: Run, row: Dict[str, Any], fields: Dict[str, Any],
         inbox: Optional[List[Tuple[str, Dict[str, Any]]]] = None) -> None:
    """Live: write the domain row (and its inbox rows) now, before the next step. Dry: in memory."""
    row.update(fields)
    by_id = {str(i["id"]): i for i in run.inboxes.get(row["id"], [])}
    for inbox_id, f in inbox or []:
        if str(inbox_id) in by_id:
            by_id[str(inbox_id)].update(f)
    if not run.live:
        return
    run.db.update("sending_domains", row["id"], fields)
    for group in skillkit.batches(inbox or []):
        for inbox_id, f in group:
            run.db.update("sending_inboxes", inbox_id, f)


def stuck_check(run: Run, row: Dict[str, Any], reason: str, fields: Dict[str, Any]) -> None:
    hours = (run.cfg.get("give_up_hours") or {}).get(row["status"])
    started = as_time(row.get("step_started_at"))
    if not hours or not started or run.now() - started < timedelta(hours=float(hours)):
        return
    words = "Waiting more than {0} hours to {1}: {2}".format(hours, DOING[row["status"]], reason)
    fields["last_error"] = words
    if skillkit.first_time(run.ctx.seen, "sending-stuck:{0}:{1}".format(row["id"], row["status"])):
        skillkit.post(run.ctx, "needs-a-person", STUCK_BOT,
                      "*Inbox set-up is stuck:* {0} ({1})\n{2}\n_Check it at the inbox provider. It keeps checking by "
                      "itself; this message comes once a day at most._".format(row["domain"], run.client_name, words),
                      link=run.link)


def result(row: Dict[str, Any], state: str, notes: List[str], waiting: Optional[str] = None,
           error: Optional[str] = None) -> Dict[str, Any]:
    return {"id": row["id"], "domain": row["domain"], "status": row["status"], "state": state, "notes": list(notes),
            "waiting_for": waiting, "error": error}


# --------------------------------------------------------------------------- the steps


def step_buy(run: Run, row: Dict[str, Any]) -> Any:
    d = row["domain"]
    if run.registrar.lookup(d):  # already in the account: a buy whose write was lost. Never buy twice.
        return Done({"bought_at": run.iso()}, "already in the {0} account, not bought again".format(run.registrar.name))
    q = run.registrar.quote(d)
    if not q["available"]:
        raise http.VendorError("{0} is no longer free. Plan a new name for it.".format(d))
    if q["premium"]:
        raise http.VendorError("{0} is now a premium name. It is not bought.".format(d))
    approved = row.get("planned_price_usd")
    if approved in (None, ""):
        raise SpendGuard("{0} has no approved price. Plan it again.".format(d))
    cost = round(float(q["price"]) * int(q["years"]), 2)
    if cost > float(approved) * int(q["years"]) + run.tolerance:
        raise SpendGuard("{0} now costs {1:.2f} USD; the approved price is {2:.2f} USD. It was not bought. Plan it "
                         "again for a new approval.".format(d, cost, float(approved)))
    if run.spent + cost > run.approved_total + run.tolerance:
        raise SpendGuard("Buying {0} would take the card to {1:.2f} USD, over the approved {2:.2f} USD.".format(
            d, run.spent + cost, run.approved_total))
    run.registrar.buy(d, cost, "sending-{0}-{1}".format(run.batch["id"], d))
    run.spent += cost
    return Done({"paid_price_usd": cost, "bought_at": run.iso()},
                "{0} {1} for {2:.2f} USD (approved {3:.2f} USD)".format("bought" if run.live else "would buy", d,
                                                                         cost, float(approved)))


def step_order(run: Run, row: Dict[str, Any]) -> Any:
    boxes = run.inboxes.get(row["id"], [])
    planned = int(row.get("inboxes_planned") or 0)
    if not boxes or len(boxes) != planned:
        raise SpendGuard("{0} has {1} inbox rows but {2} were approved. Nothing was ordered.".format(
            row["domain"], len(boxes), planned))
    if run.ordered + len(boxes) > int(run.batch.get("inbox_count") or 0):
        raise SpendGuard("Ordering {0} more inboxes would pass the approved {1}.".format(
            len(boxes), run.batch.get("inbox_count")))
    if run.provider.one_order_for_many and row["domain"] not in run.order_results:
        raise Park()
    got = run.order_results.pop(row["domain"]) if row["domain"] in run.order_results else \
        run.provider.order(run, [{"row": row, "inboxes": boxes}]).get(row["domain"])
    if isinstance(got, Exception):
        raise got
    if not got:
        raise http.VendorError("{0} gave no answer for this domain.".format(run.provider.name))
    run.ordered += len(boxes)
    return Done({"provider_ref": got.get("ref")},
                got.get("note") or "{0} {1} {2} inboxes at {3}".format(
                    "ordered" if run.live else "would order", len(boxes), math.KIND_LABEL.get(row["inbox_kind"], ""),
                    run.provider.name),
                inbox=[(i["id"], {"status": "ordered"}) for i in boxes])


def step_dns(run: Run, row: Dict[str, Any]) -> Any:
    d, mode = row["domain"], run.provider.dns_mode
    if mode == "records":
        records = run.provider.dns_records(run, row)
        if not records:
            return Wait("{0} has not given the DNS records yet".format(run.provider.name), 15)
        run.registrar.set_dns_records(d, records)
        if row.get("forward_to"):
            run.registrar.add_forward(d, row["forward_to"])
        return Done({}, "wrote {0} DNS records and the forward at {1}".format(len(records), run.registrar.name))
    resolving = dns.nameservers(d)
    if mode == "provider_sets":
        moved = resolving and not any(n.endswith(run.registrar.default_ns_suffix) for n in resolving)
        if not moved:
            return Wait("waiting for {0}'s staff to connect the domain (the nameservers have not moved yet)".format(
                run.provider.name), 60)
        return Done({"nameservers": resolving}, "the nameservers moved to {0}".format(run.provider.name))
    wanted = sorted(n.lower().rstrip(".") for n in run.provider.nameservers(run, row))
    if not wanted:
        return Wait("{0} has not given the nameservers yet".format(run.provider.name), 10)
    if set(wanted) <= set(resolving):
        return Done({"nameservers": wanted}, "the nameservers point at {0}".format(run.provider.name))
    if sorted(row.get("nameservers") or []) != wanted:
        if not run.provider.sets_own_nameservers(run):
            run.registrar.set_nameservers(d, wanted)
        return Wait("nameservers set to {0}; waiting for them to spread (15 minutes or more)".format(
            ", ".join(wanted)), 15, fields={"nameservers": wanted})
    return Wait("waiting for the nameservers to spread", 15)


def step_active(run: Run, row: Dict[str, Any]) -> Any:
    state, words = run.provider.status(run, row)
    if state == "failed":
        raise http.VendorError(words)
    if state != "active":
        return Wait(words, 60)
    return Done({}, words, inbox=[(i["id"], {"status": "active"}) for i in run.inboxes.get(row["id"], [])])


def step_auth(run: Run, row: Dict[str, Any]) -> Any:
    a = dns.check_auth(row["domain"], row["inbox_kind"])
    if a["missing"]:
        return Wait("not there yet: {0}".format(", ".join(a["missing"])), 30)
    note = "SPF, DKIM, DMARC and MX all pass"
    if a["dmarc_policy"] == "reject":
        note += ". DMARC is p=reject from day one (the provider set it). That is strict, but safe"
    return Done({"dns_verified_at": run.iso()}, note)


def step_warmup(run: Run, row: Dict[str, Any]) -> Any:
    ws = run.workspace()
    run.provider.hand_over(run, row)
    accounts = run.tool.accounts(ws, row["domain"])
    planned = int(row.get("inboxes_planned") or 0)
    if len(accounts) < planned:
        return Wait("{0} of {1} inboxes are in {2} so far".format(len(accounts), planned, run.tool.name), 60)
    profile = math.warmup_profile(row["inbox_kind"], run.plan_cfg)
    run.tool.start(ws, [a["id"] for a in accounts], profile)
    ids = {a["email"]: a["id"] for a in accounts}
    stamp = run.iso()
    updates = [(i["id"], {"status": "warming", "warmup_account_id": ids.get(i["address"].lower()),
                          "warmup_daily_limit": int(profile["max_per_day"]), "warmup_started_at": stamp})
               for i in run.inboxes.get(row["id"], []) if i["address"].lower() in ids]
    return Done({"warmup_started_at": stamp}, "warm-up on for {0} inboxes in {1}: {2}".format(
        len(accounts), run.tool.name, math.warmup_words(row["inbox_kind"], run.plan_cfg)), inbox=updates)


def step_ready(run: Run, row: Dict[str, Any]) -> Any:
    started = as_time(row.get("warmup_started_at")) or run.now()
    days = (run.now() - started).days
    profile = math.warmup_profile(row["inbox_kind"], run.plan_cfg)
    boxes = run.inboxes.get(row["id"], [])
    updates: List[Tuple[str, Dict[str, Any]]] = []
    after = profile.get("after_step_down_per_day")
    if profile.get("step_down_after_days") is not None and days >= int(profile["step_down_after_days"]):
        lower = [i for i in boxes if i.get("warmup_account_id") and i.get("warmup_daily_limit") != after]
        if lower:
            run.tool.step_down(run.workspace(), [i["warmup_account_id"] for i in lower], int(after))
            updates = [(i["id"], {"warmup_daily_limit": int(after)}) for i in lower]
    warm = int(row.get("warm_days") or math.warm_days(run.plan_cfg))
    if days < warm:
        due = started + timedelta(days=warm)
        minutes = int((due - run.now()).total_seconds() // 60) + 1
        return Wait("warming for {0} days, until {1}".format(warm, due.date().isoformat()), min(minutes, 24 * 60),
                    inbox=updates)
    stamp = run.iso()
    updates += [(i["id"], {"status": "ready", "ready_at": stamp}) for i in boxes]
    return Done({"ready_at": stamp}, "warmed {0} days: ready to send. Warm-up stays on".format(days), inbox=updates)


STEPS = {"planned": step_buy, "bought": step_order, "ordered": step_dns, "nameservers_set": step_active,
         "inboxes_active": step_auth, "dns_verified": step_warmup, "warming": step_ready}


# --------------------------------------------------------------------------- the card


def finish_card(run: Run) -> str:
    """After a live run: move the card on (never back), fill its dates, tell the team."""
    db, batch = run.db, run.batch
    rows = db.select_all("sending_domains", {"batch_id": "eq." + str(batch["id"])})
    lowest = min(ORDER.index(r["status"]) for r in rows)
    target = next(stage for status, stage in CARD_STAGE if lowest >= ORDER.index(status))
    fields: Dict[str, Any] = {}
    starts = sorted(str(r["warmup_started_at"])[:10] for r in rows if r.get("warmup_started_at"))
    if starts and batch.get("warmup_started_on") != starts[0]:
        fields["warmup_started_on"] = starts[0]
    if lowest == ORDER.index("ready") and not batch.get("ready_on"):
        fields["ready_on"] = run.now().date().isoformat()
    moved = stage_no(target) > stage_no(batch.get("stage"))
    if moved:
        fields["stage"] = target
    if fields:
        db.update(BOARD, batch["id"], fields)
    bought = sorted(r["domain"] for r in rows if ORDER.index(r["status"]) >= 1)
    note_client_domains(run, bought)
    if moved:
        skillkit.post(run.ctx, "task-updates", UPDATE_BOT, stage_message(run, target, rows), link=run.link)
    return target if moved else str(batch.get("stage"))


def stage_message(run: Run, stage: str, rows: List[Dict[str, Any]]) -> str:
    n = len(rows)
    inboxes = sum(int(r.get("inboxes_planned") or 0) for r in rows)
    head = "*Inbox set-up for {0} moved to {1}.*\n{2}".format(run.client_name, stage, run.batch.get("batch_name"))
    if stage.startswith("100"):
        return head + ("\n{0} domains and {1} inboxes are warm and ready to send. Warm-up stays on.\n"
                       "_Next: add the inboxes to the client's campaigns._".format(n, inboxes))
    if stage.startswith("40"):
        return head + ("\nWarm-up is on for all {0} inboxes. They are ready after the warm-up days.\n"
                       "_Nothing to do. The daily job checks them._".format(inboxes))
    if stage.startswith("30"):
        return head + ("\nAll {0} domains are bought, for {1:.2f} USD. The inbox provider is building {2} inboxes.\n"
                       "_Nothing to do. The daily job checks them._".format(n, run.spent, inboxes))
    return head


def note_client_domains(run: Run, bought: List[str]) -> None:
    """Keep the client's 'sending domains' field (names only) in step with what was bought."""
    if not bought or "sending_domains" not in run.client:
        return
    have = [d.strip() for d in str(run.client.get("sending_domains") or "").split(",") if d.strip()]
    merged = sorted(set(have) | set(bought))
    if merged != sorted(set(have)):
        run.db.update("clients", run.client["id"], {"sending_domains": ", ".join(merged)})


# --------------------------------------------------------------------------- the dry-run simulator


class Simulator(object):
    """Plausible vendor answers, so a dry run (and the tests) can walk every step with nothing
    sent. Made-up host names end in .invalid, a name that can never exist."""

    def __init__(self, domains: List[Dict[str, Any]], inboxes: Dict[str, List[Dict[str, Any]]]) -> None:
        self.rows = {d["domain"]: d for d in domains}
        self.boxes = {d["domain"]: [i["address"] for i in inboxes.get(d["id"], [])] for d in domains}
        self.inboxing: Dict[str, str] = {}
        self.scaledmail: List[str] = []
        self.connections: List[Dict[str, Any]] = []
        self.pointed: set = set()  # domains whose nameservers were changed at the registrar

    def ns(self, domain: str) -> List[str]:
        row = self.rows.get(domain) or {}
        if row.get("inbox_provider") == "scaledmail":
            return ["ns1.provider-dns.invalid", "ns2.provider-dns.invalid"]
        slug = re.sub(r"[^a-z0-9]", "", domain)[:12]
        return ["ns1-{0}.provider-dns.invalid".format(slug), "ns2-{0}.provider-dns.invalid".format(slug)]

    def respond(self, method: str, url: str, body: Any) -> Any:
        path, _, q = url.partition("?")
        if "porkbun.com" in path:
            return self.porkbun(path.split("/v3", 1)[1], body)
        if "inboxing.com" in path:
            return self.inboxing_api(method, path.split("/api/v2", 1)[1], body)
        if "scaledmail.com" in path:
            return self.scaledmail_api(method, path.split("/api/v1", 1)[1], body)
        if "plusvibe.ai" in path:
            return self.plusvibe(path.split("/api/v1", 1)[1], q)
        if "dns.google" in path:
            return self.dns(q)
        return {"simulated": True}

    def porkbun(self, path: str, body: Any) -> Any:
        domain = path.rsplit("/", 1)[-1]
        if path.startswith("/domain/get/"):
            return 404, {"status": "ERROR", "code": "DOMAIN_NOT_FOUND", "message": "not in the account"}
        if path.startswith("/domain/checkDomain/"):
            price = (self.rows.get(domain) or {}).get("planned_price_usd") or 10
            return {"status": "SUCCESS", "response": {"avail": "yes", "price": "{0:.2f}".format(float(price)),
                                                      "premium": "no", "minDuration": 1}}
        if path.startswith("/account/balance"):
            return {"status": "SUCCESS", "balance": 10 ** 9}
        if path.startswith("/domain/getUrlForwarding/"):
            return {"status": "SUCCESS", "forwards": []}
        if path.startswith("/domain/listAll"):
            return {"status": "SUCCESS", "domains": []}
        if path.startswith("/domain/updateNs/"):
            self.pointed.add(domain)
        return {"status": "SUCCESS", "simulated": True}

    def inboxing_api(self, method: str, path: str, body: Any) -> Any:
        if path == "/domains" and method == "POST":
            d = (body or {}).get("domain", "")
            self.inboxing[d] = "sim-" + d
            return {"id": "sim-" + d, "status": "update_nameservers", "nameservers": self.ns(d)}
        if path == "/slots":
            return {"system": {"can_provision": 99}}
        if path == "/platform-connections":
            if method == "POST":
                conn = {"id": "sim-conn", "platform": (body or {}).get("platform"), "name": (body or {}).get("name")}
                self.connections.append(conn)
                return conn
            return list(self.connections)
        if path.startswith("/domains/"):
            d = path.split("/")[2].replace("sim-", "")
            if path.endswith("/status"):
                return {"status": "active"}
            if path.endswith("/upload"):
                return {"success": True}
            if d in self.inboxing:
                return {"id": "sim-" + d, "status": "active", "nameservers": self.ns(d)}
            return 404, {"error": "not found"}
        return {"simulated": True}

    def scaledmail_api(self, method: str, path: str, body: Any) -> Any:
        if path == "/domains":
            return {"domains": [{"domain": d, "id": "sim-" + d, "status": "Active"} for d in self.scaledmail]}
        if path == "/create-custom-order":
            for item in ((((body or {}).get("providers") or {}).get("google") or {}).get("domains") or []):
                self.scaledmail.append(item["domain"])
            return {"payment_id": "sim-order"}
        if path.startswith("/mailboxes/"):
            d = path.split("/")[2].replace("sim-", "")
            return {"mailboxes": [{"email": a, "status": "Active"} for a in self.boxes.get(d, [])]}
        return {"simulated": True}

    def plusvibe(self, path: str, q: str) -> Any:
        if path == "/authenticate":
            return {"status": "success", "workspaces": [{"_id": "sim-ws-main", "name": "Agency"}]}
        if path == "/workspaces/add":
            return {"status": "success", "_id": "sim-ws-client"}
        if path == "/account/list":
            if "skip=0" not in q:
                return {"accounts": []}
            return {"accounts": [{"_id": "sim-" + a, "email": a} for addrs in self.boxes.values() for a in addrs]}
        return {"status": "success"}

    def dns(self, q: str) -> Any:
        from urllib.parse import parse_qs

        p = parse_qs(q)
        name, rtype = (p.get("name") or [""])[0], (p.get("type") or [""])[0]
        base = name.split("._domainkey.")[-1].replace("_dmarc.", "")
        kind = (self.rows.get(base) or {}).get("inbox_kind", "google")
        if rtype == "NS":
            moved = base in self.pointed or base in self.scaledmail
            data = self.ns(base) if moved else ["curitiba.ns.porkbun.com", "maceio.ns.porkbun.com"]
        elif rtype == "MX":
            data = ["1 smtp.google.com."] if kind == "google" else ["0 mail.protection.outlook.com."]
        elif rtype == "TXT" and name.startswith("_dmarc."):
            data = ["v=DMARC1; p=none"]
        elif rtype == "TXT" and "._domainkey." in name:
            data = ["v=DKIM1; k=rsa; p=SIMULATED"] if name.startswith("google.") and kind == "google" else []
        elif rtype == "CNAME" and name.startswith("selector1._domainkey."):
            data = ["selector1.dkim.invalid."] if kind == "outlook" else []
        elif rtype == "TXT":
            data = ["v=spf1 {0} ~all".format(dns.SPF_INCLUDE.get(kind, ""))]
        else:
            data = []
        return {"Status": 0, "Answer": [{"name": name, "type": dns.TYPES.get(rtype, 0), "data": x} for x in data]}


def today_utc() -> date:
    return datetime.now(timezone.utc).date()
