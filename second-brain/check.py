"""Checks the second brain. It reads the notes and changes nothing.

    python3 second-brain/check.py

It prints the number of notes in each area (area maps are not counted), then every problem it finds:
  * a [[link]] that points to no file;
  * two files with the same name (a [[link]] must point to one file only);
  * a file more than two folder levels down;
  * an area map that is not linked from INDEX.md, or that does not link back to [[INDEX]];
  * a note that does not link to its area map, or that its area map does not list;
  * a note with no "Source:" line, or a "Raw:" line that is not a [[link]] to a file in raw/
    or "none (an idea, not proven)".
It ends with PASS or FAIL. Use the counts for INDEX.md.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

BRAIN = Path(__file__).resolve().parent
NOT_NOTES = {"INDEX.md", "PROMPT.md"}
NOT_NOTE_FOLDERS = {"raw", "inbox"}
LINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
IDEA = "none (an idea, not proven)"


def links(text):
    out = []
    for t in LINK.findall(text):
        t = t.strip().lower()
        out.append(t[:-3] if t.endswith(".md") else t)
    return out


def main() -> int:
    every = sorted(p for p in BRAIN.rglob("*") if p.is_file() and p.name != ".DS_Store"
                   and "__pycache__" not in p.parts)
    by_name = defaultdict(set)
    for p in every:
        if p.suffix == ".md":
            by_name[p.stem.lower()].add(p)
        elif p.relative_to(BRAIN).parts[0] == "raw":
            # A raw file can be any kind of file: link it with or without its ending.
            by_name[p.name.lower()].add(p)
            by_name[p.stem.lower()].add(p)

    problems = []
    for name, places in sorted(by_name.items()):
        if len(places) > 1:
            problems.append("two files are named " + name + ": "
                            + ", ".join(sorted(str(p.relative_to(BRAIN)) for p in places)))
    for p in every:
        if len(p.relative_to(BRAIN).parts) > 2:
            problems.append(f"{p.relative_to(BRAIN)}: more than two folder levels down")

    md = [p for p in every if p.suffix == ".md"]
    notes = [p for p in md if p.name not in NOT_NOTES and p.relative_to(BRAIN).parts[0] not in NOT_NOTE_FOLDERS]
    maps = [p for p in notes if p.name.endswith("_map.md")]
    index = BRAIN / "INDEX.md"
    index_links = links(index.read_text(encoding="utf-8")) if index.exists() else []

    # Raw files and the inbox are kept word for word, so their text is not checked.
    for p in notes + ([index] if index.exists() else []):
        for target in links(p.read_text(encoding="utf-8")):
            if target not in by_name:
                problems.append(f"{p.relative_to(BRAIN)}: the link [[{target}]] points to no file")

    for m in maps:
        rel = m.relative_to(BRAIN)
        if m.stem.lower() not in index_links:
            problems.append(f"{rel}: INDEX.md does not link to this area map")
        if "index" not in links(m.read_text(encoding="utf-8")):
            problems.append(f"{rel}: does not link back to [[INDEX]]")

    counts = defaultdict(int)
    for m in maps:
        counts[m.relative_to(BRAIN).parts[0]] += 0
    for p in notes:
        if p in maps:
            continue
        rel = p.relative_to(BRAIN)
        area = rel.parts[0] if len(rel.parts) > 1 else "(top folder)"
        counts[area] += 1
        text = p.read_text(encoding="utf-8")
        out = links(text)
        area_map = BRAIN / rel.parts[0] / (rel.parts[0] + "_map.md")
        if area_map.exists():
            if area_map.stem.lower() not in out:
                problems.append(f"{rel}: does not link to its area map [[{area_map.stem}]]")
            if p.stem.lower() not in links(area_map.read_text(encoding="utf-8")):
                problems.append(f"{rel}: its area map does not list it")
        elif not [t for t in out if t != p.stem.lower()]:
            problems.append(f"{rel}: links to no other note")
        if not re.search(r"^\**Source:", text, re.M):
            problems.append(f"{rel}: has no 'Source:' line")
        raw = re.search(r"^\**Raw:\**\s*(.*)$", text, re.M)
        if not raw:
            problems.append(f"{rel}: has no 'Raw:' line")
        else:
            value = raw.group(1).strip()
            raw_links = links(value)
            in_raw = raw_links and all(
                any(f.relative_to(BRAIN).parts[0] == "raw" for f in by_name.get(t, ())) for t in raw_links)
            if not (in_raw or value.startswith(IDEA)):
                problems.append(f"{rel}: the Raw line must be a [[link]] to a file in raw/ or '{IDEA}'")

    print("Notes in each area (area maps not counted):")
    for area in sorted(counts):
        print(f"  {area}: {counts[area]}")
    print(f"  total: {sum(counts.values())} notes, {len(maps)} area maps")
    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)")
        for line in problems:
            print("  - " + line)
        return 1
    print("\nPASS: every link points to a file, and every note has its map, Source and Raw.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
