"""google-maps-scraper, offline: a fake database, a fake Slack and a fake Serper.

    python3 -m pytest skills/fulfilment/google-maps-scraper -q
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

_spec = importlib.util.spec_from_file_location("gms_run", str(HERE.parents[1] / "scripts/run.py"))
gms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gms)  # type: ignore[union-attr]

CLIENT = "00000000-0000-4000-8000-00000000c001"
PERSON = "00000000-0000-4000-8000-00000000a001"


def make_db(searches=None):
    return fakes.FakeDB({
        "clients": [{"id": CLIENT, "client_name": "Acme Dental"}],
        "settings": [{"id": "1", "os_url": "os.example.com"}],
        "lead_searches": searches if searches is not None else [
            {"id": "s1", "client_id": CLIENT, "keyword": "dentist", "location": "Austin, TX",
             "segment": "Dental | Austin, TX", "industry": "Dental", "status": "to do", "attempts": 0,
             "credits_used": 0, "created_at": "2026-11-01T00:00:00Z"},
            {"id": "s2", "client_id": CLIENT, "keyword": "dentist", "location": "Dallas, TX",
             "segment": "Dental | Dallas, TX", "industry": "Dental", "status": "to do", "attempts": 0,
             "credits_used": 0, "created_at": "2026-11-01T00:00:01Z"},
        ],
        "lead_companies": [],
        "tasks": [],
        "stage_log": [],
    })


PLACES = {
    "dentist in Austin, TX": [
        {"title": "Acme Dental Austin", "website": "https://www.acme-dental.example.com/", "placeId": "P1",
         "phoneNumber": "+1 555 0100", "address": "1 Main St, Austin, TX", "category": "Dentist",
         "rating": 4.8, "ratingCount": 120},
        {"title": "Bright Smiles", "website": "http://brightsmiles.example.org", "placeId": "P2"},
        {"title": "No Site Dental", "placeId": "P3"},
    ],
    "dentist in Dallas, TX": [
        {"title": "Bright Smiles Dallas", "website": "https://brightsmiles.example.org/dallas", "placeId": "P4"},
        {"title": "Acme Dental Austin", "website": "https://acme-dental.example.com", "placeId": "P1"},
        {"title": "Lone Star Dental", "website": "https://lonestar.example.net", "placeId": "P5"},
    ],
}


def fake_fetch(calls):
    def fetch(query, page, country, key):
        calls.append(query)
        return PLACES.get(query, [])
    return fetch


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")


def ctx_for(db):
    return skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())


def test_live_run_saves_new_businesses_once_and_marks_searches_done():
    db = make_db()
    ctx = ctx_for(db)
    calls = []
    out = gms.run(ctx, client="Acme Dental", live=True, fetch=fake_fetch(calls))
    assert out["ok"] and out["searches_run"] == 2 and out["credits_used"] == 2
    companies = db.tables["lead_companies"]
    # P1 twice (same place id), brightsmiles twice (same domain), P3 has no website: 3 saved.
    assert sorted(c["domain"] for c in companies) == ["acme-dental.example.com", "brightsmiles.example.org",
                                                      "lonestar.example.net"]
    assert all(c["client_id"] == CLIENT and c["segment"] for c in companies)
    assert {s["status"] for s in db.tables["lead_searches"]} == {"done"}
    assert [s["new_count"] for s in db.tables["lead_searches"]] == [2, 1]
    post = ctx.slack.posts[-1]
    assert post["channel"] == "chan-daily-summary"
    assert "3 new saved" in post["text"] and "2 credits used" in post["text"]

    # Run again: nothing is left to do, nothing is spent.
    again = gms.run(ctx, client="Acme Dental", live=True, fetch=fake_fetch(calls))
    assert "Nothing to do" in again["message"] and len(calls) == 2


def test_dry_run_spends_and_writes_nothing():
    db = make_db()
    calls = []
    out = gms.run(ctx_for(db), client="Acme Dental", fetch=fake_fetch(calls))
    assert out["dry_run"] and out["credits_needed"] == 2 and calls == []
    assert db.writes == []


def test_crash_resumes_at_the_next_search_not_done():
    db = make_db()
    ctx = ctx_for(db)

    def broken(query, page, country, key):
        if "Dallas" in query:
            raise KeyboardInterrupt  # the process dies mid-run
        return PLACES[query]

    with pytest.raises(KeyboardInterrupt):
        gms.run(ctx, client="Acme Dental", live=True, fetch=broken)
    assert [s["status"] for s in db.tables["lead_searches"]] == ["done", "to do"]
    calls = []
    gms.run(ctx, client="Acme Dental", live=True, fetch=fake_fetch(calls))
    assert calls == ["dentist in Dallas, TX"]


def test_a_failed_search_is_tried_once_more_then_skipped():
    db = make_db()

    def down(query, page, country, key):
        raise gms.VendorError("Serper said 500")

    out = gms.run(ctx_for(db), client="Acme Dental", live=True, fetch=down)
    assert out["failed"] == 4  # each search: first try and one retry
    assert all(s["status"] == "failed" and s["attempts"] == 2 for s in db.tables["lead_searches"])
    assert db.tables["lead_companies"] == []


def test_big_run_asks_for_approval_then_runs_after_a_person_approves():
    searches = [{"id": "s{0}".format(i), "client_id": CLIENT, "keyword": "dentist", "location": "Town {0}".format(i),
                 "status": "to do", "attempts": 0, "credits_used": 0, "created_at": "2026-11-01T00:00:{0:02d}Z".format(i)}
                for i in range(6)]
    db = make_db(searches)
    ctx = ctx_for(db)
    cfg = Path(__file__).resolve().parent / "small_limit.json"
    calls = []
    with pytest.raises(skillkit.NotApproved):
        gms.run(ctx, client="Acme Dental", live=True, fetch=fake_fetch(calls), config_path=str(cfg))
    assert calls == []
    task = db.tables["tasks"][0]
    assert task["stage"] == "30 - In Review" and "up to 6 credits" in task["task_name"]
    ask = ctx.slack.posts[-1]
    assert ask["channel"] == "chan-review" and "up to 6 credits" in ask["text"]
    assert ask["blocks"][1]["elements"][0]["url"] == "https://os.example.com/board/tasks/" + task["id"]

    # Asked again before anyone approves: it waits, no second card.
    with pytest.raises(skillkit.NotApproved):
        gms.run(ctx, client="Acme Dental", live=True, fetch=fake_fetch(calls), config_path=str(cfg))
    assert len(db.tables["tasks"]) == 1 and calls == []

    db.tables["stage_log"].append({"board": "tasks", "record_id": task["id"], "from_stage": "30 - In Review",
                                   "to_stage": "100 - Complete", "changed_by_id": PERSON,
                                   "changed_at": "2026-11-01T00:00:00Z"})
    out = gms.run(ctx, client="Acme Dental", live=True, fetch=fake_fetch(calls), config_path=str(cfg))
    assert out["searches_run"] == 6 and out["credits_used"] == 6


def test_unknown_client_is_a_plain_error_and_nothing_happens():
    db = make_db()
    calls = []
    with pytest.raises(ValueError, match="No client is named"):
        gms.run(ctx_for(db), client="Nobody Ltd", live=True, fetch=fake_fetch(calls))
    assert db.writes == [] and calls == []


def test_missing_key_stops_with_where_to_get_it(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY")
    db = make_db()
    with pytest.raises(skillkit.MissingKey, match="serper.dev"):
        gms.run(ctx_for(db), client="Acme Dental", live=True, fetch=fake_fetch([]))
    assert db.writes == []


def test_add_plans_searches_without_duplicates():
    db = make_db([])
    ctx = ctx_for(db)
    out = gms.run(ctx, client="Acme Dental", add=["dentist"], places=["Austin, TX"], live=False)
    assert out["would_add_searches"] == 1 and db.writes == []
    calls = []
    gms.run(ctx, client="Acme Dental", add=["dentist", "dentist"], places=["Austin, TX"], live=True,
            fetch=fake_fetch(calls))
    assert len(db.tables["lead_searches"]) == 1 and calls == ["dentist in Austin, TX"]
