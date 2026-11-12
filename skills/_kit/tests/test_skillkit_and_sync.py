"""The skill kit and tools/sync_skills.py, offline.

    python3 -m pytest skills/_kit/tests -q        (from the repo root)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
ROOT = KIT.parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(ROOT / "tools"))

import skill_fakes as fakes  # noqa: E402
import skillkit  # noqa: E402
import sync_skills  # noqa: E402

GOOD = """---
name: {name}
description: Does one example job. Use when the user says "do the example job".
area: {area}
agency: all
needs: [SUPABASE_URL, SUPABASE_SECRET_KEY]
runs_on: either
---

# Example
"""


def make_repo(tmp_path: Path, skills=(("global", "alpha"), ("owner", "beta"))) -> Path:
    for area, name in skills:
        d = tmp_path / "skills" / area / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(GOOD.format(name=name, area=area))
    return tmp_path


# --------------------------------------------------------------------------- the header


def test_parse_frontmatter_lists_and_flags():
    card = skillkit.parse_frontmatter("---\nname: a\nneeds:\n  - A_KEY\n  - B_KEY\ndaily: true\nx: []\n---\nbody")
    assert card == {"name": "a", "needs": ["A_KEY", "B_KEY"], "daily": True, "x": []}
    assert skillkit.parse_frontmatter("no header") == {}
    assert skillkit.parse_frontmatter("---\nname: a\n") == {}


def test_bad_header_is_named_in_plain_words(tmp_path):
    d = tmp_path / "skills" / "global" / "gamma"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: other\ndescription: short\narea: owner\nagency: law\nneeds: lower\n---\n")
    probs = skillkit.find_skills(tmp_path)[0]["problems"]
    text = " | ".join(probs)
    assert "match the folder name" in text
    assert "'runs_on'" in text
    assert "skills/global/" in text
    assert "'agency' must be" in text
    assert "'needs' must be a list" in text


def test_every_real_skill_header_is_valid():
    """Every skill shipped in this repo (core and, in the working repo, every type)."""
    roots = [ROOT]
    types = ROOT.parent / "types"
    if (ROOT.name == "core") and types.is_dir():
        roots += [t for t in types.iterdir() if (t / "skills").is_dir()]
    found = 0
    for r in roots:
        for s in skillkit.find_skills(r):
            found += 1
            assert not s["problems"], "{0}: {1}".format(s["folder"], s["problems"])
    assert found >= 2


def test_roles_owner_skills_only_for_owner_and_admin(tmp_path):
    repo = make_repo(tmp_path)
    assert {s["name"] for s in skillkit.list_skills(repo, "Owner")} == {"alpha", "beta"}
    assert {s["name"] for s in skillkit.list_skills(repo, "Admin")} == {"alpha", "beta"}
    assert {s["name"] for s in skillkit.list_skills(repo, "Member")} == {"alpha"}
    assert skillkit.list_skills(repo, "Member")[0]["id"] == "global/alpha"


# --------------------------------------------------------------------------- keys


def test_missing_key_says_where_and_never_the_value(monkeypatch):
    monkeypatch.setenv("SET_KEY", "secret-value-123")
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with pytest.raises(skillkit.MissingKey) as e:
        skillkit.need(["SET_KEY", "MISSING_KEY"], {"MISSING_KEY": "the tool's API page"})
    msg = str(e.value)
    assert "MISSING_KEY: get it from the tool's API page" in msg
    assert "secret-value-123" not in msg and "SET_KEY" not in msg


# --------------------------------------------------------------------------- batches and resume


def test_batches_never_exceed_500():
    sizes = [len(b) for b in skillkit.batches(range(1234), size=10000)]
    assert sizes == [500, 500, 234]


def test_run_in_batches_resumes_from_the_database():
    db = fakes.FakeDB({"items": [{"id": str(i), "done_at": None} for i in range(7)]})
    calls = {"n": 0}

    def todo(limit):
        return db.select("items", {"done_at": "is.null"}, limit=limit)

    def work(rows):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("crash in batch 2")
        for r in rows:
            db.update("items", r["id"], {"done_at": "now"})
        return len(rows)

    with pytest.raises(RuntimeError):
        skillkit.run_in_batches(todo, work, size=3)
    assert len(db.select("items", {"done_at": "is.null"})) == 4  # first batch kept
    out = skillkit.run_in_batches(todo, work, size=3)  # the next run picks up
    assert out == {"batches": 2, "done": 4}
    assert db.select("items", {"done_at": "is.null"}) == []


# --------------------------------------------------------------------------- spend gate


def test_spend_gate_needs_a_person_to_move_the_card():
    db = fakes.FakeDB({"stage_log": [
        {"id": "1", "board": "inbox_batches", "record_id": "b1", "from_stage": "10 - Approval Needed",
         "to_stage": "20 - Buying Domains", "changed_by_id": None, "changed_at": "2026-11-01T10:00:00Z"},
    ]})
    with pytest.raises(skillkit.NotApproved):
        skillkit.require_approval(db, "inbox_batches", "b1", "10 - Approval Needed")
    db.tables["stage_log"].append({"id": "2", "board": "inbox_batches", "record_id": "b1",
                                   "from_stage": "10 - Approval Needed", "to_stage": "20 - Buying Domains",
                                   "changed_by_id": "person-1", "changed_at": "2026-11-02T10:00:00Z"})
    assert skillkit.require_approval(db, "inbox_batches", "b1", "10 - Approval Needed")["changed_by_id"] == "person-1"


def test_approval_ask_goes_to_review_with_a_button():
    ctx = skillkit.Context(fakes.FakeDB(), fakes.FakeSlack(), fakes.FakeConfig())
    skillkit.ask_for_approval(ctx, "Buy 4 domains", ["Cost: about 40 USD"], "https://os.example.com/board/x/1")
    post = ctx.slack.posts[0]
    assert post["channel"] == "chan-review"
    assert post["blocks"][1]["elements"][0]["url"] == "https://os.example.com/board/x/1"


def test_failure_posted_once():
    ctx = skillkit.Context(fakes.FakeDB(), fakes.FakeSlack(), fakes.FakeConfig())
    for _ in range(3):
        skillkit.report_failure(ctx, "demo", "step 1", ValueError("bad row"))
    assert len(ctx.slack.posts) == 1 and ctx.slack.posts[0]["channel"] == "chan-pipeline-errors"


# --------------------------------------------------------------------------- daily hook


def test_daily_hook_runs_each_skill_and_reports_one_failure(tmp_path):
    for name, body in (("good-one", "def run(db, slack, config, seen, today):\n    return {'ok': True}\n"),
                       ("bad-one", "def run(db, slack, config, seen, today):\n    raise ValueError('boom')\n")):
        d = tmp_path / "skills" / "fulfilment" / name
        (d / "scripts").mkdir(parents=True)
        (d / "SKILL.md").write_text(GOOD.format(name=name, area="fulfilment").replace("runs_on", "daily: true\nruns_on"))
        (d / "scripts" / "daily.py").write_text(body)
    slack = fakes.FakeSlack()
    out = skillkit.run_daily_skills(fakes.FakeDB(), slack, fakes.FakeConfig(), {}, root=tmp_path)
    assert out["good-one"] == {"ok": True}
    assert out["bad-one"]["ok"] is False
    assert [p["channel"] for p in slack.posts] == ["chan-pipeline-errors"]


# --------------------------------------------------------------------------- sync_skills


def test_sync_links_then_check_passes_and_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SYNC_SKILLS_COPY", raising=False)
    repo = make_repo(tmp_path)
    assert sync_skills.main(["--root", str(repo), "--check"]) == 1
    assert sync_skills.main(["--root", str(repo)]) == 0
    link = repo / ".claude/skills/alpha"
    assert link.is_symlink() and (link / "SKILL.md").exists()
    assert os.readlink(str(link)) == "../../skills/global/alpha"
    assert sync_skills.main(["--root", str(repo)]) == 0
    assert sync_skills.main(["--root", str(repo), "--check"]) == 0


def test_sync_removes_links_of_deleted_skills_and_leaves_other_folders(tmp_path):
    repo = make_repo(tmp_path)
    sync_skills.main(["--root", str(repo)])
    other = repo / ".claude/skills/installed-by-a-tool"
    other.mkdir()
    (other / "SKILL.md").write_text("not ours")
    import shutil

    shutil.rmtree(str(repo / "skills/owner/beta"))
    assert sync_skills.main(["--root", str(repo), "--check"]) == 1
    sync_skills.main(["--root", str(repo)])
    assert not (repo / ".claude/skills/beta").exists()
    assert (other / "SKILL.md").read_text() == "not ours"


def test_sync_copies_on_windows_and_finds_stale_copies(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNC_SKILLS_COPY", "1")
    repo = make_repo(tmp_path)
    assert sync_skills.main(["--root", str(repo)]) == 0
    copy = repo / ".claude/skills/alpha"
    assert copy.is_dir() and not copy.is_symlink() and (copy / sync_skills.MARK).exists()
    (repo / "skills/global/alpha/SKILL.md").write_text(GOOD.format(name="alpha", area="global") + "\nmore\n")
    assert sync_skills.main(["--root", str(repo), "--check"]) == 1
    assert sync_skills.main(["--root", str(repo)]) == 0
    assert "more" in (copy / "SKILL.md").read_text()


def test_sync_refuses_two_skills_with_one_name_and_a_foreign_folder(tmp_path):
    repo = make_repo(tmp_path, skills=(("global", "alpha"), ("fulfilment", "alpha")))
    assert sync_skills.main(["--root", str(repo)]) == 1
    repo2 = make_repo(tmp_path / "two", skills=(("global", "gamma"),))
    (repo2 / ".claude/skills/gamma").mkdir(parents=True)
    assert sync_skills.main(["--root", str(repo2)]) == 1
    assert not (repo2 / ".claude/skills/gamma").is_symlink()


def test_sync_two_repo_folders_in_one_git_repo_keep_their_own_lines(tmp_path):
    import subprocess

    if subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True).returncode != 0:
        pytest.skip("git is not installed")
    one = make_repo(tmp_path / "one", skills=(("global", "alpha"),))
    two = make_repo(tmp_path / "two", skills=(("global", "beta"),))
    sync_skills.main(["--root", str(one)])
    sync_skills.main(["--root", str(two)])
    sync_skills.main(["--root", str(one)])
    text = (tmp_path / ".git/info/exclude").read_text()
    assert "/one/.claude/skills/alpha" in text and "/two/.claude/skills/beta" in text
    assert text.count("/one/.claude/skills/alpha") == 1
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(tmp_path), capture_output=True, text=True).stdout
    assert ".claude" not in status


def test_ask_ai_uses_the_low_cost_model_and_a_json_schema(monkeypatch):
    import io
    import json as _json
    import urllib.request

    sent = {}

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        sent["body"] = _json.loads(req.data.decode())
        sent["headers"] = {k.lower(): v for k, v in req.header_items()}
        return Reply(_json.dumps({"stop_reason": "end_turn",
                                  "content": [{"type": "text", "text": "{\"fit\": true}"}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("AI_MODEL", raising=False)
    out = skillkit.ask_ai("Is this a dentist?", schema={"type": "object", "properties": {"fit": {"type": "boolean"}}})
    assert out == {"fit": True}
    assert sent["body"]["model"] == "claude-haiku-5-5"
    assert sent["body"]["output_config"]["format"]["type"] == "json_schema"
    assert "fallbacks" not in sent["body"]
    monkeypatch.setenv("AI_MODEL", "claude-sonnet-5-5")
    skillkit.ask_ai("again")
    assert sent["body"]["model"] == "claude-sonnet-5-5" and sent["body"]["fallbacks"] == "default"


def test_ask_ai_without_a_key_stops_before_any_call(monkeypatch):
    import urllib.request

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    with pytest.raises(skillkit.MissingKey):
        skillkit.ask_ai("hello")
