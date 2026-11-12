"""Skills that run on Modal (plan Wave 2 item 3): one run_skill function and one /skill/<name>
address for every skill, and the daily skills inside the daily summary job (no new schedule).
A stand-in kit plays skills/_kit/skillkit.py, so these run before the skills folder is merged."""

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from fakes import AUTOMATIONS, REPO, FakeSlack, config
from test_daily_summary import TUESDAY_8, summary_world

import skills_runner
from daily_summary import run_daily_summary

CFG = config()

STAND_IN_KIT = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
CALLS = []
BREAK = []

def find_skill(name):
    folder = ROOT / "skills" / "fulfilment" / name
    if not (folder / "SKILL.md").exists():
        return None
    return {"folder": folder, "card": {"name": name, "runs_on": "local" if name.endswith("-local") else "modal"}}

def run_skill(name, args, db, slack, config, seen, where="modal"):
    CALLS.append(("run", name, args, where))
    return {"ok": True, "echo": args}

def run_daily_skills(db, slack, config, seen, today=None):
    CALLS.append(("daily", str(today)))
    if BREAK:
        raise RuntimeError("the kit broke")
    return {"stand-in": {"ok": True}}
'''


def skill(root, name, run_py=True):
    folder = root / "skills" / "fulfilment" / name
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: {0}\n---\n".format(name))
    if run_py:
        (folder / "scripts" / "run.py").write_text("def run(ctx, **args):\n    return {'ok': True}\n")


@pytest.fixture
def no_kit(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_runner, "KIT_PLACES", [tmp_path / "skills" / "_kit"])
    monkeypatch.delitem(sys.modules, "skillkit", raising=False)
    yield
    sys.modules.pop("skillkit", None)


@pytest.fixture
def kit(tmp_path, no_kit):
    (tmp_path / "skills" / "_kit").mkdir(parents=True)
    (tmp_path / "skills" / "_kit" / "skillkit.py").write_text(STAND_IN_KIT)
    skill(tmp_path, "hello")
    skill(tmp_path, "hello-local")
    skill(tmp_path, "notes-only", run_py=False)
    return skills_runner.kit()


def summary(db, slack, seen, hours=0, scheduled=True):
    return run_daily_summary(db, slack, CFG, seen, scheduled=scheduled, now_utc=TUESDAY_8 + timedelta(hours=hours))


def errors(slack):
    return [p for p in slack.posts if p["channel"] == CFG.channel_id("pipeline-errors")]


# --------------------------------------------------------------------------- no kit yet


def test_with_no_skills_kit_every_answer_is_plain_and_the_summary_still_posts(no_kit):
    assert skills_runner.kit() is None
    assert skills_runner.check("hello") == skills_runner.NOT_SET_UP
    assert skills_runner.run_skill("hello", {}, None, None, CFG, {}) == {"ok": False, "error": skills_runner.NOT_SET_UP}
    db, slack = summary_world(), FakeSlack()
    out = summary(db, slack, {})
    assert out["posted"] and out["daily_skills"] == {"skipped": "no skills kit"} and errors(slack) == []


# --------------------------------------------------------------------------- with a kit


def test_check_refuses_bad_names_missing_skills_computer_only_skills_and_skills_with_no_script(kit):
    assert skills_runner.check("hello") is None
    assert "lower case" in skills_runner.check("../hello")
    assert "lower case" in skills_runner.check("Hello")
    assert "No skill named 'nope'" in skills_runner.check("nope")
    assert "runs only on a computer" in skills_runner.check("hello-local")
    assert "no scripts/run.py" in skills_runner.check("notes-only")


def test_the_daily_skills_run_once_a_day_inside_the_summary(kit):
    db, slack, seen = summary_world(), FakeSlack(), {}
    out = summary(db, slack, seen)
    assert out["posted"] and out["daily_skills"] == {"stand-in": {"ok": True}}
    assert summary(db, slack, seen, hours=3, scheduled=False)["daily_skills"] == {"skipped": "already ran today"}
    assert summary(db, slack, seen, hours=1)["posted"] is False  # not the summary hour: nothing runs
    assert kit.CALLS == [("daily", str(TUESDAY_8.date()))]
    assert skills_runner.run_daily_skills(db, slack, CFG, seen, date(2026, 11, 18))["stand-in"]["ok"]  # next day


def test_a_broken_kit_is_reported_once_and_the_summary_is_still_out(kit):
    kit.BREAK.append(True)
    db, slack = summary_world(), FakeSlack()
    out = summary(db, slack, {})
    assert out["posted"] and out["daily_skills"] == {"error": "the kit broke"}
    assert len(errors(slack)) == 1 and "Daily skills" in errors(slack)[0]["text"]
    assert any(p["channel"] == CFG.channel_id("daily-summary") for p in slack.posts)


# --------------------------------------------------------------------------- the Modal app


def load_app(monkeypatch):
    pytest.importorskip("modal")
    pytest.importorskip("fastapi")
    monkeypatch.syspath_prepend(str(REPO))
    spec = importlib.util.spec_from_file_location("os_automations_app", str(AUTOMATIONS / "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def raw(fn):
    """The plain Python function under a Modal function (its name differs between Modal versions)."""
    for get in (lambda: fn._raw_f_, lambda: fn.get_raw_f(), lambda: fn.info.raw_f):
        try:
            f = get()
        except Exception:  # noqa: BLE001
            continue
        if callable(f):
            return f
    pytest.skip("this Modal version hides the plain function")


class Spawn:
    def __init__(self):
        self.calls = []

    async def aio(self, *args):
        self.calls.append(args)


class FakeFunction:
    def __init__(self):
        self.spawn = Spawn()


def test_the_skill_address_checks_the_secret_and_the_skill_then_starts_it(kit, monkeypatch):
    from fastapi.testclient import TestClient

    mod = load_app(monkeypatch)
    started = FakeFunction()
    monkeypatch.setattr(mod, "run_skill", started)
    monkeypatch.setenv("OS_SHARED_SECRET", "s3cret")
    c = TestClient(raw(mod.web)())
    ok = {"x-os-secret": "s3cret"}
    assert c.post("/skill/hello", json={}).status_code == 401
    assert c.post("/skill/hello", json={}, headers={"x-os-secret": "wrong"}).status_code == 401
    r = c.post("/skill/hello", json={"client": "c-1", "limit": 5}, headers=ok)
    assert r.status_code == 200 and r.json() == {"ok": True, "started": True, "skill": "hello"}
    assert started.spawn.calls == [("hello", json.dumps({"client": "c-1", "limit": 5}))]
    assert c.post("/skill/hello", headers=ok).status_code == 200 and started.spawn.calls[-1] == ("hello", "{}")
    r = c.post("/skill/nope", json={}, headers=ok)
    assert r.status_code == 404 and "No skill named 'nope'" in r.json()["error"]
    assert c.post("/skill/hello-local", json={}, headers=ok).status_code == 400
    assert c.post("/skill/Hello", json={}, headers=ok).status_code == 400
    assert c.post("/skill/hello", json=[1, 2], headers=ok).status_code == 400
    assert len(started.spawn.calls) == 2  # nothing else was started


def test_the_one_run_skill_function_runs_any_skill_on_modal_with_no_schedule(kit, monkeypatch):
    mod = load_app(monkeypatch)
    monkeypatch.setattr(mod, "_setup", lambda: ("db", FakeSlack(), CFG))
    out = raw(mod.run_skill)("hello", '{"limit": 3}')
    assert out == {"ok": True, "echo": {"limit": 3}}
    assert kit.CALLS[-1] == ("run", "hello", {"limit": 3}, "modal")
    text = (AUTOMATIONS / "app.py").read_text()
    block = text.split("def run_skill(")[0].rsplit("@app.function(", 1)[1]
    assert "schedule" not in block


# --------------------------------------------------------------------------- the real kit, once merged


def test_the_real_kit_answers_the_same_questions():
    real = REPO / "skills" / "_kit" / "skillkit.py"
    if not real.is_file():
        pytest.skip("skills/_kit is not in this copy yet")
    sys.modules.pop("skillkit", None)
    try:
        k = skills_runner.kit()
        assert k is not None and Path(k.__file__).resolve() == real.resolve()
        for name in ("find_skill", "run_skill", "run_daily_skills", "list_skills"):
            assert callable(getattr(k, name)), name
        for s in k.find_skills():
            if s["problems"]:
                continue
            name = s["card"]["name"]
            problem = skills_runner.check(name)
            if s["card"].get("runs_on") == "local":
                assert "runs only on a computer" in problem
            elif (s["folder"] / "scripts" / "run.py").exists():
                assert problem is None, (name, problem)
    finally:
        sys.modules.pop("skillkit", None)
