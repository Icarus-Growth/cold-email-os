"""Copy documents in the AI connector (contract 0013): docs.read, docs.write, the version
conflict, who may write what, the audit rows, and the previews in cards.get and clients.get."""

import re

import pytest
from fakes import AUTOMATIONS
from test_mcp import CFG, SPEC, ago, make, ok

from mcp_actions import DOC_PREVIEW, word_count

DOC_BOARD = next((b for b, s in SPEC["boards"].items() if s.get("documents")), None)
CLIENT_DOCS = SPEC.get("client_documents", {})
CFG_DOCS = AUTOMATIONS.parents[2] / "docs"
pytestmark = pytest.mark.skipif(DOC_BOARD is None, reason="this agency type has no card documents")


def with_card(**extra):
    spec = SPEC["boards"][DOC_BOARD]
    card = {"id": "d1", spec["name"]: "Launch copy", "client_id": "c-1", "stage": spec["stages"][1]}
    card.update(extra)
    return make(**{DOC_BOARD: [card]})


def field():
    return next(iter(SPEC["boards"][DOC_BOARD]["documents"]))


def where(**more):
    out = {"board": DOC_BOARD, "card": "d1", "field": field()}
    out.update(more)
    return out


def write(mcp, token, params):
    return mcp.run("write", token, "docs.write", params)


def test_the_app_and_the_connector_count_words_the_same_way():
    # The app: plain text split on spaces, parts with a letter or a digit. A merge field is one word.
    assert word_count("# Hi {{firstName}},\n\n- see [our offer](https://x.com/a b) now.\n- 3 — ok") == 8
    assert word_count("") == 0 and word_count("--- ** ##") == 0


def test_a_new_document_reads_as_empty_then_saves_with_version_0():
    db, mcp = with_card()
    first = ok(mcp.run("read", "member-token", "docs.read", where()))
    assert first["version"] == 0 and first["word_count"] == 0 and "version 0" in first["note"]
    assert "documents" not in db.tables or db.tables["documents"] == []  # a read never makes a row
    saved = ok(write(mcp, "member-token", where(body_md="Hello there, friend.", version=0)))
    assert saved["saved"] and saved["word_count"] == 3 and saved["version"] == 2
    doc = db.tables["documents"][0]
    assert doc["updated_by"] == "t-maker" and doc["body_md"] == "Hello there, friend."
    got = ok(mcp.run("read", "owner-token", "docs.read", {"document": doc["id"]}))
    assert got["body_md"] == "Hello there, friend." and got["updated_by"] == "Max Maker" and got["version"] == 2
    assert [name for name, _ in db.rpcs] == ["open_document", "save_document"]
    assert db.rpcs[1][1]["p_saved_by"] == "t-maker" and db.rpcs[1][1]["p_word_count"] == 3


def test_a_stale_version_is_a_conflict_and_saves_nothing():
    db, mcp = with_card()
    ok(write(mcp, "member-token", where(body_md="First text.", version=0)))
    ok(write(mcp, "owner-token", where(body_md="Owner's text.", version=2)))
    res = write(mcp, "member-token", where(body_md="My late change.", version=2))
    assert res["ok"] is False
    assert "Someone else changed this document" in res["error"] and "version 3" in res["error"]
    assert db.tables["documents"][0]["body_md"] == "Owner's text."
    # Two people starting the same new document: the second is a conflict too.
    res = write(mcp, "member-token", where(body_md="Also new.", version=0))
    assert res["ok"] is False and "docs.read" in res["error"]


def test_bad_names_and_sizes_get_plain_answers():
    db, mcp = with_card()
    res = mcp.run("read", "member-token", "docs.read", where(field="nope"))
    assert res["ok"] is False and "'{0}'".format(field()) in res["error"]
    res = mcp.run("read", "member-token", "docs.read", {"board": DOC_BOARD, "field": field()})
    assert res["ok"] is False and "card" in res["error"]
    res = write(mcp, "member-token", where(body_md="x" * 500001, version=0))
    assert res["ok"] is False and "500 000 bytes" in res["error"]
    res = write(mcp, "member-token", where(body_md="x", version=4))
    assert res["ok"] is False and "version 0" in res["error"]
    label = SPEC["boards"][DOC_BOARD]["documents"][field()]["label"]
    assert ok(mcp.run("read", "member-token", "docs.read", where(field=label.upper())))["field"] == field()


def test_an_archived_card_can_be_read_but_not_written():
    db, mcp = with_card(archived_at=ago(1))
    assert ok(mcp.run("read", "member-token", "docs.read", where()))["archived"] is True
    res = write(mcp, "member-token", where(body_md="x", version=0))
    assert res["ok"] is False and "archived" in res["error"]


@pytest.mark.skipif(not CLIENT_DOCS, reason="this agency type has no client page documents")
def test_client_page_documents_are_read_by_all_and_written_by_owners_and_admins():
    db, mcp = make()
    key = next(iter(CLIENT_DOCS))
    params = {"client": "Example Client A", "field": key}
    assert ok(mcp.run("read", "member-token", "docs.read", params))["version"] == 0
    res = write(mcp, "member-token", dict(params, body_md="Member text", version=0))
    assert res["ok"] is False and "Owners and Admins only" in res["error"] and "Member" in res["error"]
    assert db.rpcs == []
    saved = ok(write(mcp, "admin-token", dict(params, body_md="Admin text", version=0)))
    doc = db.tables["documents"][0]
    assert doc["board"] is None and doc["card_id"] is None and doc["updated_by"] == "t-am"
    assert saved["link"].startswith("https://os.example.com/")
    shown = ok(mcp.run("read", "member-token", "clients.get", {"client": "Example Client A"}))["documents"]
    assert {d["field"] for d in shown} == set(CLIENT_DOCS)
    assert next(d for d in shown if d["field"] == key)["preview"] == "Admin text"


def test_cards_get_shows_each_document_preview_and_word_count():
    db, mcp = with_card()
    long_text = "word " * 200
    ok(write(mcp, "member-token", where(body_md=long_text, version=0)))
    docs = ok(mcp.run("read", "member-token", "cards.get", {"board": DOC_BOARD, "id": "d1"}))["documents"]
    assert {d["field"] for d in docs} == set(SPEC["boards"][DOC_BOARD]["documents"])
    mine = next(d for d in docs if d["field"] == field())
    assert mine["word_count"] == 200 and mine["preview"] == long_text[:DOC_PREVIEW] + "..."
    assert "body_md" not in mine and mine["document"] == db.tables["documents"][0]["id"]


def test_every_document_call_is_in_the_audit_log():
    db, mcp = with_card()
    mcp.run("read", "member-token", "docs.read", where())
    mcp.run("write", "member-token", "docs.write", where(body_md="One.", version=0))
    mcp.run("write", "member-token", "docs.write", where(body_md="Two.", version=0))  # conflict
    mcp.run("read", "member-token", "docs.write", where(body_md="Three.", version=2))  # wrong tool
    rows = [(a["action"], a["ok"]) for a in db.tables["mcp_audit"]]
    assert rows == [("docs.read", True), ("docs.write", True), ("docs.write", False), ("docs.write", False)]
    assert all(a["team_id"] == "t-maker" for a in db.tables["mcp_audit"])


def test_each_document_names_a_real_link_column_and_boards_lists_them():
    client_fields = SPEC["client_fields"]
    for key, spec in SPEC["boards"].items():
        for name, doc in spec.get("documents", {}).items():
            assert doc["label"] and (doc.get("link") is None or doc["link"] in spec["fields"]), (key, name)
    for name, doc in CLIENT_DOCS.items():
        assert doc["label"] and doc["link"] in client_fields, name
    db, mcp = make()
    out = ok(mcp.run("read", "member-token", "boards", {}))
    assert next(b for b in out["boards"] if b["board"] == DOC_BOARD)["documents"] == sorted(
        SPEC["boards"][DOC_BOARD]["documents"]
    )
    assert out["client_page_documents"] == sorted(CLIENT_DOCS)
    assert CFG.boards.get(DOC_BOARD)


def test_tab_5_names_every_action_and_the_document_check():
    tab5 = (CFG_DOCS / "5-mcp.md").read_text()
    for name in SPEC["actions"]:
        assert "`{0}`".format(name) in tab5, name
    assert "docs.read" in tab5 and "with the version it read" in tab5 and "public.documents" in tab5


def test_the_document_fields_match_the_database_list():
    """0014 fills document_fields for the app, and later migrations add to it (ads 0017: the
    campaign brief). mcp_actions.json must name the same fields."""
    from fakes import MIGRATIONS

    files = sorted(MIGRATIONS.glob("*document_fields.sql"))
    if not files:
        pytest.skip("0014 is not in this copy yet")
    row = re.compile(r"\(\s*(null|'[a-z_]+')\s*,\s*'([a-z_]+)'\s*,\s*'([^']*)'\s*,\s*(null|'[a-z_]+')\s*\)")
    block = re.compile(r"insert\s+into\s+(?:public\.)?document_fields\b.*?;", re.I | re.S)
    found = {}
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.name < files[-1].name:
            continue
        sql = re.sub(r"--[^\n]*", "", f.read_text())
        for b in block.findall(sql) if f != files[-1] else [sql]:
            for board, key, label, link in row.findall(b):
                board = board.strip("'") if board != "null" else None
                found[(board, key)] = (label, link.strip("'") if link != "null" else None)
    db_list = {(b, k, label, c) for (b, k), (label, c) in found.items()}
    ours = {(b, k, d["label"], d.get("link")) for b, s in SPEC["boards"].items() for k, d in s.get("documents", {}).items()}
    ours |= {(None, k, d["label"], d.get("link")) for k, d in CLIENT_DOCS.items()}
    assert db_list and ours == db_list
