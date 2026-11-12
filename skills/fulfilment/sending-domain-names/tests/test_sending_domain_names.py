"""Tests for sending-domain-names: fake example data, no network."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
for _up in HERE.parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
sys.path.insert(0, str(HERE.parents[1] / "scripts"))

import pytest  # noqa: E402
from skill_fakes import FakeDB  # noqa: E402

import propose_domains  # noqa: E402
import sending_http as http  # noqa: E402
import sending_naming as naming  # noqa: E402
from sending_registrars import Porkbun, Registrar  # noqa: E402


class FakeRegistrar(Registrar):
    name = "porkbun"

    def __init__(self, taken=(), prices=None):
        self.taken, self.prices, self.asked = set(taken), prices or {}, []

    def check_many(self, names):
        self.asked += names
        return {n: naming.Availability(n not in self.taken, self.prices.get(n, 11.0),
                                       reason=None if n not in self.taken else "already registered") for n in names}

    def owned(self):
        return {"oldagencyname.com"}


def db_with_client(**extra):
    client = dict({"id": "c1", "client_name": "Acme Dental", "website": "https://www.acmedental.com/about",
                   "contact_email": "jane@example.com", "sending_domains": "acmedentalhq.com"}, **extra)
    return FakeDB({"clients": [client], "sending_domains": [{"id": "d0", "domain": "goacmedental.com"}]})


def test_brand_names_in_tier_order_and_never_the_main_domain():
    cfg = naming.load_config()
    reg = FakeRegistrar(taken={"myacmedental.com"})
    db = db_with_client()
    out = propose_domains.propose_for(db, "Acme Dental", count=4, cfg=cfg, registrar=reg)
    names = [d["domain"] for d in out["domains"]]
    # goacmedental.com is used by another plan; myacmedental.com is taken at the registrar.
    assert names == ["getacmedental.com", "tryacmedental.com", "useacmedental.com", "heyacmedental.com"]
    assert "acmedental.com" not in names and "acmedental.com" not in reg.asked
    assert all(d["tier"] == 1 and d["price"] == 11.0 for d in out["domains"])
    assert out["main_domain"] == "acmedental.com"
    assert db.writes == []  # read only


def test_rules_block_bad_words_banned_parts_and_bad_endings():
    cfg = naming.load_config()
    assert naming.screen("therapistlab", ".com", cfg) == "has the blocked word 'rapist'"
    assert naming.screen("skillhub", ".com", cfg) is None  # "kill" inside "skill" is fine
    assert naming.screen("megaacme", ".com", cfg).startswith("has the banned part")
    assert naming.screen("acmehub", ".xyz", cfg) == ".xyz hurts delivery"
    assert naming.screen("a" * 41, ".com", cfg).startswith("longer than")


def test_price_over_the_limit_is_left_out_and_mix_has_both_styles():
    cfg = naming.load_config()
    reg = FakeRegistrar(prices={"goacmedental.com": 99.0})
    taken = set()
    out = naming.propose_for_client(4, "mix", reg.check_many, cfg, taken, website="acmedental.com", seed="c1")
    styles = [d["style"] for d in out["domains"]]
    assert styles == ["generic", "branded", "generic", "branded"]
    assert "goacmedental.com" not in [d["domain"] for d in out["domains"]]
    assert any("over the 15 USD limit" in r["reason"] for r in out["rejected"])


def test_porkbun_bulk_check_reads_the_answer_shape(monkeypatch):
    monkeypatch.setenv("PORKBUN_API_KEY", "test-key")
    monkeypatch.setenv("PORKBUN_SECRET_KEY", "test-secret")
    calls = []

    def respond(method, url, body):
        calls.append(url)
        return {"status": "SUCCESS", "domains": {
            "tryacme.com": {"avail": "yes", "price": "11.08", "premium": "no"},
            "goacme.com": {"avail": "no", "price": "11.08", "premium": "no"}}}

    old = http.set_transport(http.RecordingTransport(respond))
    try:
        got = Porkbun().check_many(["tryacme.com", "goacme.com", "myacme.com"])
    finally:
        http.set_transport(old)
    assert got["tryacme.com"].available and got["tryacme.com"].price == 11.08
    assert not got["goacme.com"].available
    assert "myacme.com" not in got  # no answer = unknown, never "free"
    assert calls == ["https://api.porkbun.com/api/json/v3/domain/checkDomain"]


def test_unknown_client_stops_plainly_and_asks_nothing():
    reg = FakeRegistrar()
    db = db_with_client()
    with pytest.raises(naming.NamingError) as e:
        propose_domains.propose_for(db, "Nobody Ltd", count=3, registrar=reg)
    assert "No client named 'Nobody Ltd'" in str(e.value)
    assert reg.asked == [] and db.writes == []


def test_not_enough_free_names_stops_without_a_short_list():
    cfg = dict(naming.load_config(), max_checks=10)

    class AllTaken(FakeRegistrar):
        def check_many(self, names):
            return {n: naming.Availability(False, reason="already registered") for n in names}

    with pytest.raises(naming.NamingError) as e:
        naming.propose_for_client(3, "branded", AllTaken().check_many, cfg, set(), website="acmedental.com")
    assert "Only 0 of 3 names are free" in str(e.value)
