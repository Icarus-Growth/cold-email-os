"""Make a new client's notes folder from clients/_template/. Run it from the repo root.

    python3 skills/global/create-client/scripts/create_client.py --name "Acme Corp"
    python3 skills/global/create-client/scripts/create_client.py --name "Acme Corp" --folder acme
    python3 skills/global/create-client/scripts/create_client.py --name "Acme Corp" --dry-run

It copies every file in clients/_template/ to clients/<folder>/ and writes the client's
name where the template says {{CLIENT_NAME}}. The folder name comes from the client's
name (lower case, words joined by "-"). It never overwrites a folder that exists, and it
does not touch the database or Slack.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[4]
CLIENTS = REPO / "clients"
TEMPLATE = CLIENTS / "_template"
PLACEHOLDER = "{{CLIENT_NAME}}"


def folder_name(name: str) -> str:
    """'Acme Corp.' -> 'acme-corp'. Letters, numbers and "-" only."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower())
    return s.strip("-")


def plan(name: str, folder: str) -> List[Path]:
    """The files that would be made, in order."""
    return [CLIENTS / folder / p.relative_to(TEMPLATE) for p in sorted(TEMPLATE.rglob("*")) if p.is_file()]


def create(name: str, folder: str, dry_run: bool = False) -> List[Path]:
    if not TEMPLATE.is_dir():
        raise SystemExit("No clients/_template/ folder in this repo. Nothing made.")
    if not folder or folder.startswith("_"):
        raise SystemExit("The folder name {0!r} cannot be used. Pick another with --folder.".format(folder))
    target = CLIENTS / folder
    if target.exists():
        raise SystemExit("clients/{0}/ already exists. Open it, or pick another name with --folder.".format(folder))
    files = plan(name, folder)
    if dry_run:
        return files
    for src in sorted(TEMPLATE.rglob("*")):
        if not src.is_file():
            continue
        dst = target / src.relative_to(TEMPLATE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            dst.write_text(src.read_text().replace(PLACEHOLDER, name))
        except UnicodeDecodeError:
            dst.write_bytes(src.read_bytes())
    return files


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Make clients/<folder>/ from clients/_template/.")
    ap.add_argument("--name", required=True, help="The client's name, as it should read in the notes")
    ap.add_argument("--folder", help="The folder name (default: made from the name)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be made, and make nothing")
    args = ap.parse_args(argv)
    name = args.name.strip()
    if not name:
        raise SystemExit("--name is empty.")
    folder = folder_name(args.folder or name)
    files = create(name, folder, args.dry_run)
    print("{0} clients/{1}/ for {2}:".format("Would make" if args.dry_run else "Made", folder, name))
    for f in files:
        print("  " + str(f.relative_to(REPO)))
    if not args.dry_run:
        print("Next: fill in about.md. Keys for this client go in clients/{0}/.env (copy .env.example).".format(folder))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
