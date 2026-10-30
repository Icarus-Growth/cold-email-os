"""Fails if the OS app's stage lists differ from the database's.

    python3 tests/config_matches_db.py

The app reads its stage lists ("ladders") from two files:
    apps/os/frontend/src/core.config.ts     CORE_LADDERS (tasks, clients, team, calls)
    apps/os/frontend/src/agency.config.ts   LADDERS (this agency's boards)
The database keeps the same lists as enums in apps/os/backend/supabase/migrations/*.sql.

When they differ, a dragged card writes a stage the database refuses, or a stage that exists
in the database never shows on the board. So this check fails when:
  - a ladder is not an enum in the migrations, or its stages or their order differ;
  - a board, list or field names a ladder that is not in the config;
  - a board's "closed" stage is not on its ladder;
  - a board or checklist names a table that no migration makes.
It reads every migration in file-name order, so an Interview change that adds a stage
(alter type ... add value) is counted. Then add the same stage to the config, in the same place.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps" / "os" / "frontend" / "src"
MIGRATIONS = ROOT / "apps" / "os" / "backend" / "supabase" / "migrations"
CORE_CONFIG = SRC / "core.config.ts"
AGENCY_CONFIG = SRC / "agency.config.ts"

QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")


def strip_sql_comments(sql):
    return re.sub(r"--[^\n]*", "", sql)


def strip_ts_comments(ts):
    ts = re.sub(r"/\*.*?\*/", "", ts, flags=re.S)
    return re.sub(r"(^|[^:])//[^\n]*", r"\1", ts)


def ladders_in(path, name):
    """{ladder: [stages]} from the `<name> = { ... } as const` block of a config file."""
    text = strip_ts_comments(path.read_text())
    m = re.search(r"\b" + name + r"\s*=\s*\{(.*?)\}\s*as\s+const", text, re.S)
    if not m:
        return None
    out = {}
    for key, body in re.findall(r"(\w+)\s*:\s*\[(.*?)\]", m.group(1), re.S):
        out[key] = [v.replace("\\'", "'") for v in QUOTED.findall(body)]
    return out


def enums_in(files):
    """{enum: [values]} after running every create/alter type in order."""
    enums = {}
    problems = []
    create = re.compile(r"create\s+type\s+(?:public\.)?(\w+)\s+as\s+enum\s*\((.*?)\)\s*;", re.I | re.S)
    add = re.compile(
        r"alter\s+type\s+(?:public\.)?(\w+)\s+add\s+value\s+(?:if\s+not\s+exists\s+)?"
        r"'((?:[^']|'')*)'(?:\s+(before|after)\s+'((?:[^']|'')*)')?\s*;",
        re.I,
    )
    rename = re.compile(
        r"alter\s+type\s+(?:public\.)?(\w+)\s+rename\s+value\s+'((?:[^']|'')*)'\s+to\s+'((?:[^']|'')*)'\s*;", re.I
    )
    statement = re.compile("|".join("(?:%s)" % r.pattern for r in (create, add, rename)), re.I | re.S)
    for f in files:
        sql = strip_sql_comments(f.read_text())
        for s in statement.finditer(sql):
            text = s.group(0)
            c, a, r = create.fullmatch(text), add.fullmatch(text), rename.fullmatch(text)
            if c:
                enums[c.group(1)] = [v.replace("''", "'") for v in re.findall(r"'((?:[^']|'')*)'", c.group(2))]
            elif a:
                name, value, where, other = a.group(1), a.group(2).replace("''", "'"), a.group(3), a.group(4)
                if name not in enums:
                    problems.append(f"{f.name} adds '{value}' to {name}, but no earlier migration makes {name}.")
                    continue
                values = enums[name]
                if value in values:
                    continue
                if where and other is not None and other.replace("''", "'") in values:
                    i = values.index(other.replace("''", "'"))
                    values.insert(i if where.lower() == "before" else i + 1, value)
                else:
                    values.append(value)
            elif r:
                name, old, new = r.group(1), r.group(2).replace("''", "'"), r.group(3).replace("''", "'")
                values = enums.get(name, [])
                if old in values:
                    values[values.index(old)] = new
                else:
                    problems.append(f"{f.name} renames '{old}' in {name}, but {name} has no such value.")
    return enums, problems


def tables_in(files):
    found = set()
    for f in files:
        sql = strip_sql_comments(f.read_text())
        found.update(re.findall(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)", sql, re.I))
    return found


def show(values):
    return ", ".join(f"'{v}'" for v in values) or "(none)"


def main():
    problems = []
    if not CORE_CONFIG.exists():
        print(f"FAIL\n  - {CORE_CONFIG.relative_to(ROOT)} is missing.")
        return 1
    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        print(f"FAIL\n  - No migrations in {MIGRATIONS.relative_to(ROOT)}.")
        return 1

    ladders = {}
    configs = [(CORE_CONFIG, "CORE_LADDERS")]
    if AGENCY_CONFIG.exists():
        configs.append((AGENCY_CONFIG, "LADDERS"))
    else:
        print(f"note: {AGENCY_CONFIG.relative_to(ROOT)} is missing (normal in core/ alone; each agency type adds it).")
    for path, name in configs:
        found = ladders_in(path, name)
        if found is None:
            problems.append(f"{path.relative_to(ROOT)}: no `{name} = {{ ... }} as const` block found.")
            continue
        for key, stages in found.items():
            if key in ladders:
                problems.append(f"{path.relative_to(ROOT)}: ladder '{key}' is in two config files. Keep one.")
            ladders[key] = (path, stages)

    enums, enum_problems = enums_in(files)
    problems.extend(enum_problems)

    for key, (path, stages) in sorted(ladders.items()):
        where = path.relative_to(ROOT)
        if key not in enums:
            problems.append(f"{where}: ladder '{key}' is not an enum in the migrations. Fix the name, or add the enum.")
            continue
        db = enums[key]
        if stages == db:
            continue
        missing = [v for v in db if v not in stages]
        extra = [v for v in stages if v not in db]
        lines = [f"{where}: ladder '{key}' does not match the database."]
        if missing:
            lines.append(f"      in the database, not in the config: {show(missing)}")
        if extra:
            lines.append(f"      in the config, not in the database: {show(extra)}")
        if not missing and not extra:
            lines.append("      same stages, different order.")
        lines.append(f"      the database order is: [{show(db)}]")
        lines.append(f"      fix: make the config list exactly this, in this order.")
        problems.append("\n".join(lines))

    tables = tables_in(files)
    for path, _ in configs:
        text = strip_ts_comments(path.read_text())
        where = path.relative_to(ROOT)
        for kind, name in re.findall(r"\b(ladder|list|statusList)\s*:\s*'(\w+)'", text):
            if name not in ladders:
                problems.append(f"{where}: {kind} '{name}' is not a ladder in the config.")
        for ladder, closed in re.findall(r"\bladder\s*:\s*'(\w+)'\s*,\s*closed\s*:\s*\[(.*?)\]", text, re.S):
            stages = ladders.get(ladder, (None, []))[1]
            for v in QUOTED.findall(closed):
                if v not in stages:
                    problems.append(f"{where}: closed stage '{v}' is not on ladder '{ladder}'.")
        for name in re.findall(r"\btable\s*:\s*'(\w+)'", text):
            if name not in tables:
                problems.append(f"{where}: table '{name}' is not made by any migration.")

    if problems:
        print("FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"PASS: {len(ladders)} stage lists match the database ({len(files)} migrations read).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
