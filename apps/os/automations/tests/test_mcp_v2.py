"""The connector, version 2: one name (id) for every get and read, skills and the second brain with
roles, and the database actions that run as the caller (row level security), never as the server.

The skills here are two stand-ins in a temp folder, in the format Milo's skills/ use
(skills/<fulfilment|owner|global>/<name>/SKILL.md with name, description, area, agency, needs,
runs_on), plus one made for another agency type, which must stay hidden.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from test_mcp import SPEC, TOKENS, make, note, ok, read

import mcp_actions
from mcp_actions import ALL, frontmatter
from mcp_server import NO_PUBLISHABLE, Sessions
from shared.supabase_client import Supabase, SupabaseError

# --------------------------------------------------------------------------- one name: id


def test_every_get_and_read_action_takes_id():
    for name, entry in ALL.items():
        if name.endswith((".get", ".read")):
            assert "id" in entry["schema"]["properties"], name
    assert ALL["docs.read"]["aliases"] == {"document": "id"}  # the old name, kept for one release
    assert ALL["brain.read"]["aliases"] == {"note": "id"} and ALL["clients.get"]["aliases"] == {"client": "id"}


def test_the_old_names_still_work_and_two_different_values_are_refused(brain):
    db, mcp = make()
    by_id = ok(read(mcp, "brain.read", {"id": "Discovery_Call"}))
    assert ok(read(mcp, "brain.read", {"note": "Discovery_Call"})) == by_id
    assert ok(read(mcp, "brain.read", {"id": "Discovery_Call", "note": "Discovery_Call"})) == by_id
    res = read(mcp, "brain.read", {"id": "Discovery_Call", "note": "Price_Objection"})
    assert res["ok"] is False and "'note' is the old name of 'id'" in res["error"]
    assert ok(read(mcp, "clients.get", {"id": "Example Client A"}))["client"]["client_name"] == "Example Client A"
    assert ok(read(mcp, "clients.get", {"client": "Example Client A"}))["client"]["client_name"] == "Example Client A"
    assert "needs id" in read(mcp, "clients.get", {})["error"]


@pytest.fixture
def brain(tmp_path, monkeypatch):
    root = tmp_path / "second-brain"
    note(root, "INDEX.md", "# Second brain: INDEX\n")
    note(root, "sales/sales_map.md", "# Sales map\n")
    note(root, "sales/Discovery_Call.md", "# Discovery call\nAsk about the budget.\n")
    note(root, "sales/Price_Objection.md", "# Price objection\nprice budget\n")
    note(root, "delivery/delivery_map.md", "# Delivery map\n")
    note(root, "delivery/Unhappy_Client.md", "# Unhappy client\n")
    note(root, "raw/2026-10-01_call.md", "word for word\n")
    monkeypatch.setattr(mcp_actions, "BRAIN_DIRS", [root])
    return root


def test_brain_list_gives_every_note_and_one_area(brain):
    db, mcp = make()
    out = ok(read(mcp, "brain.list"))
    ids = [n["id"] for n in out["rows"]]
    assert set(ids) == {"Discovery_Call", "Price_Objection", "Unhappy_Client", "sales_map", "delivery_map"}
    assert "2026-10-01_call" not in ids and out["next_page"] is None  # raw/ is never listed
    assert {n["id"] for n in ok(read(mcp, "brain.list", {"area": "delivery"}))["rows"]} == {
        "Unhappy_Client",
        "delivery_map",
    }
    assert "No notes in an area" in read(mcp, "brain.list", {"area": "hiring"})["error"]
    assert ok(read(mcp, "brain.read", {"id": out["rows"][0]["id"]}))  # an id from the list reads


# --------------------------------------------------------------------------- skills


def skill(root, area, name, agency="all", runs_on="either", needs="[]", body="# Steps\n1. Do it.\n", files=None):
    folder = root / area / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: {0}\ndescription: {0} does one thing. Use when asked.\narea: {1}\nagency: {2}\n"
        "needs: {3}\nruns_on: {4}\n---\n\n{5}".format(name, area, agency, needs, runs_on, body)
    )
    for rel, text in (files or {}).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text)
    return folder


@pytest.fixture
def skills(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    skill(root, "fulfilment", "write-copy", runs_on="local", needs="[SUPABASE_URL, SUPABASE_SECRET_KEY]",
          files={"scripts/run.py": "print('copy')\n", "references/tone.md": "Plain words.\n", "logo.png": "x",
                 ".env": "SECRET=1\n"})  # fmt: skip
    skill(root, "owner", "close-deal", runs_on="modal")
    skill(root, "global", "for-another-type", agency="some-other-type")
    skill(root, "global", "for-this-type", agency="[{0}, some-other-type]".format(SPEC["agency_type"]))
    monkeypatch.setattr(mcp_actions, "SKILL_DIRS", [root])
    return root


def test_the_frontmatter_reader():
    meta, body = frontmatter("---\nname: a\nneeds: [X, 'Y']\nagency:\n  - ads\n  - content\n---\n\n# Body\n")
    assert meta == {"name": "a", "needs": ["X", "Y"], "agency": ["ads", "content"]} and body == "# Body\n"
    assert frontmatter("# No block\n") == ({}, "# No block\n")
    assert frontmatter("---\nname: never closed\n") == ({}, "---\nname: never closed\n")


def test_a_member_sees_fulfilment_and_global_skills_but_not_owner_skills(skills):
    db, mcp = make()
    member = ok(read(mcp, "skills.list"))
    assert [s["id"] for s in member["skills"]] == ["fulfilment/write-copy", "global/for-this-type"]  # fulfilment, then global
    assert "Owner skills" in member["note"]
    owner = ok(read(mcp, "skills.list", token="owner-token"))
    assert [s["id"] for s in owner["skills"]] == ["owner/close-deal", "fulfilment/write-copy", "global/for-this-type"] and "note" not in owner
    assert [s["id"] for s in ok(read(mcp, "skills.list", {"area": "owner"}, token="admin-token"))["skills"]] == [
        "owner/close-deal"
    ]
    assert ok(read(mcp, "skills.list", {"area": "owner"}))["skills"] == []  # a Member: none, and no names
    assert "No skill area" in read(mcp, "skills.list", {"area": "sales"})["error"]
    wc = member["skills"][0]
    assert wc["runs_on"] == "local" and wc["needs"] == ["SUPABASE_URL", "SUPABASE_SECRET_KEY"]


def test_skills_read_by_role(skills):
    db, mcp = make()
    out = ok(read(mcp, "skills.read", {"id": "write-copy"}))
    assert out["text"].startswith("# Steps") and "---" not in out["text"]
    assert out["files"] == ["SKILL.md", "logo.png", "references/tone.md", "scripts/run.py"]  # never .env
    assert "SUPABASE_SECRET_KEY" in out["needs_note"] and "own computer" in out["how_to_run"]
    assert ok(read(mcp, "skills.read", {"id": "fulfilment/write-copy"}))["id"] == "fulfilment/write-copy"
    assert out["id"] == "fulfilment/write-copy" and out["name"] == "write-copy"  # an id from the list reads
    script = ok(read(mcp, "skills.read", {"id": "write-copy", "file": "scripts/run.py"}))
    assert script["text"] == "print('copy')\n" and script["file"] == "scripts/run.py"
    for bad in ("../owner/close-deal/SKILL.md", ".env", "/etc/passwd", "scripts/nope.py"):
        assert read(mcp, "skills.read", {"id": "write-copy", "file": bad})["ok"] is False, bad
    assert "not a text file" in read(mcp, "skills.read", {"id": "write-copy", "file": "logo.png"})["error"]

    refused = read(mcp, "skills.read", {"id": "close-deal"})
    assert refused["ok"] is False and "for Owners and Admins only; you are a Member" in refused["error"]
    assert ok(read(mcp, "skills.read", {"id": "close-deal"}, token="admin-token"))["how_to_run"].startswith(
        "It runs on the automations app"
    )
    assert "No skill called" in read(mcp, "skills.read", {"id": "for-another-type"}, token="owner-token")["error"]
    last = db.tables["mcp_audit"][-1]
    assert last["action"] == "skills.read" and last["ok"] is False


def test_no_skills_folder_is_a_plain_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_actions, "SKILL_DIRS", [tmp_path / "none"])
    db, mcp = make()
    out = ok(read(mcp, "skills.list"))
    assert out["skills"] == [] and "No skills yet" in out["message"]


# --------------------------------------------------------------------------- the database, as the caller


class CallerDB(Supabase):
    """The database as one signed-in person, with two of the real rules (proven on the real
    database in tools/sqltest/run.mjs): a Member's change to the settings matches no row, with no
    error ("a Member cannot change the settings"), and a Member's archive is an error ("a Member
    cannot archive a client by changing archived_at"). Every call is recorded."""

    def __init__(self, world, me):
        super().__init__("https://db.example.com", "publishable-key", bearer="session-for-" + me["email"])
        self.world, self.me, self.calls = world, me, []

    def select(self, table, filters=None, columns="*", order=None, limit=None, offset=None):
        self.calls.append(("GET", table, dict(filters or {})))
        if table == "mcp_audit" and self.me["access"] == "Member":
            return []  # admin_read: a Member sees no row
        return self.world.select(table, filters, columns, order, limit, offset)

    def request(self, method, path, params=None, body=None, prefer=None):
        self.calls.append((method, path, dict(params or {})))
        member = self.me["access"] == "Member"
        if method == "PATCH":
            if member and path == "settings":
                return []
            if member and "archived_at" in (body or {}):
                raise SupabaseError(
                    'PATCH {0} failed (400): {{"code":"42501","message":"Only an Owner or Admin can archive or restore."}}'.format(path)
                )  # fmt: skip
            row_id = (params or {}).get("id", "").partition(".")[2]
            hit = [r for r in self.world.tables.get(path, []) if str(r.get("id")) == row_id]
            if not hit:
                return []
            hit[0].update(body)
            return [dict(hit[0])]
        if method == "POST":
            if member and path == "team":
                raise SupabaseError(
                    'POST team failed (403): {"code":"42501","message":"new row violates row-level security policy for table \\"team\\""}'
                )  # fmt: skip
            return [self.world.insert(path, body)]
        raise AssertionError("no " + method)


def caller_world():
    db, mcp = make()
    made = {}

    def as_me(me):
        made.setdefault(me["id"], CallerDB(db, me))
        return made[me["id"]]

    mcp.sessions = type("S", (), {"db_for": staticmethod(as_me)})()
    return db, mcp, made


def write(mcp, params, token="member-token"):
    return mcp.run("write", token, "db.write", params)


def test_a_member_cannot_write_what_the_database_rules_block():
    db, mcp, made = caller_world()
    before = json.dumps(db.tables["settings"])
    res = write(mcp, {"table": "settings", "id": str(db.tables["settings"][0].get("id", 1)), "fields": {"agency_name": "Mine"}})
    assert res["ok"] is False and res["error"].startswith("Refused: the database's rules did not let you change row")
    assert json.dumps(db.tables["settings"]) == before  # nothing changed
    res = write(mcp, {"table": "clients", "id": "c-1", "fields": {"archived_at": "2026-11-11T00:00:00Z"}})
    assert res["ok"] is False and "Refused by the database's rules" in res["error"] and "Only an Owner or Admin" in res["error"]
    res = write(mcp, {"table": "team", "fields": {"full_name": "New", "email": "new@example.com"}})
    assert res["ok"] is False and "may not add a row to team" in res["error"]
    assert set(made) == {"t-maker"}  # every call ran as the Member
    assert not [u for u in db.updates if u[0] != "team" or set(u[2]) != {"mcp_last_seen_at"}]  # the server's key
    assert not [i for i in db.inserts if i[0] != "mcp_audit"]  # wrote nothing but its own log and "last seen"
    assert [a["ok"] for a in db.tables["mcp_audit"]] == [False, False, False]


def test_what_the_rules_allow_is_written_and_read_back():
    db, mcp, made = caller_world()
    out = ok(write(mcp, {"table": "clients", "id": "c-1", "fields": {"notes": "Called them."}}))
    assert out["changed"] and out["row"]["notes"] == "Called them."
    assert ok(mcp.run("read", "member-token", "db.read", {"table": "clients", "id": "c-1"}))["row"]["notes"] == "Called them."
    owner = ok(write(mcp, {"table": "settings", "id": "1", "fields": {"agency_name": "Ours"}}, token="owner-token"))
    assert owner["changed"] if db.tables["settings"][0].get("id") is not None else True
    assert set(made) == {"t-maker", "t-owner"}  # the Owner wrote as the Owner, not as the server


def test_db_read_filters_pages_and_checks_names():
    db, mcp, made = caller_world()
    rows = ok(mcp.run("read", "member-token", "db.read", {"table": "tasks", "filters": {"stage": "10 - In Progress"}}))
    assert {r["id"] for r in rows["rows"]} == {"k1", "k3"} and rows["next_page"] is None
    assert made["t-maker"].calls[-1] == ("GET", "tasks", {"stage": "eq.10 - In Progress"})
    ok(mcp.run("read", "member-token", "db.read", {"table": "tasks", "filters": {"due_date": "lt.2026-11-01", "notes": None}}))
    assert made["t-maker"].calls[-1][2] == {"due_date": "lt.2026-11-01", "notes": "is.null"}
    for bad in ({"table": "tasks; drop"}, {"table": "tasks", "columns": "id,(select)"}, {"table": "tasks", "filters": {"a b": 1}}):
        assert "is not a table or column name" in mcp.run("read", "member-token", "db.read", bad)["error"]
    assert ok(mcp.run("read", "member-token", "db.read", {"table": "mcp_audit"}))["rows"] == []  # the rules hide it
    res = mcp.run("read", "member-token", "db.read", {"table": "tasks", "id": "nope"})
    assert res["ok"] is False and "that you may see" in res["error"]
    assert mcp.run("read", "member-token", "db.write", {"table": "tasks", "fields": {"x": 1}})["error"].endswith(
        "so run it with run_write_action."
    )


# --------------------------------------------------------------------------- the sign-in per person


def test_sessions_sign_in_once_an_hour_with_the_publishable_key():
    signed, now = [], [1000.0]

    def sign_in(email, url, secret):
        signed.append((email, url, secret))
        return {"access_token": "at-{0}".format(len(signed)), "expires_in": 3600}

    s = Sessions("https://db.example.com", "secret", "publishable", clock=lambda: now[0], sign_in=sign_in)
    db = s.db_for({"email": "Max@Example.com"})
    assert db.key == "publishable" and db.bearer == "at-1"
    assert signed == [("max@example.com", "https://db.example.com", "secret")]
    now[0] += 3000
    assert s.db_for({"email": "max@example.com"}) is db and len(signed) == 1  # kept
    now[0] += 400  # five minutes before the hour runs out
    assert s.db_for({"email": "max@example.com"}).bearer == "at-2"
    with pytest.raises(mcp_actions.ActionError) as e:
        Sessions("u", "s", "", sign_in=sign_in).db_for({"email": "max@example.com"})
    assert str(e.value) == NO_PUBLISHABLE


class Stub(BaseHTTPRequestHandler):
    """A stand-in Supabase on this computer: Auth (generate_link, verify) and the Data API.
    It records every request's path and keys, so the test sees which key each call used."""

    seen: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        self._answer()

    def do_PATCH(self):
        self._answer()

    def _answer(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        Stub.seen.append((self.command, self.path, self.headers.get("apikey"), self.headers.get("Authorization"), body))
        if self.path == "/auth/v1/admin/generate_link":
            out = {"id": "u1", "email": body["email"], "hashed_token": "hash-1", "verification_type": "magiclink"}
        elif self.path == "/auth/v1/verify":
            out = {"access_token": "user-jwt", "token_type": "bearer", "expires_in": 3600, "refresh_token": "r"}
        elif self.path.startswith("/rest/v1/settings"):
            out = []  # what the real rules answer a Member: no row matched
        else:
            out = {}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_the_real_sign_in_and_data_calls_use_the_person_never_the_secret_key():
    """The real code over real HTTP, against the stand-in: the sign-in calls use the secret key,
    and every data call carries the publishable key and the person's own token."""
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:{0}".format(server.server_port)
    Stub.seen = []
    try:
        db, mcp = make()
        mcp.sessions = Sessions(url, "sb_secret_test", "sb_publishable_test")
        res = mcp.run("write", TOKENS["t-maker"], "db.write", {"table": "settings", "id": "1", "fields": {"agency_name": "x"}})
    finally:
        server.shutdown()
    assert res["ok"] is False and "did not let you change row 1 in settings" in res["error"]
    link, verify, patch = Stub.seen
    assert link[:4] == ("POST", "/auth/v1/admin/generate_link", "sb_secret_test", "Bearer sb_secret_test")
    assert link[4] == {"type": "magiclink", "email": "max@example.com"}
    assert verify[1] == "/auth/v1/verify" and verify[4] == {"type": "magiclink", "token_hash": "hash-1"}
    assert patch[:4] == ("PATCH", "/rest/v1/settings?id=eq.1", "sb_publishable_test", "Bearer user-jwt")
    assert patch[4] == {"agency_name": "x"}
    assert "sb_secret_test" not in json.dumps(db.tables["mcp_audit"])


def test_metrics_get_reads_one_row_by_id():
    db, mcp = make(weekly_metrics=[{"id": "w1", "client_id": "c-1", "week_start": "2026-11-02"}])
    out = ok(read(mcp, "metrics.get", {"id": "w1"}))
    assert out["row"]["week_start"] == "2026-11-02" and out["client"] == "Example Client A"
    assert "No weekly numbers row" in read(mcp, "metrics.get", {"id": "nope"})["error"]
    assert "Give a client" in read(mcp, "metrics.get", {})["error"]


def test_tab_5_has_no_show_me_the_post_and_names_the_revoke_row():
    from fakes import AUTOMATIONS

    tab5 = (AUTOMATIONS.parents[2] / "docs" / "5-mcp.md").read_text()
    assert "show me the post" not in tab5.lower() and "Slack alert is in the right channel" not in tab5
    assert "Open Slack, channel" in tab5 and "You should see" in tab5
    assert "the top row is `revoked`" in tab5
    assert "upgrade" not in tab5.lower() and "pay" not in tab5.lower().replace("paste", "")


def test_a_live_card_stays_on_my_queue_but_is_never_late_or_stuck():
    from test_mcp import ago, day, open_card

    live = open_card("running", due_date=day(-10), stage_changed_at=ago(40), is_live=True)
    late = open_card("late", due_date=day(-1))
    db, mcp = make(v_open_cards=[live, late])
    rows = ok(read(mcp, "my_queue"))["rows"]
    assert [r["id"] for r in rows] == ["late", "running"]
    assert rows[1]["why"] == "live" and "late" not in rows[1]["why"] and "no move" not in rows[1]["why"]


def test_a_card_off_my_work_stays_on_its_board_but_not_on_my_queue():
    """0023: v_open_cards.on_my_work is false for a flow at '60 - Live'. My Work leaves it out."""
    from test_mcp import open_card

    off = open_card("live-flow", on_my_work=False)
    db, mcp = make(v_open_cards=[off, open_card("normal")])
    assert [r["id"] for r in ok(read(mcp, "my_queue"))["rows"]] == ["normal"]
    asked = [r for r in db.reads if r.get("table") == "v_open_cards"]
    assert asked and all(r["filters"].get("on_my_work") == "eq.true" for r in asked[-2:])
    assert "live-flow" in [r["id"] for r in ok(read(mcp, "urgent", token="owner-token"))["rows"]]  # still an open card
