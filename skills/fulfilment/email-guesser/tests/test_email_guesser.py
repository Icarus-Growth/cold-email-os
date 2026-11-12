"""email-guesser, offline: a fake database, a fake Slack and a fake verifier.

    python3 -m pytest skills/fulfilment/email-guesser -q
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

_spec = importlib.util.spec_from_file_location("eg_run", str(HERE.parents[1] / "scripts/run.py"))
eg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eg)  # type: ignore[union-attr]

CLIENT = "00000000-0000-4000-8000-00000000c001"
# Made-up domains under the reserved example names.
ACME, BRIGHT, LONE = "acme-dental.example.com", "brightsmiles.example.org", "lonestar.example.net"
CATCH, NOMAIL = "catchall.example.org", "nomail.example.net"
REAL = {"jane@" + ACME, "sam@" + ACME, "pat.kim@" + BRIGHT,
        "lee.wong@" + BRIGHT, "m.long@" + LONE}


def fake_verifier(calls):
    def check(email):
        calls.append(email)
        if email.endswith("@" + CATCH):
            return "catch_all"
        return "ok" if email in REAL else "invalid"
    return check


def mx(domain):
    return domain != NOMAIL


def person(i, name, **extra):
    row = {"id": "p{0}".format(i), "client_id": CLIENT, "full_name": name,
           "created_at": "2026-11-01T00:00:{0:02d}Z".format(i)}
    row.update(extra)
    return row


def make_db():
    return fakes.FakeDB({
        "clients": [{"id": CLIENT, "client_name": "Acme Dental"}],
        "settings": [{"id": "1", "os_url": "https://os.example.com"}],
        "lead_companies": [{"id": "co1", "client_id": CLIENT, "domain": ACME}],
        "lead_contacts": [
            person(1, "Dr. Jane Doe", company_id="co1"),
            person(2, "Sam Lee", domain=ACME),
            person(3, "Ann Smith", domain=ACME),
            person(4, "Bob Stone", domain=CATCH),
            person(5, "Carol King", domain=CATCH),
            person(6, "Dan Fox", domain=NOMAIL),
            person(7, "Lee Wong", domain=BRIGHT),
            person(8, "Pat Kim", email="pat.kim@" + BRIGHT),
            person(9, "Eve Stray"),
            person(10, "Mia Long", domain=LONE),
            # Already resolved earlier: shows the pattern at this domain.
            {"id": "p0", "client_id": CLIENT, "full_name": "Tom Ray", "domain": LONE,
             "email": "t.ray@" + LONE, "email_status": "valid",
             "guess_checked_at": "2026-10-01T00:00:00Z"},
        ],
        "tasks": [], "stage_log": [],
    })


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("MILLIONVERIFIER_API_KEY", "test-key")


def test_live_run_proves_emails_and_writes_evidence_beside_them():
    db = make_db()
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    calls = []
    out = eg.run(ctx, client="Acme Dental", live=True, check=fake_verifier(calls), mx=mx)
    rows = {r["id"]: r for r in db.tables["lead_contacts"]}

    # The pathfinder finds the pattern; the colleague then costs one check.
    assert rows["p1"]["email"] == "jane@" + ACME and rows["p1"]["email_status"] == "valid"
    assert rows["p1"]["email_pattern"] == "first" and rows["p1"]["final_verdict"] == "send"
    assert rows["p1"]["domain"] == ACME  # taken from the company
    assert rows["p2"]["email"] == "sam@" + ACME and rows["p2"]["guess_credits"] == 1
    assert "proved by a colleague" in rows["p2"]["email_evidence"]
    # None valid is a real result: written as one, with no email.
    assert rows["p3"]["email_status"] == "none" and not rows["p3"].get("email")
    assert "None valid" in rows["p3"]["email_evidence"]
    # Catch-all domain: no answer, ranked candidates saved, one credit for the whole domain.
    assert rows["p4"]["email_status"] == "catch-all" and rows["p4"]["catch_all"] is True
    assert not rows["p4"].get("email")
    assert rows["p4"]["email_candidates"][0] == {"email": "bob.stone@" + CATCH, "pattern": "first.last"}
    assert rows["p4"]["guess_credits"] + rows["p5"]["guess_credits"] == 1
    assert len([e for e in calls if e.endswith("@" + CATCH)]) == 1  # only the test address
    # No mail server: no spend.
    assert rows["p6"]["email_status"] == "none" and rows["p6"]["guess_credits"] == 0
    assert not any(e.endswith("@" + NOMAIL) for e in calls)
    # A given email is checked once, and shows the pattern for the colleague.
    assert rows["p8"]["email_status"] == "valid" and rows["p8"]["email_source"] == "given"
    assert rows["p7"]["email"] == "lee.wong@" + BRIGHT
    # A pattern proved earlier in the database goes first.
    assert rows["p10"]["email"] == "m.long@" + LONE and rows["p10"]["guess_credits"] == 2
    # No domain: skipped, nothing spent.
    assert rows["p9"]["email_status"] == "skipped" and rows["p9"]["guess_credits"] == 0

    # Never an untested guess: every email written was proved, or was given.
    for r in rows.values():
        if r.get("email") and r["id"] != "p0":
            assert r["email_status"] == "valid" and r["email"] in REAL
    assert out["credits_used"] == len(calls)

    post = ctx.slack.posts[-1]
    assert post["channel"] == "chan-daily-summary"
    assert "10 contacts checked: 5 valid, 2 on catch-all domains" in post["text"]

    again = eg.run(ctx, client="Acme Dental", live=True, check=fake_verifier(calls), mx=mx)
    assert "Nothing to do" in again["message"]


def test_dry_run_spends_and_writes_nothing():
    db = make_db()
    calls = []
    out = eg.run(skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig()), client="Acme Dental",
                 check=fake_verifier(calls), mx=mx)
    assert out["dry_run"] and out["credits_at_most"] > 0 and calls == [] and db.writes == []


def test_verifier_down_leaves_rows_for_the_next_run_and_reports_once():
    db = make_db()
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())

    def down(email):
        raise eg.VendorError("MillionVerifier: Insufficient credits")

    out = eg.run(ctx, client="Acme Dental", live=True, check=down, mx=mx)
    assert not out["ok"] and out["errors"]
    rows = {r["id"]: r for r in db.tables["lead_contacts"]}
    assert not rows["p1"].get("guess_checked_at") and not rows["p1"].get("email")
    errors = [p for p in ctx.slack.posts if p["channel"] == "chan-pipeline-errors"]
    assert len(errors) == 1 and "Insufficient credits" in errors[0]["text"]


def test_unknown_client_is_a_plain_error_and_nothing_is_spent():
    db = make_db()
    calls = []
    with pytest.raises(ValueError, match="No client is named"):
        eg.run(skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig()), client="Nobody", live=True,
               check=fake_verifier(calls), mx=mx)
    assert calls == [] and db.writes == []


def test_names_and_patterns():
    assert eg.split_name("Dr. Jane van der Berg Jr.") == ("jane", "vanderberg")
    assert eg.split_name("Renée O'Brien") == ("renee", "obrien")
    assert eg.pattern_of("j.doe@example.com", "Jane Doe") == "f.last"
    assert eg.pattern_of("jane@example.com", "Jane Doe") == "first"
    assert eg.pattern_of("info@example.com", "Jane Doe") == ""
    first = eg.candidates("Jane Doe", "example.com", ["flast"], 3)
    assert [c["email"] for c in first] == ["jdoe@example.com", "jane.doe@example.com", "jane@example.com"]


def test_own_email_that_fails_the_check_gets_the_verdict_skip():
    db = make_db()
    db.tables["lead_contacts"] = [person(1, "Ann Smith", email="ann@" + ACME)]
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    eg.run(ctx, client="Acme Dental", live=True, check=fake_verifier([]), mx=mx)
    row = db.tables["lead_contacts"][0]
    assert row["email_status"] == "invalid" and row["final_verdict"] == "skip"
