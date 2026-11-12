"""website-classifier, offline: a fake database, a fake Slack, fake web pages and a fake AI.

    python3 -m pytest skills/fulfilment/website-classifier -q
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

_spec = importlib.util.spec_from_file_location("wc_run", str(HERE.parents[1] / "scripts/run.py"))
wc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wc)  # type: ignore[union-attr]

CLIENT = "00000000-0000-4000-8000-00000000c001"
LONG = " We are a family dental practice in Austin. Our team of 9 treats patients of all ages." * 5

PAGES = {
    "https://acme-dental.example.com": ("Acme Dental", "Family dentist in Austin", LONG),
    "https://supplies.example.org": ("Dental Supplies", "We sell chairs to dentists", "We ship dental chairs." * 20),
    "https://parked.example.net": ("parked.example.net", "", "This domain is for sale. Buy this domain today." * 5),
    "https://thin.example.com": ("Coming soon", "", "Soon."),
    "https://maybe.example.com": ("Smile Studio", "", "Smiles for everyone in town." * 20),
}

ANSWERS = {
    "Acme Dental": {"verdict": "fit", "confidence": 95, "reason": "An independent dental practice.",
                    "evidence": "We are a family dental practice in Austin", "size_band": "1-10"},
    "Dental Supplies": {"verdict": "not fit", "confidence": 92, "reason": "A supplier, not a practice.",
                        "evidence": "We ship dental chairs.", "size_band": "unknown"},
    "Smile Studio": {"verdict": "fit", "confidence": 55, "reason": "Maybe a dental studio.", "evidence": "",
                     "size_band": "unknown"},
}


def fetch(url, timeout, max_bytes):
    if url not in PAGES:
        raise wc.FetchError("the site did not answer (timed out)")
    return PAGES[url]


def judge_with(calls):
    def judge(prompt, system):
        calls.append(prompt)
        assert "independent dental practice" in prompt and "fits a client's ideal customer" in system
        for name, answer in ANSWERS.items():
            if "Page title: " + name in prompt:
                return answer
        raise AssertionError("unexpected prompt")
    return judge


def company(i, name, url, **extra):
    row = {"id": "c{0}".format(i), "client_id": CLIENT, "company_name": name, "website": url,
           "created_at": "2026-11-01T00:00:{0:02d}Z".format(i)}
    row.update(extra)
    return row


def make_db():
    return fakes.FakeDB({
        "clients": [{"id": CLIENT, "client_name": "Acme Dental", "target_market": "independent dental practices"}],
        "settings": [{"id": "1", "os_url": "https://os.example.com"}],
        "lead_companies": [
            company(1, "Acme Dental", "https://acme-dental.example.com"),
            company(2, "Dental Supplies Co", "https://supplies.example.org"),
            company(3, "Parked", "https://parked.example.net"),
            company(4, "Thin", "thin.example.com"),
            company(5, "Gone", "https://gone.example.com"),
            company(6, "Smile Studio", "https://maybe.example.com"),
            company(7, "City Hospital Dental Unit", "https://hospital.example.org"),
            company(8, "No Site", None),
        ],
        "tasks": [], "stage_log": [],
    })


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


ICP = {"fit_rule": "An independent dental practice that treats patients.", "exclude": ["hospital"],
       "sizes": ["1-10", "11-50"]}


def test_live_run_writes_answers_with_reasons_and_posts_a_summary():
    db = make_db()
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    calls = []
    out = wc.run(ctx, client="Acme Dental", live=True, icp=ICP, fetch=fetch, judge=judge_with(calls))
    rows = {r["id"]: r for r in db.tables["lead_companies"]}
    assert rows["c1"]["fit_status"] == "fit" and rows["c1"]["fit_method"] == "ai"
    assert rows["c1"]["fit_evidence"].startswith("We are a family dental practice")
    assert rows["c1"]["size_band"] == "1-10"
    assert rows["c2"]["fit_status"] == "not fit" and "supplier" in rows["c2"]["fit_reason"]
    assert rows["c3"]["fit_status"] == "not fit" and rows["c3"]["fit_method"] == "free check"
    assert rows["c4"]["fit_status"] == "error" and "too little text" in rows["c4"]["fit_reason"]
    assert rows["c5"]["fit_status"] == "error" and "could not be read" in rows["c5"]["fit_reason"]
    assert rows["c6"]["fit_status"] == "unsure" and "Low confidence (55)" in rows["c6"]["fit_reason"]
    assert rows["c7"]["fit_status"] == "not fit" and "hospital" in rows["c7"]["fit_reason"]
    assert rows["c8"]["fit_status"] == "error"
    assert all(r.get("fit_checked_at") for r in rows.values())
    assert len(calls) == 3 and out["ai_checks_used"] == 3
    post = ctx.slack.posts[-1]
    assert post["channel"] == "chan-daily-summary"
    assert "8 companies checked: 1 fit, 3 not fit, 1 unsure" in post["text"]

    # Run again: nothing left, no AI call.
    again = wc.run(ctx, client="Acme Dental", live=True, icp=ICP, fetch=fetch, judge=judge_with(calls))
    assert "Nothing to do" in again["message"] and len(calls) == 3


def test_dry_run_spends_and_writes_nothing():
    db = make_db()
    calls = []
    out = wc.run(skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig()), client="Acme Dental", icp=ICP,
                 fetch=fetch, judge=judge_with(calls))
    assert out["dry_run"] and out["ai_checks_needed"] == 8 and calls == [] and db.writes == []


def test_ai_failure_stops_the_run_and_leaves_rows_for_next_time():
    db = make_db()
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())

    def broken(prompt, system):
        raise skillkit.AIError("The AI call failed (401): invalid key")

    out = wc.run(ctx, client="Acme Dental", live=True, icp=ICP, fetch=fetch, judge=broken)
    assert not out["ok"] and "invalid key" in out["message"]
    rows = {r["id"]: r for r in db.tables["lead_companies"]}
    assert not rows["c1"].get("fit_checked_at")  # left for the next run
    assert any(p["channel"] == "chan-pipeline-errors" for p in ctx.slack.posts)


def test_no_rule_is_a_plain_error_and_nothing_is_spent():
    db = make_db()
    db.tables["clients"][0]["target_market"] = None
    calls = []
    with pytest.raises(ValueError, match="No rule"):
        wc.run(skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig()), client="Acme Dental", live=True,
               fetch=fetch, judge=judge_with(calls))
    assert calls == [] and db.writes == []


def test_page_text_keeps_title_description_and_visible_words_only():
    html = ("<html><head><title>Acme &amp; Co</title><meta name=\"description\" content=\"Family dentist\">"
            "<style>.x{}</style><script>var a=1;</script></head><body><h1>Hello</h1><p>World</p></body></html>")
    assert wc.page_text(html) == ("Acme & Co", "Family dentist", "Acme & Co Hello World")
