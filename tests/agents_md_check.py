"""Fails if the instructions files are not in their v2 shape.

    python3 tests/agents_md_check.py

  - CLAUDE.md exists and has 50 lines or fewer. It links to OS_BUILD_RULES.md and DATABASE_RULES.md.
  - AGENTS.md is exactly one line: "Read CLAUDE.md. It is the instructions file for every coding tool in this repo."
  - OS_BUILD_RULES.md and DATABASE_RULES.md exist (the rules live there, not in CLAUDE.md).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 50
AGENTS_LINE = "Read CLAUDE.md. It is the instructions file for every coding tool in this repo."


def problems(root: Path) -> list:
    out = []
    claude = root / "CLAUDE.md"
    agents = root / "AGENTS.md"
    if not claude.exists():
        out.append("CLAUDE.md is missing.")
    else:
        text = claude.read_text()
        n = len(text.splitlines())
        if n > LIMIT:
            out.append(f"CLAUDE.md has {n} lines. Keep it at {LIMIT} or fewer: move rules to OS_BUILD_RULES.md or DATABASE_RULES.md.")
        for name in ("OS_BUILD_RULES.md", "DATABASE_RULES.md"):
            if name not in text:
                out.append(f"CLAUDE.md does not link to {name}.")
    if not agents.exists():
        out.append("AGENTS.md is missing.")
    elif agents.read_text().strip() != AGENTS_LINE or len(agents.read_text().strip().splitlines()) != 1:
        out.append(f'AGENTS.md must be exactly one line: "{AGENTS_LINE}"')
    for name in ("OS_BUILD_RULES.md", "DATABASE_RULES.md"):
        if not (root / name).exists():
            out.append(f"{name} is missing.")
    return out


def main() -> int:
    found = problems(ROOT)
    if found:
        print("FAIL")
        for p in found:
            print(f"  - {p}")
        return 1
    n = len((ROOT / "CLAUDE.md").read_text().splitlines())
    print(f"PASS: CLAUDE.md has {n} lines (at most {LIMIT}); AGENTS.md is the one line; both rule files are there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
