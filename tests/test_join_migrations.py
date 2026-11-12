"""The Tab 1 Step 10 join script (scripts/join_migrations.sh), in sh, bash and zsh.

    python3 -m pytest tests/test_join_migrations.py

Each test makes a small repo in a temporary folder: this repo's own change files,
the example file, the interview folder and the SQL editor folder. A fake
`supabase` command writes down every call. Nothing reaches a real project.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "join_migrations.sh"
MIG = Path("apps/os/backend/supabase/migrations")
SHELLS = [s for s in ("sh", "bash", "zsh") if shutil.which(s)]
STAMP = "20261111120000"

FAKE = """#!/bin/sh
echo "$*" >> "{log}"
case "$*" in
  *"migration repair"*) [ -e "{fail}" ] && {{ echo "Invalid access token" >&2; exit 1; }}; echo "Repaired." ;;
  *"migration list"*) echo "   Local          | Remote         "; echo "  {stamp} | {stamp}" ;;
  *"db push"*) echo "Remote database is up to date." ;;
esac
exit 0
"""


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


def make_repo(tmp: Path, use_git=True):
    repo = tmp / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, repo / "scripts" / "join_migrations.sh")
    real = sorted((ROOT / MIG).glob("[0-9][0-9][0-9][0-9]_*.sql"))
    (repo / MIG).mkdir(parents=True)
    if real:
        for f in real:
            shutil.copy2(f, repo / MIG / f.name)
    else:
        (repo / MIG / "0001_a.sql").write_text("select 1;\n")
    # One file with no new line at the end, so the join must add one.
    (repo / MIG / "0099_last.sql").write_text("select 'last';")
    (repo / "docs/examples").mkdir(parents=True)
    (repo / "docs/examples/add_examples.sql").write_text("-- examples\n")
    (repo / "docs/examples/delete_examples.sql").write_text("-- delete\n")
    (repo / "docs/interview").mkdir()
    (repo / "docs/interview/q1.sql").write_text("-- q1\n")
    se = repo / "apps/os/backend/supabase/sql-editor"
    se.mkdir()
    (se / "mark_baseline.sql").write_text("values ('<YYYYMMDDHHMMSS>', 'baseline')\n")
    if use_git:
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "start")
    log, fail = tmp / "calls.log", tmp / "fail"
    fake = tmp / "supabase"
    fake.write_text(FAKE.format(log=log, fail=fail, stamp=STAMP))
    fake.chmod(0o755)
    return repo, log, fail, fake


def run(shell, repo, fake, cwd=None):
    env = {**os.environ, "SUPABASE_CMD": str(fake), "JOIN_NOW": STAMP}
    return subprocess.run([shell, str(repo / "scripts" / "join_migrations.sh")], cwd=cwd or repo, env=env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("shell", SHELLS)
def test_join_moves_and_marks(tmp_path, shell):
    repo, log, _, fake = make_repo(tmp_path)
    olds = sorted(p.name for p in (repo / MIG).glob("[0-9][0-9][0-9][0-9]_*.sql"))
    texts = [(repo / MIG / n).read_text() for n in olds]
    r = run(shell, repo, fake)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout

    left = sorted(p.name for p in (repo / MIG).iterdir())
    assert left == [STAMP + "_baseline.sql"], left
    base = (repo / MIG / left[0]).read_text()
    assert base.splitlines()[0].startswith("-- Joined from the files in archive/migrations/.")
    at = 0
    for name, text in zip(olds, texts):
        at = base.index("-- From " + name, at)
        assert base.index(text.rstrip("\n"), at) > at
    assert "select 'last';\n" in base

    assert sorted(p.name for p in (repo / "archive/migrations").iterdir()) == olds
    assert (repo / "archive/examples/add_examples.sql").exists()
    assert (repo / "docs/examples/delete_examples.sql").exists()
    assert (repo / "archive/interview/q1.sql").exists() and not (repo / "docs/interview").exists()
    assert (repo / "archive/sql-editor/mark_baseline.sql").read_text() == "values ('%s', 'baseline')\n" % STAMP

    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert "R  apps/os/backend/supabase/migrations/%s -> archive/migrations/%s" % (olds[0], olds[0]) in status

    calls = log.read_text().splitlines()
    nums = " ".join(n.split("_")[0] for n in olds)
    assert calls[0] == "migration repair --linked --status reverted %s --workdir apps/os/backend --yes" % nums
    assert calls[1] == "migration repair --linked --status applied %s --workdir apps/os/backend --yes" % STAMP
    assert calls[2].startswith("migration list --linked")
    assert calls[3] == "db push --linked --dry-run --workdir apps/os/backend --yes"
    assert all("--yes" in c for c in calls if "repair" in c or "push" in c)


@pytest.mark.parametrize("shell", SHELLS)
def test_a_failed_mark_can_be_run_again(tmp_path, shell):
    repo, log, fail, fake = make_repo(tmp_path)
    fail.write_text("x")
    r = run(shell, repo, fake)
    assert r.returncode == 1 and "Marking the old files failed" in r.stderr
    assert sorted(p.name for p in (repo / MIG).iterdir()) == [STAMP + "_baseline.sql"]
    fail.unlink()
    r = run(shell, repo, fake, cwd=repo / "docs")  # from a sub folder, too
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Already done" in r.stdout and "PASS" in r.stdout
    assert len(list((repo / MIG).iterdir())) == 1, "a second run must not join twice"


@pytest.mark.parametrize("shell", SHELLS)
def test_nothing_moves_when_a_target_is_taken(tmp_path, shell):
    repo, log, _, fake = make_repo(tmp_path, use_git=False)
    (repo / "archive/interview").mkdir(parents=True)
    before = sorted(p.name for p in (repo / MIG).iterdir())
    r = run(shell, repo, fake)
    assert r.returncode == 1 and "archive/interview is already there" in r.stderr
    assert sorted(p.name for p in (repo / MIG).iterdir()) == before
    assert not log.exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_without_git_it_still_moves(tmp_path, shell):
    repo, _, _, fake = make_repo(tmp_path, use_git=False)
    r = run(shell, repo, fake)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / "archive/migrations").is_dir() and len(list((repo / MIG).iterdir())) == 1


def test_all_three_shells_are_here():
    assert {"sh", "bash", "zsh"} <= set(SHELLS) or os.environ.get("CI"), "install bash and zsh to test both"
