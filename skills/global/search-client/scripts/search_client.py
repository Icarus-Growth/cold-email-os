"""Find everything about one client. Run it from the repo root. Reads .env; never prints a key.

    python3 skills/global/search-client/scripts/search_client.py "Acme"
    python3 skills/global/search-client/scripts/search_client.py --email jane@example.com
    python3 skills/global/search-client/scripts/search_client.py --id <client row id>
    python3 skills/global/search-client/scripts/search_client.py "Acme" --full      every column of every row
    python3 skills/global/search-client/scripts/search_client.py "Acme" --json      the same, as JSON
    python3 skills/global/search-client/scripts/search_client.py "Acme" --files-only   skip the database

1. Find the client. First the sure matches: the same name (case, dots and "Inc", "Ltd"
   and so on do not count), the same email, an email on the client's own domain, or a name
   listed in the client's clients/<name>/about.md. Only when there is none, close matches
   (a name that is spelled nearly the same, or holds the words searched for). A close match
   is always marked as one. Two or more matches: it lists them and stops, so you can pick.
2. Gather it: the client's row, its rows on every table that has a client_id column (every
   board, the calls, the forms, the report numbers, the stage history), and the files in
   clients/<name>/. Every read goes in pages of at most 500 rows.

It only reads. Standard library only, Python 3.9.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from shared.supabase_client import Supabase, SupabaseError, load_dotenv  # noqa: E402

CLIENTS_DIR = REPO / "clients"
SURE, CLOSE = 0.86, 0.62
SUFFIXES = {"inc", "ltd", "llc", "limited", "co", "corp", "corporation", "company", "gmbh", "plc", "llp", "the"}
MAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "example.com",
}
# Tables read for the client's history. Used when the database cannot list its tables.
FALLBACK_TABLES = ["tasks", "calls", "onboarding_forms", "daily_metrics", "weekly_metrics", "stage_log"]
SKIP_TABLES = {"clients", "onboarding_form_drafts"}
SHOW_ROWS = 25


# --------------------------------------------------------------------------- names


def norm(text: Any) -> str:
    """'The Acme Corp., Inc.' -> 'acme'. Pure."""
    words = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def domain_of(text: Any) -> str:
    """An email or a web address -> its domain, without www. Pure."""
    t = str(text or "").strip().lower()
    if "@" in t:
        t = t.split("@", 1)[1]
    t = re.sub(r"^[a-z]+://", "", t).split("/")[0].split("?")[0]
    return t[4:] if t.startswith("www.") else t


# --------------------------------------------------------------------------- the notes folders


def section_items(text: str, heading: str) -> List[str]:
    """The bullet lines under one '### heading' (or '## heading') of about.md. Pure."""
    m = re.search(r"^#{2,3} " + re.escape(heading) + r"[^\n]*\n(.*?)(?=^#{1,3} |\Z)", text, re.M | re.S | re.I)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("- "):
            item = re.sub(r"\*\*[^*]+:\*\*", "", line[2:]).strip()
            if item and not item.startswith("<!--"):
                out.append(item)
    return out


def read_folder(path: Path) -> Dict[str, Any]:
    """What a clients/<name>/ folder says about who the client is. Pure apart from reading."""
    about = (path / "about.md").read_text() if (path / "about.md").exists() else ""
    names = [path.name.replace("-", " ")]
    head = re.search(r"^# (.+?)(?::\s*About)?\s*$", about, re.M)
    if head:
        names.append(head.group(1))
    legal = re.search(r"\*\*Legal name:\*\*\s*(.+)", about, re.I)
    if legal and legal.group(1).strip():
        names.append(legal.group(1).strip())
    for h in ("Company name variations", "Short forms", "Sub-brands"):
        names += section_items(about, h)
    emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", about))
    domains = {domain_of(d) for d in section_items(about, "Domains and links")}
    domains |= {domain_of(e) for e in emails}
    website = re.search(r"\*\*Website:\*\*\s*(\S+)", about, re.I)
    if website:
        domains.add(domain_of(website.group(1)))
    people = section_items(about, "People")
    return {
        "folder": path.name,
        "path": str(path.relative_to(REPO)),
        "names": [n for n in dict.fromkeys(names) if norm(n)],
        "emails": {e.lower() for e in emails},
        "domains": {d for d in domains if d and d not in MAIL_DOMAINS and "." in d},
        "people": people,
        "files": sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file() and p.name != ".env"),
    }


def all_folders(root: Path = CLIENTS_DIR) -> List[Dict[str, Any]]:
    if not root.is_dir():
        return []
    return [read_folder(p) for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(("_", "."))]


# --------------------------------------------------------------------------- matching


def row_names(row: Dict[str, Any]) -> List[str]:
    return [row.get("client_name") or ""]


def row_domains(row: Dict[str, Any]) -> set:
    out = {domain_of(row.get("website")), domain_of(row.get("contact_email"))}
    return {d for d in out if d and d not in MAIL_DOMAINS and "." in d}


def score(query: str, names: List[str]) -> float:
    """How close the words searched for are to the best of these names (0 to 1). Pure."""
    q = norm(query)
    if not q:
        return 0.0
    best = 0.0
    for n in names:
        n = norm(n)
        if not n:
            continue
        ratio = difflib.SequenceMatcher(None, q, n).ratio()
        if q in n.split() or set(q.split()) <= set(n.split()):
            ratio = max(ratio, 0.75)
        best = max(best, ratio)
    return best


def sure_match(query: str, email: str, names: List[str], emails: set, domains: set) -> Optional[str]:
    """Why this is a sure match, or None. Pure."""
    q = norm(query)
    if q and any(norm(n) == q for n in names):
        return "same name"
    e = (email or "").strip().lower()
    if e and e in emails:
        return "same email"
    d = domain_of(e)
    if d and d not in MAIL_DOMAINS and d in domains:
        return "email on the client's domain"
    return None


def find(
    query: str, email: str, rows: List[Dict[str, Any]], folders: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], str]:
    """Candidates as [{row, folder, why, sure}], and "sure", "close" or "none". Pure.

    A database row and a notes folder that share a name are one client."""
    clients: List[Dict[str, Any]] = []
    used = set()
    for row in rows:
        folder = next((f for f in folders if norm(row.get("client_name")) in {norm(n) for n in f["names"]}), None)
        if folder:
            used.add(folder["folder"])
        clients.append({"row": row, "folder": folder})
    for f in folders:
        if f["folder"] not in used:
            clients.append({"row": None, "folder": f})

    def facts(c: Dict[str, Any]) -> Tuple[List[str], set, set]:
        names, emails, domains = [], set(), set()
        if c["row"]:
            names += row_names(c["row"])
            if c["row"].get("contact_email"):
                emails.add(c["row"]["contact_email"].lower())
            domains |= row_domains(c["row"])
        if c["folder"]:
            names += c["folder"]["names"]
            emails |= c["folder"]["emails"]
            domains |= c["folder"]["domains"]
        return names, emails, domains

    sure, close = [], []
    for c in clients:
        names, emails, domains = facts(c)
        why = sure_match(query, email, names, emails, domains)
        if why:
            sure.append(dict(c, why=why, sure=True))
            continue
        s = score(query, names)
        if s >= CLOSE:
            word = "very close" if s >= SURE else "close"
            close.append(dict(c, why="{0} match ({1:.0%}), check it".format(word, s), sure=False, score=s))
    if sure:
        return sure, "sure"
    close.sort(key=lambda c: -c["score"])
    return close, ("close" if close else "none")


# --------------------------------------------------------------------------- the database


def client_tables(db: Any) -> Dict[str, List[str]]:
    """{table: [columns]} for every table with a client_id column, read from the database's
    own list. Views (v_...) and server-only tables are left out."""
    try:
        spec = db.request("GET", "") or {}
        defs = spec.get("definitions", {})
    except SupabaseError:
        defs = {}
    if not defs:
        return {t: ["client_id"] for t in FALLBACK_TABLES}
    out = {}
    for table, d in sorted(defs.items()):
        cols = list((d.get("properties") or {}).keys())
        if "client_id" in cols and table not in SKIP_TABLES and not table.startswith("v_"):
            out[table] = cols
    return out


def gather(db: Any, client_id: str) -> Dict[str, Any]:
    """The client's row, its rows on every table with a client_id, and team names."""
    client = db.get("clients", client_id) or {}
    team = {t["id"]: t.get("full_name") for t in db.select_all("team", columns="id,full_name")}
    settings = db.get("settings", "1") or {}
    tables: Dict[str, Any] = {}
    for table, cols in client_tables(db).items():
        order = "changed_at.desc" if table == "stage_log" else ("created_at.desc" if "created_at" in cols else None)
        try:
            rows = db.select_all(table, {"client_id": "eq." + client_id}, order=order or "id")
        except SupabaseError as e:
            tables[table] = {"error": str(e)[:200], "rows": []}
            continue
        tables[table] = {"columns": cols, "rows": rows}
    return {"client": client, "team": team, "settings": settings, "tables": tables}


# --------------------------------------------------------------------------- the report


def os_link(settings: Dict[str, Any], path: str) -> str:
    base = (settings.get("os_url") or "").strip().rstrip("/")
    if base and not base.startswith("http"):
        base = "https://" + base
    return base + path if base else ""


def label_row(row: Dict[str, Any]) -> str:
    for key in sorted(row):
        if (
            re.search(r"(_name|_title|^title)$", key)
            and not key.endswith("_by_name")
            and key != "client_name"
            and row[key]
        ):
            return str(row[key])
    for key in ("metric_date", "week_start", "call_at", "submitted_at", "changed_at", "created_at"):
        if row.get(key):
            return str(row[key])[:10]
    return str(row.get("id", ""))[:8]


def describe(row: Dict[str, Any], team: Dict[str, str], table: str) -> str:
    """One readable line for one row. Pure."""
    if table == "stage_log":
        return "{0} {1}: {2} → {3}{4}".format(
            str(row.get("changed_at", ""))[:16].replace("T", " "),
            row.get("record_name") or row.get("board"),
            row.get("from_stage") or "new",
            row.get("to_stage"),
            " ({0})".format(team[row["changed_by_id"]]) if row.get("changed_by_id") in team else "",
        )
    bits = [label_row(row)]
    if row.get("stage"):
        bits.append(str(row["stage"]))
    for key in sorted(row):
        if key.endswith("_id") and key not in ("id", "client_id") and row[key] in team:
            bits.append("{0}: {1}".format(key[:-3].replace("_", " "), team[row[key]]))
    if row.get("due_date"):
        bits.append("due " + str(row["due_date"])[:10])
    if row.get("is_example"):
        bits.append("example row")
    return " · ".join(bits)


def report(match: Dict[str, Any], data: Optional[Dict[str, Any]], full: bool, note: str = "") -> str:
    lines: List[str] = []
    row = (data or {}).get("client") or match.get("row") or {}
    folder = match.get("folder")
    title = row.get("client_name") or (
        folder["names"][1] if folder and len(folder["names"]) > 1 else folder and folder["folder"]
    )
    lines.append("# {0}".format(title))
    lines.append("Found by: {0}.".format(match["why"]))
    if data:
        team, settings = data["team"], data["settings"]
        link = os_link(settings, "/clients/" + row["id"]) if row.get("id") else ""
        lines.append("")
        lines.append("## In the OS" + (" ({0})".format(link) if link else ""))
        for key in (
            "status",
            "onboarding_stage",
            "contact_name",
            "contact_email",
            "website",
            "start_date",
            "slack_channel_name",
            "drive_folder_url",
        ):
            if row.get(key):
                value = str(row[key])[:10] if key.endswith("_date") else row[key]
                lines.append("- {0}: {1}".format(key.replace("_", " "), value))
        for key in sorted(row):
            if key.endswith("_id") and row[key] in team:
                lines.append("- {0}: {1}".format(key[:-3].replace("_", " "), team[row[key]]))
        if full:
            lines.append("- every column: " + json.dumps(row, default=str))
        for table, t in data["tables"].items():
            rows = t["rows"]
            if t.get("error"):
                lines += ["", "## {0}: could not read ({1})".format(table, t["error"])]
                continue
            if not rows:
                continue
            lines += ["", "## {0} ({1})".format(table.replace("_", " ").capitalize(), len(rows))]
            for r in rows[: (len(rows) if full else SHOW_ROWS)]:
                text = describe(r, team, table)
                if "stage" in t.get("columns", []) and r.get("id"):
                    card = os_link(settings, "/board/{0}/{1}".format(table, r["id"]))
                    text += " · " + card if card else ""
                lines.append("- " + text)
                if full:
                    lines.append("  " + json.dumps(r, default=str))
            if not full and len(rows) > SHOW_ROWS:
                lines.append("- …and {0} more. Run again with --full to see them all.".format(len(rows) - SHOW_ROWS))
    elif note:
        lines += ["", "## In the OS", "- Not read: {0}.".format(note)]
    elif not row:
        lines += ["", "## In the OS", "- No client row in the database matches this notes folder."]
    lines.append("")
    if folder:
        lines.append("## Notes ({0}/)".format(folder["path"]))
        for f in folder["files"]:
            lines.append("- " + f)
        if folder["people"]:
            lines.append("- people named in about.md: " + ", ".join(folder["people"]))
    else:
        lines.append("## Notes")
        lines.append("- No clients/ folder for this client. The create-client skill makes one.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- main


def connect(files_only: bool) -> Tuple[Optional[Any], str]:
    if files_only:
        return None, "the database was skipped (--files-only)"
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SECRET_KEY"):
        return None, "the database was skipped: SUPABASE_URL or SUPABASE_SECRET_KEY is empty in .env"
    return Supabase(), ""


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Find everything about one client.")
    ap.add_argument("query", nargs="?", default="", help="The client's name, or part of it")
    ap.add_argument("--email", default="", help="An email of someone at the client")
    ap.add_argument("--id", default="", help="The client's row id in the database")
    ap.add_argument("--full", action="store_true", help="Every column of every row")
    ap.add_argument("--json", action="store_true", help="Print JSON instead of text")
    ap.add_argument("--files-only", action="store_true", help="Search only the clients/ folders")
    args = ap.parse_args(argv)
    if not (args.query or args.email or args.id):
        ap.error("give a name, --email or --id")
    load_dotenv(str(REPO / ".env"))
    db, note = connect(args.files_only)
    folders = all_folders()
    rows: List[Dict[str, Any]] = []
    if db is not None:
        try:
            filters = {"id": "eq." + args.id} if args.id else None
            rows = db.select_all(
                "clients", filters, columns="id,client_name,contact_email,website,status", order="client_name"
            )
        except SupabaseError as e:
            db, note = None, "the database could not be read ({0})".format(str(e)[:120])
    if args.id:
        matches, kind = (
            [{"row": r, "folder": None, "why": "same id", "sure": True} for r in rows],
            "sure" if rows else "none",
        )
        for m in matches:
            m["folder"] = next(
                (f for f in folders if norm(m["row"]["client_name"]) in {norm(n) for n in f["names"]}), None
            )
    else:
        matches, kind = find(args.query, args.email, rows, folders)

    if args.json:
        out: Dict[str, Any] = {"match": kind, "note": note, "candidates": []}
        for m in matches:
            c = {
                "why": m["why"],
                "sure": m["sure"],
                "client": m.get("row"),
                "folder": m["folder"] and {k: (sorted(v) if isinstance(v, set) else v) for k, v in m["folder"].items()},
            }
            if len(matches) == 1 and db is not None and m.get("row"):
                c["data"] = gather(db, m["row"]["id"])
            out["candidates"].append(c)
        print(json.dumps(out, indent=2, default=str))
        return 0 if kind != "none" else 1

    if note:
        print("Note: {0}.".format(note))
    if kind == "none":
        print("No client matches. Try part of the name, an email, or check the spelling.")
        return 1
    if len(matches) > 1:
        print(
            "{0} clients could be this one. Pick one and search again with its full name or --id:".format(len(matches))
        )
        for m in matches:
            r, f = m.get("row") or {}, m.get("folder")
            print(
                "- {0}{1}{2}: {3}".format(
                    r.get("client_name") or (f and f["folder"]),
                    " (id {0})".format(r["id"]) if r.get("id") else "",
                    " · clients/{0}/".format(f["folder"]) if f else "",
                    m["why"],
                )
            )
        return 2
    m = matches[0]
    data = gather(db, m["row"]["id"]) if db is not None and m.get("row") else None
    print(report(m, data, args.full, note))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
