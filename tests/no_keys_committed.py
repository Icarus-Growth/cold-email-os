"""Fails if a key, token or password shape is found in a file that git tracks.

    python3 tests/no_keys_committed.py
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SHAPES = {
    "Supabase secret key": r"sb_secret_[A-Za-z0-9_-]{10,}",
    "Supabase access token": r"\bsbp_[A-Za-z0-9]{20,}",
    "JWT (old-style key)": r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "OpenAI-style key": r"\bsk-[A-Za-z0-9_-]{20,}",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    "Porkbun key": r"\b(pk1|sk1)_[A-Za-z0-9]{20,}",
    "Modal token": r"\b(ak|as)-[A-Za-z0-9]{20,}",
    "Private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}


def tracked_files():
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, capture_output=True, text=True, check=True)
        if Path(top.stdout.strip()).resolve() == ROOT:
            out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
            return [ROOT / p for p in out.splitlines()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # Not a git repo of its own yet: check every file.
    return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def main() -> int:
    hits = []
    for path in tracked_files():
        if path.name in (".env",) or not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for label, pattern in SHAPES.items():
            if re.search(pattern, text):
                hits.append(f"{path.relative_to(ROOT)}: looks like a {label}")
    if hits:
        print("FAIL: move these into .env and out of the file:")
        for h in hits:
            print(f"  - {h}")
        return 1
    print("PASS: no keys found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
