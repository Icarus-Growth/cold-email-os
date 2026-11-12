"""catch-all-verifier, offline: a fake database, a fake Slack and a fake deep check.

    python3 -m pytest skills/fulfilment/catch-all-verifier -q
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
for _up in HERE.parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
import skill_fakes as fakes  # noqa: E402
import skillkit  # noqa: E402

_spec = importlib.util.spec_from_file_location("cav_run", str(HERE.parents[1] / "scripts/run.py"))
cav = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cav)  # type: ignore[union-attr]

CLIENT = "00000000-0000-4000-8000-00000000c001"
# Made-up domains under the reserved example names.
CATCH, GIVEN, UNREAD = "catch.example.com", "given.example.net", "unread.example.org"
VALID, OTHER = "valid.example.com", "x.example.com"
DELIVERABLE = {"bob@" + CATCH: 97, "carol@" + CATCH: 91, "gil@" + GIVEN: 60}


def fake_deep(calls):
    def check(email):
        calls.append(email)
        if email.endswith("@" + UNREAD):
            return "unknown", 0
        if email in DELIVERABLE:
            return "deliverable", DELIVERABLE[email]
        return "undeliverable", 5
    return check


def cands(first, last, domain):
    return [{"email": "{0}.{1}@{2}".format(first, last, domain), "pattern": "first.last"},
            {"email": "{0}@{1}".format(first, domain), "pattern": "first"},
            {"email": "{0}{1}@{2}".format(first, last, domain), "pattern": "firstlast"},
            {"email": "{0}{1}@{2}".format(first[0], last, domain), "pattern": "flast"},
            {"email": "{0}_{1}@{2}".format(first, last, domain), "pattern": "first_last"}]


def person(i, name, domain, **extra):
    first, last = name.lower().split()
    row = {"id": "p{0}".format(i), "client_id": CLIENT, "full_name": name, "domain": domain,
           "email_status": "catch-all", "catch_all": True, "email_candidates": cands(first, last, domain),
           "created_at": "2026-11-01T00:00:{0:02d}Z".format(i)}
    row.update(extra)
    return row


def make_db():
    return fakes.FakeDB({
        "clients": [{"id": CLIENT, "client_name": "Acme Dental"}],
        "settings": [{"id": "1", "os_url": "https://os.example.com"}],
        "lead_contacts": [
            person(1, "Bob Stone", CATCH),
            person(2, "Carol King", CATCH),
            person(3, "Dan Ray", CATCH),
            person(4, "Eve Lane", UNREAD),
            person(5, "Finn Hale", UNREAD),
            person(6, "Gil Hart", GIVEN, email="gil@" + GIVEN,
                   email_candidates=[{"email": "gil@" + GIVEN, "pattern": "given"}]),
            # Not catch-all: never touched.
            {"id": "p7", "client_id": CLIENT, "full_name": "Hal Moss", "email": "hal@" + VALID,
             "email_status": "valid"},
            {"id": "p8", "client_id": CLIENT, "full_name": "Ivy Rose", "email_status": "unknown",
             "email_candidates": [{"email": "ivy@" + OTHER, "pattern": "first"}]},
        ],
        "tasks": [], "stage_log": [],
    })


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("BOUNCEBAN_API_KEY", "test-key")


def test_live_run_writes_results_with_evidence_and_posts_a_summary():
    db = make_db()
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    calls = []
    out = cav.run(ctx, client="Acme Dental", live=True, check=fake_deep(calls))
    rows = {r["id"]: r for r in db.tables["lead_contacts"]}

    assert rows["p1"]["email"] == "bob@" + CATCH and rows["p1"]["email_status"] == "valid"
    assert rows["p1"]["final_verdict"] == "send" and rows["p1"]["email_score"] == 97
    assert rows["p1"]["email_evidence"] == "Deep check (BounceBan): deliverable, score 97."
    assert rows["p1"]["deep_credits"] == 4  # 2 checks x 2 credits
    # Bob showed the pattern: Carol's 'first' address is checked first.
    assert rows["p2"]["email"] == "carol@" + CATCH and rows["p2"]["deep_credits"] == 2
    # None valid is a real result. The unchecked fifth candidate is never the answer.
    assert rows["p3"]["email_status"] == "none" and not rows["p3"].get("email")
    assert "4 of 5 candidates undeliverable. None valid. 1 were not checked" in rows["p3"]["email_evidence"]
    assert "dan_ray@" + CATCH not in calls
    # A domain the deep check cannot read: one scout, then no more spend.
    assert rows["p4"]["email_status"] == "unknown" and rows["p4"]["deep_credits"] == 2
    assert rows["p5"]["email_status"] == "unknown" and rows["p5"]["deep_credits"] == 0
    assert len([e for e in calls if e.endswith("@" + UNREAD)]) == 1
    assert not rows["p4"].get("email") and not rows["p5"].get("email")
    # A given address that is deliverable with a low score is risky, not valid.
    assert rows["p6"]["email_status"] == "risky" and rows["p6"]["final_verdict"] == "risky"
    # Only catch-all rows were touched.
    assert not rows["p7"].get("deep_checked_at") and not rows["p8"].get("deep_checked_at")
    assert out["credits_used"] == len(calls) * 2

    post = ctx.slack.posts[-1]
    assert post["channel"] == "chan-daily-summary"
    assert "6 contacts deep-checked: 2 valid, 1 risky, 1 none valid" in post["text"]

    again = cav.run(ctx, client="Acme Dental", live=True, check=fake_deep(calls))
    assert "Nothing to do" in again["message"]


def test_big_run_waits_for_a_person_to_approve():
    db = make_db()
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    small = HERE.parent / "small_limit.json"
    calls = []
    with pytest.raises(skillkit.NotApproved, match="above your limit"):
        cav.run(ctx, client="Acme Dental", live=True, check=fake_deep(calls), config_path=str(small))
    assert calls == []
    task = db.tables["tasks"][0]
    assert task["stage"] == "30 - In Review" and "catch-all-verifier" in task["task_name"]
    assert ctx.slack.posts[-1]["channel"] == "chan-review"
    assert not any(r.get("deep_checked_at") for r in db.tables["lead_contacts"])


def test_deep_check_down_leaves_rows_and_reports_once():
    db = make_db()
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())

    def down(email):
        raise cav.VendorError("BounceBan said 402: no credits")

    out = cav.run(ctx, client="Acme Dental", live=True, check=down)
    assert not out["ok"] and out["checked"] == 0
    assert not any(r.get("deep_checked_at") for r in db.tables["lead_contacts"])
    assert len([p for p in ctx.slack.posts if p["channel"] == "chan-pipeline-errors"]) == 1


def test_missing_key_stops_before_anything(monkeypatch):
    monkeypatch.delenv("BOUNCEBAN_API_KEY")
    db = make_db()
    with pytest.raises(skillkit.MissingKey, match="bounceban.com"):
        cav.run(skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig()), client="Acme Dental", live=True,
                check=fake_deep([]))
    assert db.writes == []


def test_own_email_undeliverable_gets_the_same_verdict_word_skip():
    db = make_db()
    db.tables["lead_contacts"] = [person(1, "Gil Hart", GIVEN, email="gone@" + GIVEN,
                                         email_candidates=[{"email": "gone@" + GIVEN, "pattern": "given"}])]
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    cav.run(ctx, client="Acme Dental", live=True, check=fake_deep([]))
    row = db.tables["lead_contacts"][0]
    assert row["email_status"] == "invalid" and row["final_verdict"] == "skip"
