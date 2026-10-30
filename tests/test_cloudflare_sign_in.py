"""The Cloudflare sign-in of the two deploy scripts (the OS and the onboarding form): the API
token from tab 2 is used whenever it is set, the global API key with its email only as a
fallback, and a token left in the terminal from other work never replaces the key in .env.
No call leaves this computer.

    python3 -m pytest tests/test_cloudflare_sign_in.py
"""

import importlib.util
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "apps" / "os" / "frontend" / "tools"))

import cloud  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(REPO / path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


form = load("apps/onboarding/tools/deploy.py", "onboarding_deploy")

TOKEN = {"CLOUDFLARE_API_TOKEN": "tok", "CLOUDFLARE_API_KEY": "", "CLOUDFLARE_EMAIL": "", "CLOUDFLARE_ACCOUNT_ID": "acct"}
GLOBAL = {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_API_KEY": "gk", "CLOUDFLARE_EMAIL": "me@example.com", "CLOUDFLARE_ACCOUNT_ID": "acct"}
BOTH = dict(GLOBAL, CLOUDFLARE_API_TOKEN="tok")


@pytest.fixture
def dotenv(tmp_path, monkeypatch):
    """Write a .env for both scripts; clear the Cloudflare names from the terminal."""
    for k in TOKEN:
        monkeypatch.delenv(k, raising=False)

    def write(values):
        (tmp_path / ".env").write_text("".join("%s=%s\n" % kv for kv in values.items()))
        monkeypatch.setattr(cloud, "REPO", tmp_path)
        monkeypatch.setattr(form, "REPO", tmp_path)
    return write


@pytest.mark.parametrize("c, token", [(TOKEN, True), (GLOBAL, False), (BOTH, True)])
def test_the_token_wins_whenever_it_is_set(c, token):
    assert cloud.uses_token(c) is token
    assert form.uses_token(c) is token
    want = {"Authorization": "Bearer tok"} if token else {"X-Auth-Email": "me@example.com", "X-Auth-Key": "gk"}
    assert cloud.cf_auth(c) == want


def test_with_no_sign_in_the_token_is_the_one_asked_for():
    empty = {k: "" for k in TOKEN}
    assert cloud.cf_keys(empty) == ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")
    assert form.cf_keys(empty) == ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")
    assert cloud.cf_keys(GLOBAL) == ("CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL", "CLOUDFLARE_ACCOUNT_ID")


def test_wrangler_gets_only_the_sign_in_in_use(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_KEY", "from-another-project")
    e = cloud.cf_env(TOKEN)
    assert e["CLOUDFLARE_API_TOKEN"] == "tok" and e["CLOUDFLARE_ACCOUNT_ID"] == "acct"
    assert "CLOUDFLARE_API_KEY" not in e and "CLOUDFLARE_EMAIL" not in e
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "from-another-project")
    e = cloud.cf_env(GLOBAL)
    assert "CLOUDFLARE_API_TOKEN" not in e
    assert (e["CLOUDFLARE_API_KEY"], e["CLOUDFLARE_EMAIL"]) == ("gk", "me@example.com")


def test_a_token_in_the_terminal_does_not_replace_the_global_key_in_dotenv(dotenv, monkeypatch):
    dotenv(dict(GLOBAL, SUPABASE_URL="https://x.supabase.co", SUPABASE_SECRET_KEY="sk"))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "from-another-project")
    c = cloud.env(tuple(TOKEN))
    assert not cloud.uses_token(c) and c["CLOUDFLARE_API_TOKEN"] == ""
    c = form.settings()
    assert not form.uses_token(c) and c["CLOUDFLARE_API_TOKEN"] == ""


def test_a_token_in_dotenv_is_used(dotenv, monkeypatch):
    dotenv(dict(TOKEN, SUPABASE_URL="https://x.supabase.co", SUPABASE_SECRET_KEY="sk"))
    assert cloud.uses_token(cloud.env(tuple(TOKEN)))
    assert form.uses_token(form.settings())


def test_the_form_script_names_what_is_missing(dotenv):
    dotenv({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SECRET_KEY": "sk"})
    with pytest.raises(SystemExit) as e:
        form.settings()
    assert "CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID" in str(e.value)
    assert "CLOUDFLARE_API_KEY" not in str(e.value)
