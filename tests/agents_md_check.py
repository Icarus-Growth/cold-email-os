"""Fails if CLAUDE.md and AGENTS.md differ, or if either is 150 lines or more.

    python3 tests/agents_md_check.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 150


def main() -> int:
    claude = ROOT / "CLAUDE.md"
    agents = ROOT / "AGENTS.md"
    problems = []
    for f in (claude, agents):
        if not f.exists():
            problems.append(f"{f.name} is missing.")
        elif len(f.read_text().splitlines()) >= LIMIT:
            problems.append(f"{f.name} has {len(f.read_text().splitlines())} lines. Keep it under {LIMIT}.")
    if claude.exists() and agents.exists() and claude.read_text() != agents.read_text():
        problems.append("CLAUDE.md and AGENTS.md are different. Make them the same, word for word.")
    if problems:
        print("FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"PASS: CLAUDE.md and AGENTS.md match ({len(claude.read_text().splitlines())} lines).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
