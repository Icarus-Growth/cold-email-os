"""create-client: makes a notes folder from the template; refuses a folder that exists.

    python3 -m pytest skills/global/create-client -q
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/create_client.py"


def load(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("create_client", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tpl = tmp_path / "clients/_template"
    tpl.mkdir(parents=True)
    (tpl / "about.md").write_text("# {{CLIENT_NAME}}\n")
    (tpl / "decisions.md").write_text("# Decisions for {{CLIENT_NAME}}\n")
    monkeypatch.setattr(mod, "CLIENTS", tmp_path / "clients")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "TEMPLATE", tpl)
    return mod


def test_create_client_example(tmp_path, monkeypatch):
    mod = load(tmp_path, monkeypatch)
    assert mod.folder_name("Acme Corp.") == "acme-corp"
    assert mod.main(["--name", "Acme Corp", "--dry-run"]) == 0
    assert not (tmp_path / "clients/acme-corp").exists()
    assert mod.main(["--name", "Acme Corp"]) == 0
    assert (tmp_path / "clients/acme-corp/about.md").read_text() == "# Acme Corp\n"


def test_create_client_bad_input_changes_nothing(tmp_path, monkeypatch):
    mod = load(tmp_path, monkeypatch)
    (tmp_path / "clients/acme-corp").mkdir()
    with pytest.raises(SystemExit):
        mod.create("Acme Corp", "acme-corp")
    with pytest.raises(SystemExit):
        mod.create("Acme Corp", "_template")
    assert list((tmp_path / "clients/acme-corp").iterdir()) == []
