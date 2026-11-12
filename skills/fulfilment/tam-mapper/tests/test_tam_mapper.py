"""tam-mapper, offline: a fake database and a fake Slack.

    python3 -m pytest skills/fulfilment/tam-mapper -q
"""

from __future__ import annotations

import importlib.util
import json
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

_spec = importlib.util.spec_from_file_location("tam_run", str(HERE.parents[1] / "scripts/run.py"))
tam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tam)  # type: ignore[union-attr]

CLIENT = "00000000-0000-4000-8000-00000000c001"
ICP = {
    "industries": [{"name": "Dental", "keywords": ["dentist", "dental clinic"]}, "orthodontist"],
    "locations": ["Austin, TX", "Dallas, TX"],
    "sizes": ["1-10"],
    "fit_rule": "An independent dental practice.",
}


def make_db(**tables):
    base = {"clients": [{"id": CLIENT, "client_name": "Acme Dental"}],
            "settings": [{"id": "1", "os_url": "https://os.example.com"}],
            "lead_searches": [], "lead_companies": [], "lead_contacts": []}
    base.update(tables)
    return fakes.FakeDB(base)


def ctx_for(db):
    return skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())


def test_plan_writes_the_grid_once_and_posts_the_estimate():
    db = make_db()
    ctx = ctx_for(db)
    out = tam.run(ctx, client="Acme Dental", icp=ICP)
    rows = db.tables["lead_searches"]
    # 3 keywords x 2 places
    assert out["searches_added"] == 6 and len(rows) == 6
    assert {r["segment"] for r in rows} == {"Dental | Austin, TX", "Dental | Dallas, TX",
                                             "orthodontist | Austin, TX", "orthodontist | Dallas, TX"}
    assert all(r["status"] == "to do" and r["client_id"] == CLIENT for r in rows)
    assert out["estimate"]["searches_to_do"] == 6 and out["estimate"]["credits_to_finish"] == 6
    post = ctx.slack.posts[-1]
    assert post["channel"] == "chan-daily-summary" and "6 new searches added" in post["text"]
    assert post["blocks"][1]["elements"][0]["url"] == "https://os.example.com/clients/" + CLIENT

    # Same plan again: nothing new, nothing posted.
    again = tam.run(ctx, client="Acme Dental", icp=ICP)
    assert again["searches_added"] == 0 and len(db.tables["lead_searches"]) == 6
    assert len(ctx.slack.posts) == 1


def test_report_counts_per_segment_and_estimates_from_real_results():
    db = make_db(
        lead_searches=[
            {"id": "s1", "client_id": CLIENT, "keyword": "dentist", "location": "Austin, TX",
             "segment": "Dental | Austin, TX", "status": "done", "new_count": 10},
            {"id": "s2", "client_id": CLIENT, "keyword": "dentist", "location": "Dallas, TX",
             "segment": "Dental | Dallas, TX", "status": "to do"},
        ],
        lead_companies=[
            {"id": "c1", "client_id": CLIENT, "segment": "Dental | Austin, TX", "fit_status": "fit", "size_band": "1-10"},
            {"id": "c2", "client_id": CLIENT, "segment": "Dental | Austin, TX", "fit_status": "not fit"},
            {"id": "c3", "client_id": CLIENT, "segment": "Dental | Austin, TX"},
        ],
        lead_contacts=[{"id": "p1", "client_id": CLIENT, "company_id": "c1", "final_verdict": "send"}],
    )
    out = tam.run(ctx_for(db), client="Acme Dental", report_only=True)
    seg = out["report"]["segments"]["Dental | Austin, TX"]
    assert seg == {"searches": 1, "searches_done": 1, "companies": 3, "fit": 1, "not_fit": 1, "unsure": 0,
                   "not_checked": 1, "contacts": 1, "emails_to_send": 1}
    est = out["estimate"]
    assert est["new_businesses_per_search"] == 10.0 and est["businesses_estimated"] == 13
    assert est["fit_rate"] == 0.5 and est["fits_estimated"] == 6
    assert out["report"]["by_size"] == {"1-10": 1, "unknown": 2}
    assert db.writes == []


def test_dry_run_writes_nothing():
    db = make_db()
    out = tam.run(ctx_for(db), client="Acme Dental", icp=ICP, dry_run=True)
    assert out["searches_added"] == 6 and out["estimate"]["searches_to_do"] == 6
    assert db.writes == []


def test_bad_icp_is_a_plain_error_and_nothing_is_written(tmp_path):
    db = make_db()
    bad = tmp_path / "icp.json"
    bad.write_text(json.dumps({"industries": ["dentist"], "locations": []}))
    with pytest.raises(ValueError, match="no locations"):
        tam.run(ctx_for(db), client="Acme Dental", icp=str(bad))
    bad.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        tam.run(ctx_for(db), client="Acme Dental", icp=str(bad))
    assert db.writes == []


def test_the_example_icp_file_is_valid():
    icp = tam.read_icp(str(HERE.parents[1] / "references/icp_example.json"))
    assert icp["industries"] and icp["locations"] and icp["fit_rule"]
