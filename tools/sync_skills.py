"""Link every skill in skills/ into .claude/skills/, so Claude Code finds them.

    python3 tools/sync_skills.py            make or fix the links (safe to run again and again)
    python3 tools/sync_skills.py --check    change nothing; exit 1 if a link is missing or stale,
                                            or a skill's header is wrong
    python3 tools/sync_skills.py --list     print every skill: area, agency, where it runs, keys

The real files live in skills/<fulfilment|owner|global>/<name>/. Codex, Grok and any other AI
read them there. Claude Code reads .claude/skills/<name>/, so this script puts a link there
for each skill. On Windows (no links) it copies the folder instead and marks the copy.

It only touches what it made: a link that points into skills/, or a copy with its mark.
Any other folder in .claude/skills/ (for example one a tool installed) is left alone.
The links are not committed: this script lists them in .git/info/exclude. Run it after a
clone or a pull, and after you add, rename or remove a skill.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
MARK = ".synced-from-skills"
EXCLUDE_START = "# >>> skills links (tools/sync_skills.py) >>>"
EXCLUDE_END = "# <<< skills links <<<"

sys.path.insert(0, str(ROOT / "skills" / "_kit"))
import skillkit  # noqa: E402


def tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.name != MARK and "__pycache__" not in p.parts and p.name != ".DS_Store":
            h.update(str(p.relative_to(folder)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def use_copies() -> bool:
    return os.name == "nt" or os.environ.get("SYNC_SKILLS_COPY") == "1"


def state_of(dest: Path, source: Path, root: Path) -> str:
    """'ok', 'missing', 'stale' (ours, but wrong) or 'foreign' (not ours: leave it)."""
    target = os.path.relpath(source, dest.parent)
    if dest.is_symlink():
        if os.readlink(str(dest)) == target and dest.exists():
            return "ok"
        return "stale" if is_ours(dest, root) else "foreign"
    if not dest.exists():
        return "missing"
    mark = dest / MARK
    if dest.is_dir() and mark.exists():
        lines = mark.read_text().splitlines()
        if len(lines) >= 2 and lines[0] == str(source.relative_to(root)) and lines[1] == tree_hash(source):
            return "ok"
        return "stale"
    return "foreign"


def is_ours(dest: Path, root: Path) -> bool:
    if dest.is_symlink():
        raw = os.readlink(str(dest))
        full = (dest.parent / raw).resolve() if not os.path.isabs(raw) else Path(raw)
        try:
            full.relative_to((root / "skills").resolve())
            return True
        except ValueError:
            return False
    return dest.is_dir() and (dest / MARK).exists()


def remove(dest: Path) -> None:
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)


def place(dest: Path, source: Path, root: Path) -> str:
    """Make the link (or the marked copy). Returns 'link' or 'copy'."""
    if not use_copies():
        try:
            os.symlink(os.path.relpath(source, dest.parent), str(dest), target_is_directory=True)
            return "link"
        except (OSError, NotImplementedError):
            pass
    shutil.copytree(str(source), str(dest), ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    (dest / MARK).write_text("{0}\n{1}\n".format(source.relative_to(root), tree_hash(source)))
    return "copy"


def plan(root: Path) -> Tuple[List[Dict], List[str]]:
    """What each skill needs, and every problem found (bad headers, two skills with one name,
    a name already taken by a folder that is not ours)."""
    skills = skillkit.find_skills(root)
    problems: List[str] = []
    seen: Dict[str, Path] = {}
    good = []
    for s in skills:
        rel = s["folder"].relative_to(root)
        for p in s["problems"]:
            problems.append("{0}: {1}".format(rel, p))
        if s["problems"]:
            continue
        name = s["card"]["name"]
        if name in seen:
            problems.append("{0}: the name '{1}' is also used by {2}".format(rel, name, seen[name].relative_to(root)))
            continue
        seen[name] = s["folder"]
        good.append(s)
    return good, problems


def git_exclude_file(root: Path) -> Optional[Path]:
    try:
        out = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=str(root),
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    p = Path(out.stdout.strip())
    return p if p.is_absolute() else root / p


def write_exclude(root: Path, names: List[str]) -> None:
    """List the links in .git/info/exclude, so git never commits them. Only our block changes."""
    f = git_exclude_file(root)
    if f is None:
        return
    top = root
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(root), capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            top = Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    rel = (root / ".claude/skills").resolve().relative_to(top)
    # One block per repo folder, so two copies inside one git repo never overwrite each other.
    start, end = "{0} {1}".format(EXCLUDE_START, rel.as_posix()), "{0} {1}".format(EXCLUDE_END, rel.as_posix())
    block = [start] + ["/{0}/{1}".format(rel.as_posix(), n) for n in sorted(names)] + [end]
    old = f.read_text().splitlines() if f.exists() else []
    if start in old and end in old:
        a, b = old.index(start), old.index(end)
        new = old[:a] + block + old[b + 1:]
    else:
        new = old + block
    if new != old:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(new) + "\n")


def sync(root: Path, check: bool) -> int:
    good, problems = plan(root)
    dest_dir = root / ".claude" / "skills"
    wanted = {s["card"]["name"]: s["folder"] for s in good}
    changes: List[str] = []

    for name, source in sorted(wanted.items()):
        dest = dest_dir / name
        st = state_of(dest, source, root)
        if st == "ok":
            continue
        if st == "foreign":
            problems.append(".claude/skills/{0} is a folder this script did not make. Rename the skill or move "
                            "that folder.".format(name))
            continue
        changes.append("{0} .claude/skills/{1}".format("missing:" if st == "missing" else "stale:", name))
        if not check:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if st == "stale":
                remove(dest)
            place(dest, source, root)

    if dest_dir.is_dir():
        for dest in sorted(dest_dir.iterdir()):
            if dest.name in wanted or not is_ours(dest, root):
                continue
            changes.append("left over: .claude/skills/{0} (its skill is gone)".format(dest.name))
            if not check:
                remove(dest)

    if not check:
        write_exclude(root, list(wanted))

    for p in problems:
        print("PROBLEM: " + p)
    if check:
        for c in changes:
            print("NOT IN STEP: " + c)
        if problems or changes:
            print("FAIL: run `python3 tools/sync_skills.py` and fix each problem above.")
            return 1
        print("PASS: {0} skills, every link in step.".format(len(wanted)))
        return 0
    for c in changes:
        print("fixed " + c)
    print("{0}: {1} skills linked into .claude/skills/{2}.".format(
        "DONE" if not problems else "DONE WITH PROBLEMS", len(wanted), " (copies)" if use_copies() else ""))
    return 1 if problems else 0


def show(root: Path) -> int:
    good, problems = plan(root)
    for s in good:
        c = s["card"]
        print("{0:<34} {1:<11} {2:<15} {3:<7} needs: {4}".format(
            c["name"], c["area"], c["agency"], c["runs_on"], ", ".join(c["needs"]) or "-"))
    for p in problems:
        print("PROBLEM: " + p)
    return 1 if problems else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Link skills/ into .claude/skills/.")
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 if anything is out of step")
    ap.add_argument("--list", action="store_true", help="print every skill")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    if a.list:
        return show(root)
    return sync(root, a.check)


if __name__ == "__main__":
    sys.exit(main())
