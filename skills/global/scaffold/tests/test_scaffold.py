"""The scaffold skill: each kind makes a valid skill whose own tests pass; bad input changes nothing.

    python3 -m pytest skills/global/scaffold -q
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
SCAFFOLD = HERE.parents[1]
ROOT = SCAFFOLD.parents[2]
sys.path.insert(0, str(SCAFFOLD / "scripts"))
sys.path.insert(0, str(ROOT / "skills/_kit"))
import scaffold_skill  # noqa: E402
import skillkit  # noqa: E402

DESC = "Does an example job for the team. Use when someone says do the example job."


@pytest.fixture()
def repo(tmp_path):
    """A small copy of a student repo: the kit, the sync script and the channels file."""
    shutil.copytree(str(ROOT / "skills/_kit"), str(tmp_path / "skills/_kit"),
                    ignore=shutil.ignore_patterns("tests", "__pycache__"))
    (tmp_path / "tools").mkdir()
    shutil.copy(str(ROOT / "tools/sync_skills.py"), str(tmp_path / "tools/sync_skills.py"))
    return tmp_path


CASES = [
    ["--name", "row-doer", "--kind", "rows", "--table", "tasks", "--daily", "--runs-on", "modal"],
    ["--name", "spend-thing", "--kind", "rows", "--table", "inbox_batches", "--spends", "--runs-on", "either"],
    ["--name", "job-thing", "--kind", "job", "--runs-on", "server", "--needs", "ANTHROPIC_API_KEY"],
    ["--name", "grok-steps", "--kind", "steps", "--runs-on", "grok", "--area", "owner"],
]


@pytest.mark.parametrize("args", CASES, ids=[c[1] for c in CASES])
def test_scaffold_example_each_kind_makes_a_working_skill(repo, args):
    assert scaffold_skill.main(args + ["--description", DESC, "--root", str(repo)]) == 0
    found = {s["card"]["name"]: s for s in skillkit.find_skills(repo)}
    skill = found[args[1]]
    assert skill["problems"] == []
    card = skill["card"]
    assert card["runs_on"] == {"modal": "modal", "either": "either", "server": "local", "grok": "local"}[args[args.index("--runs-on") + 1]]
    if "--kind" in args and args[args.index("--kind") + 1] != "steps":
        assert card["needs"][:2] == ["SUPABASE_URL", "SUPABASE_SECRET_KEY"]
        res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(skill["folder"])],
                             capture_output=True, text=True, cwd=str(repo))
        assert res.returncode == 0, res.stdout + res.stderr
    assert (repo / ".claude/skills" / args[1]).exists()
    text = (skill["folder"] / "SKILL.md").read_text()
    if "--daily" in args:
        assert card.get("daily") is True and (skill["folder"] / "scripts/daily.py").exists()
        assert "app.py::run_skill --name row-doer" in text
    if "--spends" in args:
        assert "Spend gate" in text
    if args[1] == "job-thing":
        assert "crontab" in text and "ANTHROPIC_API_KEY" in text
    if args[1] == "grok-steps":
        assert "Grok" in text and not (skill["folder"] / "scripts").exists()


def test_scaffold_bad_input_changes_nothing(repo, capsys):
    assert scaffold_skill.main(["--name", "Bad Name", "--description", DESC, "--root", str(repo)]) == 2
    assert scaffold_skill.main(["--name", "ok-name", "--description", "short", "--root", str(repo)]) == 2
    assert scaffold_skill.main(["--name", "no-code", "--kind", "steps", "--runs-on", "modal",
                                "--description", DESC, "--root", str(repo)]) == 2
    assert scaffold_skill.main(["--name", "ok-name", "--needs", "lower_case", "--description", DESC,
                                "--root", str(repo)]) == 2
    out = capsys.readouterr().out
    assert "small letters" in out and "cannot run on the automation server" in out
    assert not (repo / "skills/fulfilment").exists()


def test_scaffold_never_overwrites_a_skill(repo):
    assert scaffold_skill.main(["--name", "twice", "--description", DESC, "--root", str(repo)]) == 0
    marker = repo / "skills/fulfilment/twice/SKILL.md"
    marker.write_text(marker.read_text() + "\nmy edits\n")
    assert scaffold_skill.main(["--name", "twice", "--area", "global", "--description", DESC, "--root", str(repo)]) == 2
    assert "my edits" in marker.read_text()


def test_run_skill_dispatch_runs_a_scaffolded_skill(repo):
    """The automations app's one run_skill entry runs a new skill with no new function."""
    assert scaffold_skill.main(["--name", "job-on-server", "--kind", "job", "--description", DESC,
                                "--root", str(repo)]) == 0
    import skill_fakes as fakes

    db = fakes.FakeDB({"tasks": [{"id": "t1"}]})
    out = skillkit.run_skill("job-on-server", {}, db, fakes.FakeSlack(), fakes.FakeConfig(), {}, root=repo)
    assert out["ok"] and out["rows"] == 1
    bad = skillkit.run_skill("job-on-server", {"nope": 1}, db, fakes.FakeSlack(), fakes.FakeConfig(), {}, root=repo)
    assert bad["ok"] is False and "Unknown input" in bad["error"]
    assert skillkit.run_skill("missing", {}, db, None, None, root=repo)["ok"] is False
