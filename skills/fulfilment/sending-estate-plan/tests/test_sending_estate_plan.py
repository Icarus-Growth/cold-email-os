"""Tests for sending-estate-plan: fake example data, no network."""

import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve()
for _up in HERE.parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
for _skill in ("sending-domain-names", "sending-estate-plan"):
    sys.path.insert(0, str(HERE.parents[2] / _skill / "scripts"))

import pytest  # noqa: E402
import skillkit  # noqa: E402
from skill_fakes import FakeConfig, FakeDB, FakeSlack  # noqa: E402

import plan_estate  # noqa: E402
import sending_math as math  # noqa: E402
import sending_naming as naming  # noqa: E402
from sending_registrars import Registrar  # noqa: E402

TODAY = date(2026, 11, 11)


class FakeRegistrar(Registrar):
    name = "porkbun"

    def __init__(self):
        self.asked = []

    def check_many(self, names):
        self.asked += names
        return {n: naming.Availability(True, 11.0) for n in names}

    def owned(self):
        return set()


def make_ctx(volume=21000, **client_extra):
    client = dict({"id": "c1", "client_name": "Acme Dental", "website": "acmedental.com", "contact_name": "Jane Doe"},
                  **client_extra)
    if volume is not None:
        client["monthly_send_volume"] = volume
    db = FakeDB({
        "settings": [{"id": 1, "os_url": "os.example.com"}],
        "clients": [client],
        "onboarding_forms": [{"id": "f1", "client_id": "c1", "submitted_at": "2026-11-01",
                              "answers": {"sender_names": {"value": "Jane Doe, CEO and Sam Lee, Head of Sales"}}}],
        "sending_domains": [], "sending_inboxes": [], "inbox_batches": [],
    })
    return skillkit.Context(db, FakeSlack(), FakeConfig(), {})


def test_the_sum_from_a_volume():
    cfg = math.load_config()
    c = math.estate_counts(21000, cfg)
    # 21,000 / 21 days = 1,000 a day: 600 on Google, 400 on Outlook.
    g, o = c["kinds"]["google"], c["kinds"]["outlook"]
    assert (c["daily_volume"], g["daily_volume"], o["daily_volume"]) == (1000, 600, 400)
    # Google: 600 / 20 = 30 inboxes, +10% = 33, 2 a domain = 17 domains = 34 inboxes.
    assert (g["inboxes_needed"], g["inboxes_with_spare"], g["domains"], g["inboxes"]) == (30, 33, 17, 34)
    # Outlook: 400 / 5 = 80 inboxes, +10% = 88, 49 a domain = 2 domains = 98 inboxes.
    assert (o["inboxes_needed"], o["inboxes_with_spare"], o["domains"], o["inboxes"]) == (80, 88, 2, 98)
    assert (c["total_domains"], c["total_inboxes"]) == (19, 132)
    assert c["monthly_capacity"] >= 21000
    assert [math.warmup_on_day("google", d, cfg) for d in (0, 1, 9, 13, 14)] == [5, 10, 50, 50, 30]
    assert math.warmup_on_day("outlook", 20, cfg) == 2


def test_senders_and_inbox_names():
    who = math.parse_senders("Jane Doe, CEO and Sam Lee, Head of Sales")
    assert who == [{"first_name": "Jane", "last_name": "Doe"}, {"first_name": "Sam", "last_name": "Lee"}]
    assert math.parse_senders("no preference", "Sam Taylor") == [{"first_name": "Sam", "last_name": "Taylor"}]
    names = [n["local"] for n in math.inbox_names(who, 49)]
    assert len(names) == 49 and len(set(names)) == 49
    assert names[:4] == ["jane", "sam", "jane.doe", "sam.lee"]


def test_plan_writes_cards_rows_and_asks_for_approval():
    ctx = make_ctx()
    reg = FakeRegistrar()
    plan = plan_estate.make_plan(ctx, "Acme Dental", today=TODAY, registrar=reg)
    db = ctx.db

    cards = sorted(db.tables["inbox_batches"], key=lambda c: c["inbox_provider"])
    assert [(c["inbox_provider"], c["domain_count"], c["inbox_count"], c["stage"], c["domain_registrar"])
            for c in cards] == [("inboxing", 2, 98, "10 - Approval Needed", "porkbun"),
                                ("scaledmail", 17, 34, "10 - Approval Needed", "porkbun")]
    assert all(c["client_id"] == "c1" and c["due_date"] == "2026-11-28" for c in cards)
    assert "21,000 emails" in cards[0]["notes"] and "$" not in cards[0]["notes"]

    domains = db.tables["sending_domains"]
    assert len(domains) == 19 and len({d["domain"] for d in domains}) == 19
    assert all(d["status"] == "planned" and d["planned_price_usd"] == 11.0 for d in domains)
    assert "acmedental.com" not in {d["domain"] for d in domains}
    assert all(d["forward_to"] == "https://acmedental.com" for d in domains)
    assert all(d["warm_days"] == 14 for d in domains)

    inboxes = db.tables["sending_inboxes"]
    assert len(inboxes) == 132 and len({i["address"] for i in inboxes}) == 132
    per_domain = {}
    for i in inboxes:
        per_domain[i["domain_id"]] = per_domain.get(i["domain_id"], 0) + 1
    assert sorted(set(per_domain.values())) == [2, 49]

    posts = ctx.slack.posts
    assert len(posts) == 2 and all(p["channel"] == "chan-review" for p in posts)
    google = next(p for p in posts if "scaledmail" in p["text"])
    assert "17 domains at porkbun, and 34 Google inboxes at scaledmail" in google["text"]
    assert "187.00 USD now for the domains" in google["text"]  # 17 x 11.00
    assert "119.00 USD a month for the inboxes" in google["text"]  # 34 x 3.50
    assert "Nothing is bought before that" in google["text"]
    assert google["blocks"][1]["elements"][0]["url"].startswith("https://os.example.com/board/inbox_batches/")
    assert plan["counts"]["total_inboxes"] == 132


def test_a_second_run_fills_only_what_is_missing():
    ctx = make_ctx()
    plan_estate.make_plan(ctx, "Acme Dental", today=TODAY, registrar=FakeRegistrar())
    before = {k: len(v) for k, v in ctx.db.tables.items()}
    reg = FakeRegistrar()
    plan_estate.make_plan(ctx, "Acme Dental", today=TODAY, registrar=reg)
    after = {k: len(v) for k, v in ctx.db.tables.items()}
    assert before == after
    assert reg.asked == []  # nothing missing, so no new names were checked


def test_enterprise_warms_longer_and_the_rows_say_so():
    ctx = make_ctx()
    plan_estate.make_plan(ctx, "Acme Dental", enterprise=True, today=TODAY, registrar=FakeRegistrar())
    assert all(d["warm_days"] == 21 for d in ctx.db.tables["sending_domains"])
    assert all(c["due_date"] == "2026-12-05" for c in ctx.db.tables["inbox_batches"])  # 7 days later


def test_preview_writes_nothing():
    ctx = make_ctx()
    plan = plan_estate.make_plan(ctx, "Acme Dental", preview=True, today=TODAY, registrar=FakeRegistrar())
    assert ctx.db.writes == [] and ctx.slack.posts == []
    assert sum(len(c["domains"]) for c in plan["cards"]) == 19


def test_volume_flag_wins_over_the_client_row():
    ctx = make_ctx(volume=None)
    plan = plan_estate.make_plan(ctx, "Acme Dental", volume="2,000", preview=True, today=TODAY,
                                 registrar=FakeRegistrar())
    assert plan["counts"]["monthly_volume"] == 2000


def test_no_volume_stops_plainly_and_writes_nothing():
    ctx = make_ctx(volume=None)
    reg = FakeRegistrar()
    with pytest.raises(math.PlanError) as e:
        plan_estate.make_plan(ctx, "Acme Dental", today=TODAY, registrar=reg)
    assert "has no monthly send volume" in str(e.value) and "--volume" in str(e.value)
    assert ctx.db.writes == [] and ctx.slack.posts == [] and reg.asked == []


def test_bad_volume_stops_plainly():
    with pytest.raises(math.PlanError):
        math.estate_counts("lots", math.load_config())
    with pytest.raises(math.PlanError):
        math.estate_counts(0, math.load_config())


def test_an_archived_client_or_card_is_left_alone():
    # An archived client: stops plainly, writes and asks nothing.
    ctx = make_ctx(archived_at="2026-11-10T00:00:00Z")
    reg = FakeRegistrar()
    with pytest.raises(naming.NamingError) as e:
        plan_estate.make_plan(ctx, "Acme Dental", today=TODAY, registrar=reg)
    assert "No client named" in str(e.value)
    assert ctx.db.writes == [] and ctx.slack.posts == [] and reg.asked == []
    # By row id: the same client, archived, is refused with a plain reason.
    uid = "00000000-0000-4000-8000-0000000000c1"
    ctx.db.tables["clients"][0]["id"] = uid
    with pytest.raises(naming.NamingError) as e:
        plan_estate.make_plan(ctx, uid, today=TODAY, registrar=reg)
    assert "is archived" in str(e.value)
    assert ctx.db.writes == [] and ctx.slack.posts == [] and reg.asked == []
    # An archived card in Approval Needed is never filled up: a new card is made instead.
    ctx = make_ctx()
    ctx.db.tables["inbox_batches"].append({"id": "old", "client_id": "c1", "stage": "10 - Approval Needed",
                                           "inbox_provider": "scaledmail", "archived_at": "2026-11-01T00:00:00Z"})
    plan_estate.make_plan(ctx, "Acme Dental", today=TODAY, registrar=FakeRegistrar())
    assert not [d for d in ctx.db.tables["sending_domains"] if d["batch_id"] == "old"]
