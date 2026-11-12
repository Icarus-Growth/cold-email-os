"""search-client: finds a client by name, other name or email domain; lists, never picks, on a tie.

    python3 -m pytest skills/global/search-client -q
"""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/search_client.py"
spec = importlib.util.spec_from_file_location("search_client", str(SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ROWS = [
    {"id": "c1", "client_name": "Acme Dental Ltd", "contact_email": "jane@example.com",
     "website": "https://acmedental.example.com"},
    {"id": "c2", "client_name": "Northwind Roofing", "contact_email": "sam@example.org"},
]
FOLDERS = [{"folder": "acme-dental", "names": ["Acme Dental", "ADL"], "emails": set(), "domains": set()}]


def test_search_client_example_sure_matches():
    found, kind = mod.find("acme dental", "", ROWS, FOLDERS)
    assert kind == "sure" and found[0]["row"]["id"] == "c1" and found[0]["folder"]["folder"] == "acme-dental"
    found, kind = mod.find("ADL", "", ROWS, FOLDERS)
    assert kind == "sure" and found[0]["row"]["id"] == "c1"
    found, kind = mod.find("", "sam@example.org", ROWS, FOLDERS)
    assert kind == "sure" and found[0]["row"]["id"] == "c2"


def test_search_client_bad_input_finds_nothing():
    found, kind = mod.find("zzqx unknown company", "", ROWS, FOLDERS)
    assert kind == "none" and found == []
