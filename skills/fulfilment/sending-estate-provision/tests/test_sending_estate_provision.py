"""Tests for sending-estate-provision: fake example data, no network. The vendor side is the
dry-run simulator behind a recording transport, so every call is counted and none is sent."""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
for _up in HERE.parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
for _skill in ("sending-domain-names", "sending-estate-plan", "sending-estate-provision"):
    sys.path.insert(0, str(HERE.parents[2] / _skill / "scripts"))

import pytest  # noqa: E402
import skillkit  # noqa: E402
from skill_fakes import FakeConfig, FakeDB, FakeSlack  # noqa: E402

import plan_estate  # noqa: E402
import sending_engine as engine  # noqa: E402
import sending_http as http  # noqa: E402
import sending_naming as naming  # noqa: E402
from sending_registrars import Registrar  # noqa: E402

START = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
KEYS = ["PORKBUN_API_KEY", "PORKBUN_SECRET_KEY", "INBOXING_API_KEY", "SCALEDMAIL_API_KEY",
        "SCALEDMAIL_ORGANIZATION_ID", "REGISTRAR_WEB_USERNAME", "REGISTRAR_WEB_PASSWORD", "PLUSVIBE_API_KEY",
        "PLUSVIBE_LOGIN_EMAIL", "PLUSVIBE_LOGIN_PASSWORD"]


class FakeRegistrar(Registrar):
    name = "porkbun"

    def check_many(self, names):
        return {n: naming.Availability(True, 11.0) for n in names}

    def owned(self):
        return set()


class NoNetwork(object):
    """The transport when nothing may be sent: any call fails the test."""

    def __init__(self):
        self.calls = 0

    def request(self, *a, **k):
        self.calls += 1
        raise AssertionError("a vendor call was made")


@pytest.fixture
def planned():
    """A planned client: 2,000 emails a month = 2 Google domains (4 inboxes) + 1 Outlook domain (49)."""
    db = FakeDB({"settings": [{"id": 1, "os_url": "os.example.com"}],
                 "clients": [{"id": "c1", "client_name": "Acme Dental", "website": "acmedental.com",
                              "contact_name": "Jane Doe", "monthly_send_volume": 2000, "sending_domains": ""}],
                 "onboarding_forms": [], "sending_domains": [], "sending_inboxes": [], "inbox_batches": [],
                 "stage_log": []})
    ctx = skillkit.Context(db, FakeSlack(), FakeConfig(), {})
    plan_estate.make_plan(ctx, "Acme Dental", today=date(2026, 11, 11), registrar=FakeRegistrar())
    ctx.slack.posts.clear()
    cards = {c["inbox_provider"]: c for c in db.tables["inbox_batches"]}
    return ctx, cards


def approve(ctx, card, by="person-1"):
    ctx.db.tables["stage_log"].append({"id": len(ctx.db.tables["stage_log"]) + 1, "board": "inbox_batches",
                                       "record_id": card["id"], "from_stage": "10 - Approval Needed",
                                       "to_stage": "20 - Buying Domains", "changed_by_id": by,
                                       "changed_at": "2026-11-12T08:00:00+00:00"})
    ctx.db.update("inbox_batches", card["id"], {"stage": "20 - Buying Domains"})


def rows(ctx, table, card):
    return [r for r in ctx.db.tables[table] if r["batch_id"] == card["id"]]


def test_plan_gives_the_expected_cards(planned):
    ctx, cards = planned
    assert (cards["scaledmail"]["domain_count"], cards["scaledmail"]["inbox_count"]) == (2, 4)
    assert (cards["inboxing"]["domain_count"], cards["inboxing"]["inbox_count"]) == (1, 49)


def test_no_approval_refuses_and_writes_and_spends_nothing(planned):
    ctx, cards = planned
    card = cards["scaledmail"]
    net = NoNetwork()
    old = http.set_transport(net)
    writes = len(ctx.db.writes)
    try:
        with pytest.raises(skillkit.NotApproved):
            engine.provision(ctx, card["id"], live=True)
        with pytest.raises(skillkit.NotApproved):
            engine.provision(ctx, card["id"], live=False)
        # A move made by an automation (no person on the stage log row) is not an approval.
        approve(ctx, card, by=None)
        writes = len(ctx.db.writes)
        with pytest.raises(skillkit.NotApproved):
            engine.provision(ctx, card["id"], live=True)
    finally:
        http.set_transport(old)
    assert net.calls == 0 and len(ctx.db.writes) == writes and ctx.slack.posts == []
    assert all(r["status"] == "planned" and not r.get("last_note") for r in rows(ctx, "sending_domains", card))


def test_dry_run_with_approval_writes_the_would_do_notes_and_sends_nothing(planned, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    ctx, cards = planned
    card = cards["scaledmail"]
    approve(ctx, card)
    net = NoNetwork()
    old = http.set_transport(net)
    try:
        out = engine.provision(ctx, card["id"], live=False, now=lambda: START)
    finally:
        restored = http.set_transport(old)
    assert restored is net and net.calls == 0  # the dry run used its own recorder, then put ours back
    assert out["vendor_calls"] > 0 and all(r["state"] == "done" for r in out["domains"])
    assert set(out["missing_keys"]) >= {"PORKBUN_API_KEY", "SCALEDMAIL_API_KEY"}  # the go-live checklist
    domains = rows(ctx, "sending_domains", card)
    assert len(domains) == 2
    for d in domains:
        assert d["status"] == "planned"  # a dry run is never progress
        assert d["last_note"].startswith("Dry run: would buy {0} for 11.00 USD (approved 11.00 USD)".format(d["domain"]))
        assert "would order 2 Google inboxes at scaledmail" in d["last_note"]
        assert "SPF, DKIM, DMARC and MX all pass" in d["last_note"]
        assert "warm-up on for 2 inboxes in plusvibe" in d["last_note"]
        assert d["checked_at"] == START.isoformat()
    assert all(i["status"] == "planned" for i in rows(ctx, "sending_inboxes", card))
    assert ctx.db.get("inbox_batches", card["id"])["stage"] == "20 - Buying Domains"
    assert ctx.slack.posts == []


def live_vendor(ctx, card):
    domains = rows(ctx, "sending_domains", card)
    inboxes = {}
    for i in rows(ctx, "sending_inboxes", card):
        inboxes.setdefault(i["domain_id"], []).append(i)
    sim = engine.Simulator(domains, inboxes)
    return sim, http.RecordingTransport(sim.respond)


def buys(transport):
    return [c for c in transport.calls if "/domain/create/" in c["url"]]


def test_live_run_moves_the_card_and_picks_up_where_it_stopped(planned, monkeypatch):
    ctx, cards = planned
    for k in KEYS:
        monkeypatch.setenv(k, "test-value")
    card = cards["inboxing"]
    approve(ctx, card)
    sim, vendor = live_vendor(ctx, card)
    old = http.set_transport(vendor)
    try:
        # Run 1: buys, orders 49 inboxes, points the nameservers, then waits for them to spread.
        out = engine.provision(ctx, card["id"], live=True, now=lambda: START)
        d = rows(ctx, "sending_domains", card)[0]
        assert (d["status"], d["paid_price_usd"]) == ("ordered", 11.0)
        assert "spread" in d["waiting_for"] and d["nameservers"]
        assert len(buys(vendor)) == 1
        order = next(c for c in vendor.calls if c["url"].endswith("/api/v2/domains") and c["method"] == "POST")
        assert order["body"]["user_count"] == 49 and len(order["body"]["names"]) == 49
        assert order["body"]["redirect_url"] == "https://acmedental.com"
        assert ctx.db.get("inbox_batches", card["id"])["stage"] == "30 - Setting Up Inboxes"
        assert d["domain"] in ctx.db.get("clients", "c1")["sending_domains"]
        assert out["stage"] == "30 - Setting Up Inboxes"

        # Run 2, too early: the next check is not due, so nothing is asked.
        n = len(vendor.calls)
        engine.provision(ctx, card["id"], live=True, now=lambda: START + timedelta(minutes=5))
        assert len(vendor.calls) == n

        # Run 3, later: nameservers moved, inboxes active, auth passes, warm-up on. Never bought twice.
        later = START + timedelta(hours=6)
        engine.provision(ctx, card["id"], live=True, now=lambda: later)
        d = rows(ctx, "sending_domains", card)[0]
        assert d["status"] == "warming" and "warming for 14 days" in d["waiting_for"]
        assert len(buys(vendor)) == 1
        boxes = rows(ctx, "sending_inboxes", card)
        assert all(i["status"] == "warming" and i["warmup_daily_limit"] == 2 and i["warmup_account_id"] for i in boxes)
        batch = ctx.db.get("inbox_batches", card["id"])
        assert batch["stage"] == "40 - Warming" and batch["warmup_started_on"] == "2026-11-12"

        # Run 4, after 14 days: ready to send.
        done = START + timedelta(days=15)
        engine.provision(ctx, card["id"], live=True, now=lambda: done)
    finally:
        http.set_transport(old)
    batch = ctx.db.get("inbox_batches", card["id"])
    assert batch["stage"] == "100 - Ready To Send" and batch["ready_on"] == "2026-11-27"
    assert all(i["status"] == "ready" for i in rows(ctx, "sending_inboxes", card))
    posts = [p for p in ctx.slack.posts if p["channel"] == "chan-task-updates"]
    assert [p["text"].split("moved to ")[1].split(".*")[0] for p in posts] == [
        "30 - Setting Up Inboxes", "40 - Warming", "100 - Ready To Send"]
    assert "ready to send" in posts[-1]["text"]


def test_google_warmup_steps_down_after_14_days(planned, monkeypatch):
    ctx, cards = planned
    for k in KEYS:
        monkeypatch.setenv(k, "test-value")
    card = cards["scaledmail"]
    approve(ctx, card)
    sim, vendor = live_vendor(ctx, card)
    old = http.set_transport(vendor)
    try:
        engine.provision(ctx, card["id"], live=True, now=lambda: START)
        orders = [c for c in vendor.calls if "create-custom-order" in c["url"]]
        assert len(orders) == 1 and len(orders[0]["body"]["providers"]["google"]["domains"]) == 2  # one order
        assert orders[0]["body"]["hosting"]["password"] == "***"  # logins never reach a log
        assert all(i["warmup_daily_limit"] == 50 for i in rows(ctx, "sending_inboxes", card))
        engine.provision(ctx, card["id"], live=True, now=lambda: START + timedelta(days=14, hours=1))
    finally:
        http.set_transport(old)
    assert all(i["warmup_daily_limit"] == 30 and i["status"] == "ready" for i in rows(ctx, "sending_inboxes", card))


def test_a_price_above_the_approved_price_is_not_bought(planned, monkeypatch):
    ctx, cards = planned
    for k in KEYS:
        monkeypatch.setenv(k, "test-value")
    card = cards["scaledmail"]
    approve(ctx, card)
    sim, vendor = live_vendor(ctx, card)
    dear = rows(ctx, "sending_domains", card)[0]["domain"]
    sim.rows[dear] = dict(sim.rows[dear], planned_price_usd=14.0)  # the registrar now asks 14.00
    old = http.set_transport(vendor)
    try:
        out = engine.provision(ctx, card["id"], live=True, now=lambda: START)
    finally:
        http.set_transport(old)
    assert [c["url"].rsplit("/", 1)[1] for c in buys(vendor)] != [dear]
    assert dear not in [c["url"].rsplit("/", 1)[1] for c in buys(vendor)]
    row = next(r for r in rows(ctx, "sending_domains", card) if r["domain"] == dear)
    assert row["status"] == "planned" and "approved price is 11.00 USD" in row["last_error"]
    assert not out["ok"]
    errors = [p for p in ctx.slack.posts if p["channel"] == "chan-pipeline-errors"]
    assert len(errors) == 1 and dear in errors[0]["text"]


def test_more_rows_than_approved_refuses_before_any_call(planned, monkeypatch):
    ctx, cards = planned
    card = cards["scaledmail"]
    approve(ctx, card)
    ctx.db.insert("sending_domains", {"batch_id": card["id"], "client_id": "c1", "domain": "extraname.com",
                                      "status": "planned", "planned_price_usd": 11.0, "inbox_kind": "google",
                                      "inboxes_planned": 2})
    net = NoNetwork()
    old = http.set_transport(net)
    writes = len(ctx.db.writes)
    try:
        with pytest.raises(engine.SpendGuard) as e:
            engine.provision(ctx, card["id"], live=True)
    finally:
        http.set_transport(old)
    assert "approves 2 domains but has 3" in str(e.value)
    assert net.calls == 0 and len(ctx.db.writes) == writes


def test_daily_job_carries_on_but_never_buys(planned, monkeypatch):
    import daily

    ctx, cards = planned
    for k in KEYS:
        monkeypatch.setenv(k, "test-value")
    card = cards["scaledmail"]
    approve(ctx, card)
    sim, vendor = live_vendor(ctx, card)
    old = http.set_transport(vendor)
    try:
        out = daily.run(ctx.db, ctx.slack, ctx.config, {}, date(2026, 11, 12))
    finally:
        http.set_transport(old)
    assert out["ok"] and out["cards"] == 1
    assert buys(vendor) == []
    assert all(r["status"] == "planned" and "--live" in r["waiting_for"] for r in rows(ctx, "sending_domains", card))


def test_daily_job_skips_archived_cards_and_archived_clients(planned, monkeypatch):
    import daily

    ctx, cards = planned
    for k in KEYS:
        monkeypatch.setenv(k, "test-value")
    for card in cards.values():
        approve(ctx, card)
    old = http.set_transport(NoNetwork())
    try:
        ctx.db.update("inbox_batches", cards["scaledmail"]["id"], {"archived_at": "2026-11-12T00:00:00Z"})
        ctx.db.update("clients", "c1", {"archived_at": "2026-11-12T00:00:00Z"})
        out = daily.run(ctx.db, ctx.slack, ctx.config, {}, date(2026, 11, 12))
    finally:
        http.set_transport(old)
    assert out["ok"] and out["cards"] == 0
    assert out["skipped"] == [cards["inboxing"]["batch_name"]]  # the archived card is not even read
    assert ctx.slack.posts == []
