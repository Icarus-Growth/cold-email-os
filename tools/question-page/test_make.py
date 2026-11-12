"""Tests for the question page maker.   python3 tools/question-page/test_make.py

Every set in sets/ is valid; a bad set fails with plain words; the JSON goes into the page
safely; and (when Node is here) the "Copy answers" text marks skipped, unanswered and
commented questions and says where each answer goes."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make  # noqa: E402

FAILS = []


def test(fn):
    try:
        fn()
        print(f"ok   {fn.__doc__}")
    except AssertionError as e:
        FAILS.append(fn.__doc__)
        print(f"FAIL {fn.__doc__}\n     {e}")
    return fn


@test
def sets_valid():
    """every set in sets/ passes the check, and the three sets are there"""
    names = sorted(p.stem for p in (HERE / "sets").glob("*.json"))
    assert names == ["business", "second-brain", "who-are-you"], names
    for n in names:
        assert make.check(make.load(n)) == [], (n, make.check(make.load(n)))


@test
def second_brain_has_four():
    """the second brain set has 4 questions (question 5, the goal, is gone)"""
    qs = make.load("second-brain")["questions"]
    assert [q["id"] for q in qs] == ["whose", "areas", "where", "strict"], [q["id"] for q in qs]


@test
def bad_set():
    """a bad set fails with plain words, not a crash"""
    bad = {"title": "", "questions": [{"id": "a", "text": "Q", "parts": [{"k": "x", "type": "single"}]},
                                       {"id": "a", "text": "", "parts": [{"k": "_y", "type": "dropdown"}]}]}
    p = make.check(bad)
    joined = " | ".join(p)
    for want in ('needs a "title"', 'needs "opts"', "used twice", 'needs a "text"', 'type "dropdown"', 'not starting with "_"'):
        assert want in joined, (want, joined)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "bad.json"
        f.write_text("{not json")
        assert make.main([str(f), "--no-open", "--out", d]) == 1
        assert make.main(["no-such-set", "--no-open", "--out", d]) == 1


@test
def choices_flag():
    """--choices replaces the choices of one question"""
    d = make.load("second-brain")
    make.set_choices(d, ["areas=Sales;Offers;Lists and targeting"])
    assert d["questions"][1]["parts"][0]["opts"] == ["Sales", "Offers", "Lists and targeting"]
    try:
        make.set_choices(d, ["nope=a;b"])
        raise AssertionError("an unknown question id must fail")
    except ValueError:
        pass


@test
def page_safe():
    """the JSON goes into the page once, and a "</script>" in a question cannot break out"""
    d = make.load("business")
    d["questions"][0]["text"] = "Name</script><script>alert(1)</script>"
    html = make.page(d)
    assert "/*SET*/null" not in html
    assert html.count("</script>") == 1, "only the page's own closing script tag"
    with tempfile.TemporaryDirectory() as out:
        assert make.main(["who-are-you", "--no-open", "--out", out]) == 0
        assert (Path(out) / "who-are-you.html").exists()


@test
def copy_text():
    """the Copy answers text: answers, SKIPPED, NOT ANSWERED, comments, where each one goes"""
    node = shutil.which("node")
    if not node:
        print("     (skipped: Node is not installed)")
        return
    js = (HERE / "page.html").read_text().split("<script>")[1].split("</script>")[0]
    state = {"names": {"agency": "Brightside", "owner": "Ana"}, "find": {"find": ["Referrals", "Paid ads"], "_comment": "mostly\nreferrals"},
             "sell": {"_skip": True}, "goal": {"goal": "Line one\nLine two"}}
    run = js + "\nconst r = module.exports.answersText(" + json.dumps(make.load("business")) + ", " + json.dumps(state) + ");\nprocess.stdout.write(r);"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.cjs"
        f.write_text(run)
        text = subprocess.run([node, str(f)], capture_output=True, text=True, check=True).stdout
    assert text.startswith("ANSWERS: Business set-up"), text[:80]
    assert "1. What is your agency called, and what is your name?  [goes to: CLAUDE.md, About the business]" in text
    assert "   Agency name: Brightside\n   Your name: Ana" in text
    assert "   SKIPPED: leave for now" in text
    assert "   Answer: Referrals; Paid ads\n   Comment: mostly referrals" in text
    assert "[goes to: DECISIONS.md]" in text
    assert "   The goal:\n     - Line one\n     - Line two" in text
    assert "   NOT ANSWERED" in text
    assert "3 answered, 1 skipped, 6 not answered." in text, text[-300:]
    assert "Keep CLAUDE.md at 50 lines or fewer" in text


print(f"\n{6 - len(FAILS)}/6 passed")
sys.exit(1 if FAILS else 0)
