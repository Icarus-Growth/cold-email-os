"""Small helper for the database. Python 3.9+, no installs needed.

It talks to your Supabase project through the Supabase Management API, with the
personal access token in .env (SUPABASE_ACCESS_TOKEN). It never prints a key.

    python3 apps/os/backend/db.py run FILE.sql      run one SQL file
    python3 apps/os/backend/db.py query "SQL"        run one SQL statement and print the rows
    python3 apps/os/backend/db.py add-owner --name "Jane Doe" --email jane@example.com
                                                     add (or update) the owner, who can sign in
    python3 apps/os/backend/db.py signups-off        turn off sign-ups (keeps email + password sign-in on)
    python3 apps/os/backend/db.py check              tables, row counts, locks, views, sign-up setting
    python3 apps/os/backend/db.py access             what a signed-in stranger can see (should be 0 everywhere)
    python3 apps/os/backend/db.py schema             write SCHEMAS.md from the live project
    python3 apps/os/backend/db.py keys               check the tab 1 lines in .env (names only, never values)

If you cannot run this, use the Supabase SQL editor instead. The paste files are in
apps/os/backend/supabase/sql-editor/ (after the tidy-up: archive/sql-editor/).
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[3]
BOARDS = "Tasks, Campaigns, Inbox set-ups"
API = "https://api.supabase.com/v1/projects"


TAB1_KEYS = (
    "SUPABASE_PROJECT_REF",
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_DB_PASSWORD",
    "SUPABASE_ACCESS_TOKEN",
)


def env_problems(text: str) -> List[str]:
    """The lines of .env that break `set -a; . ./.env`. Names only, never a value."""
    out = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            out.append(f"line {n}: no '=' on this line. Write NAME=value.")
            continue
        name, value = raw.split("=", 1)
        label = name.strip() or f"line {n}"
        if name != name.rstrip() or value != value.lstrip():
            out.append(f"{label} (line {n}): a space before or after '='. Write {name.strip()}=value, with no spaces.")
        elif not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            out.append(f"line {n}: '{name.strip()}' is not a key name. Use capital letters, numbers and _.")
        elif re.search(r"\s", value.strip().strip('"').strip("'")):
            out.append(f"{label} (line {n}): the value has a space in it. Keys and passwords have none: copy it again.")
    return out


def load_env() -> Dict[str, str]:
    env = {}
    path = ROOT / ".env"
    if path.exists():
        text = path.read_text()
        bad = env_problems(text)
        if bad:
            sys.exit(".env has lines the terminal cannot load:\n  " + "\n  ".join(bad))
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("SUPABASE_")})
    for name in ("SUPABASE_ACCESS_TOKEN", "SUPABASE_PROJECT_REF"):
        if not env.get(name):
            sys.exit(f"{name} is missing from .env. Add it (see .env.example), then run this again.")
    return env


def call(method: str, path: str, body=None):
    env = load_env()
    req = urllib.request.Request(
        f"{API}/{env['SUPABASE_PROJECT_REF']}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {env['SUPABASE_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "agency-os-db-helper",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode() or "null"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:2000]
        sys.exit(f"Supabase said {e.code}: {detail}")


def query(sql: str) -> List[dict]:
    rows = call("POST", "/database/query", {"query": sql})
    return rows if isinstance(rows, list) else []


def print_rows(rows: List[dict]) -> None:
    if not rows:
        print("(no rows)")
        return
    cols = list(rows[0].keys())
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols))


TABLES_SQL = """
select c.relname as table_name, c.relrowsecurity as locked
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r' order by 1
"""

VIEWS_SQL = """
select c.relname as view_name,
       coalesce(array_to_string(c.reloptions, ',') like '%security_invoker=true%', false) as reads_as_person_asking
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'v' order by 1
"""

ACCESS_SQL = """
create or replace function pg_temp.seen_by(who text) returns table(table_name text, rows_seen bigint)
language plpgsql as $f$
declare t text; n bigint;
begin
  perform set_config('request.jwt.claims', json_build_object('email', who, 'role', 'authenticated')::text, false);
  perform set_config('role', 'authenticated', false);
  for t in select c.relname from pg_class c join pg_namespace s on s.oid = c.relnamespace
           where s.nspname = 'public' and c.relkind in ('r', 'v') order by 1 loop
    begin
      execute format('select count(*) from public.%I', t) into n;
    exception when insufficient_privilege then n := 0;
    end;
    table_name := t; rows_seen := n; return next;
  end loop;
  perform set_config('role', 'none', false);
  perform set_config('request.jwt.claims', '', false);
end
$f$;
select * from pg_temp.seen_by('someone-not-on-the-team@example.com');
"""

SCHEMA_SQL = """
select c.table_name, c.column_name, c.ordinal_position,
       case when c.data_type = 'USER-DEFINED' then c.udt_name
            when c.data_type = 'ARRAY' then ltrim(c.udt_name, '_') || '[]'
            else c.data_type end as data_type,
       c.is_nullable = 'YES' as nullable,
       col_description(format('public.%I', c.table_name)::regclass, c.ordinal_position) as note,
       obj_description(format('public.%I', c.table_name)::regclass, 'pg_class') as table_note,
       t.table_type
from information_schema.columns c
join information_schema.tables t on t.table_schema = c.table_schema and t.table_name = c.table_name
where c.table_schema = 'public'
order by t.table_type, c.table_name, c.ordinal_position
"""

ENUM_SQL = """
select t.typname as list_name, string_agg(e.enumlabel, ', ' order by e.enumsortorder) as choices
from pg_type t join pg_enum e on e.enumtypid = t.oid
join pg_namespace n on n.oid = t.typnamespace
where n.nspname = 'public' group by t.typname order by 1
"""


def cmd_run(path: str) -> None:
    sql = Path(path).read_text()
    print_rows(query(sql))
    print(f"Done: {path}")


def cmd_signups_off() -> None:
    call("PATCH", "/config/auth", {"disable_signup": True, "external_email_enabled": True})
    # Supabase can take a few seconds to show the new setting, so read it back until it does.
    for _ in range(10):
        if call("GET", "/config/auth").get("disable_signup"):
            break
        time.sleep(3)
    cmd_signup_setting()


def cmd_signup_setting() -> None:
    cfg = call("GET", "/config/auth")
    off = bool(cfg.get("disable_signup"))
    email = bool(cfg.get("external_email_enabled"))
    print(f"Sign-ups off: {'YES' if off else 'NO (turn them off)'}")
    print(f"Email and password sign-in on: {'YES' if email else 'NO'}")


def cmd_check() -> None:
    tables = query(TABLES_SQL)
    counts = {}
    if tables:
        union = " union all ".join(
            "select '{0}' as t, count(*) as n from public.\"{0}\"".format(r["table_name"]) for r in tables
        )
        counts = {r["t"]: r["n"] for r in query(union)}
    print("TABLES (locked = only the team can see it)")
    for r in tables:
        print(f"  {r['table_name']:<28} rows: {counts.get(r['table_name'], '?'):<6} locked: {'yes' if r['locked'] else 'NO'}")
    print("VIEWS (should all read as the person asking)")
    for r in query(VIEWS_SQL):
        print(f"  {r['view_name']:<28} {'yes' if r['reads_as_person_asking'] else 'NO'}")
    trig = query("select tgrelid::regclass::text as board from pg_trigger where tgname like '%\\_log\\_stage' order by 1")
    print("STAGE LOG is on for: " + ", ".join(r["board"] for r in trig))
    guard = query("select tgrelid::regclass::text as t from pg_trigger where tgname like '%\\_delete\\_admin\\_only' order by 1")
    print("ONLY AN OWNER OR ADMIN can delete from: " + ", ".join(r["t"] for r in guard))
    cmd_signup_setting()


def cmd_access() -> None:
    rows = query(ACCESS_SQL)
    bad = [r for r in rows if int(r["rows_seen"]) > 0]
    print_rows(rows)
    print("PASS: a stranger sees nothing." if not bad else f"FAIL: a stranger can see {len(bad)} table(s).")


def cmd_schema() -> None:
    rows = query(SCHEMA_SQL)
    enums = query(ENUM_SQL)
    out = [
        "# SCHEMAS",
        "",
        "Every table and column in the live Supabase project. Written from the live project by",
        "`python3 apps/os/backend/db.py schema`. Run it again after every database change.",
        "",
        f"- **Boards in the OS:** {BOARDS}. Each board is a table with a stage list; every stage change"
        " is written to `stage_log`.",
        "- **Stage lists** (the numbered stages, in order) are in the last section, \"Stage ladders and lists\".",
        "- **Finished and live:** only a \"100 - ...\" stage is finished. `v_open_cards.is_live` marks a live stage:"
        " open, but never stuck or late.",
        "- **The rules** for any change are in `DATABASE_RULES.md`.",
        "",
    ]
    current = None
    for r in rows:
        if r["table_name"] != current:
            current = r["table_name"]
            kind = "view" if r["table_type"] == "VIEW" else "table"
            out += ["", f"## {current} ({kind})", ""]
            if r.get("table_note"):
                out += [r["table_note"], ""]
            out += ["| Column | Type | Empty allowed | Note |", "|---|---|---|---|"]
        note = (r.get("note") or "").replace("|", "/")
        out.append(f"| {r['column_name']} | {r['data_type']} | {'yes' if r['nullable'] else 'no'} | {note} |")
    out += ["", "## Stage ladders and lists", "", "| List | Choices, in order |", "|---|---|"]
    out += [f"| {e['list_name']} | {e['choices']} |" for e in enums]
    (ROOT / "SCHEMAS.md").write_text("\n".join(out) + "\n")
    print(f"Wrote SCHEMAS.md: {len({r['table_name'] for r in rows})} tables and views, {len(enums)} lists.")


def sql_text(value: str) -> str:
    """A safe SQL text value: wrap in quotes, write every quote twice."""
    return "'" + value.replace("'", "''") + "'"


def cmd_add_owner(argv: List[str]) -> None:
    opts = {}
    i = 0
    while i < len(argv) - 1:
        if argv[i] in ("--name", "--email"):
            opts[argv[i][2:]] = argv[i + 1].strip()
            i += 2
        else:
            i += 1
    name, email = opts.get("name", ""), opts.get("email", "").lower()
    if not name or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        sys.exit('Usage: db.py add-owner --name "Jane Doe" --email jane@example.com')
    query(
        "insert into public.team (full_name, email, access, can_sign_in) values ({}, {}, 'Owner', true) "
        "on conflict (email) do update set full_name = excluded.full_name, access = 'Owner', "
        "can_sign_in = true, status = 'Active'".format(sql_text(name), sql_text(email))
    )
    print_rows(query("select full_name, email, access, can_sign_in from public.team where email = " + sql_text(email)))


def cmd_keys() -> None:
    """Every tab 1 name has a value, and no line breaks the terminal. Prints names only."""
    path = ROOT / ".env"
    if not path.exists():
        sys.exit("FAIL: there is no .env file. Copy .env.example to .env, then fill it in.")
    text = path.read_text()
    bad = env_problems(text)
    values = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    for name in TAB1_KEYS:
        if not values.get(name):
            bad.append(f"{name}: no value. Fill it in.")
        else:
            print(f"  {name:<26} has a value")
    pw = values.get("SUPABASE_DB_PASSWORD", "")
    if pw and not pw.isalnum():
        bad.append("SUPABASE_DB_PASSWORD: use letters and numbers only (some symbols break `set -a`).")
    if bad:
        print("FAIL:\n  " + "\n  ".join(bad))
        sys.exit(1)
    print("PASS: every tab 1 key has a value, with no space before or after '='.")


def main(argv: List[str]) -> None:
    if len(argv) < 2:
        sys.exit(__doc__)
    name = argv[1]
    if name == "run" and len(argv) == 3:
        cmd_run(argv[2])
    elif name == "query" and len(argv) == 3:
        print_rows(query(argv[2]))
    elif name == "add-owner":
        cmd_add_owner(argv[2:])
    elif name == "signups-off":
        cmd_signups_off()
    elif name == "check":
        cmd_check()
    elif name == "access":
        cmd_access()
    elif name == "schema":
        cmd_schema()
    elif name == "keys":
        cmd_keys()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
