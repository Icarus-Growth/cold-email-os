"""The tab 3 set-up scripts: client channel matching, the logo address, the database hook file."""

from fakes import AUTOMATIONS, MIGRATIONS, REPO

from logo import clean_domain, logo_url
from slack_setup import NEEDED, match_clients


def test_clients_match_their_channel_by_name():
    channels = [
        {"name": "youragency-example-client-a", "id": "A"},
        {"name": "general", "id": "G"},
        {"name": "youragency-example-client-a-ads", "id": "B"},
        {"name": "other-name", "id": "O"},
    ]
    clients = [
        {"id": "1", "client_name": "Example Client A"},
        {"id": "2", "client_name": "Example Client B"},
        {"id": "3", "client_name": "Odd One"},
    ]
    out = match_clients(clients, channels, {"odd one": "#other-name"})
    assert [m["channel"]["id"] if m["channel"] else None for m in out] == ["A", None, "O"]


def test_the_logo_address():
    assert clean_domain("https://www.YourAgency.com/about") == "youragency.com"
    url = logo_url("youragency.com", "test-key")
    assert url.startswith("https://img.logo.dev/youragency.com?")
    assert "format=png" in url and "size=512" in url and "fallback=404" in url


def test_the_manifest_asks_for_exactly_what_the_scripts_check():
    manifest = (AUTOMATIONS / "slack-app-manifest.yml").read_text()
    listed = [line.strip()[2:] for line in manifest.splitlines() if line.strip().startswith("- ")]
    assert sorted(listed) == sorted(NEEDED)


def hook_sql(repo=REPO):
    """The hook file's text, wherever tab 1 left it: in migrations/ before the Step 10 tidy-up,
    in archive/migrations/ after it, or joined into the baseline file if the old file is gone."""
    migrations = repo / MIGRATIONS.relative_to(REPO)
    for folder in (migrations, repo / "archive/migrations"):
        found = sorted(folder.glob("*automation_hooks.sql"))
        if found:
            return found[-1].read_text()
    for p in sorted(migrations.glob("*.sql")):
        text = p.read_text()
        if "function public.call_automation" in text:
            return text
    raise AssertionError("No file in {0} or archive/migrations/ sets up the automation hooks".format(migrations))


def test_the_hook_file_is_found_before_and_after_the_tidy_up(tmp_path):
    """Before: after tab 1 Step 10 the test looked only in migrations/ and failed."""
    sql = hook_sql()
    rel = MIGRATIONS.relative_to(REPO)
    before, after, joined = tmp_path / "before", tmp_path / "after", tmp_path / "joined"
    (before / rel).mkdir(parents=True)
    (before / rel / "0008_automation_hooks.sql").write_text(sql)
    (after / rel).mkdir(parents=True)
    (after / rel / "20261026000000_baseline.sql").write_text("-- joined\n" + sql)
    (after / "archive/migrations").mkdir(parents=True)
    (after / "archive/migrations/0008_automation_hooks.sql").write_text(sql)
    (joined / rel).mkdir(parents=True)
    (joined / rel / "20261026000000_baseline.sql").write_text("-- joined\n" + sql)
    for repo in (before, after, joined):
        assert "public.call_automation" in hook_sql(repo), repo


def test_the_hook_file_keeps_secrets_out_of_tables():
    sql = hook_sql()
    assert "vault.decrypted_secrets" in sql and "X-OS-Secret" in sql
    assert "revoke all on function public.call_automation" in sql
    assert "revoke all on function public.set_automation_hook" in sql


def test_the_deploy_steps_explain_the_scheduled_job_limit():
    docs = AUTOMATIONS.parents[2] / "docs"
    tab3 = (docs / "3-automations.md").read_text()
    assert "reached limit of 5 scheduled functions" in tab3 and "free plan allows 5 scheduled jobs" in tab3
    assert "modal app stop" in tab3
    for tab in ("4-second-brain.md", "5-mcp.md"):
        assert "reached limit of 5 scheduled functions" in (docs / tab).read_text(), tab
    # The text says the app needs one scheduled job. Keep it true.
    assert (AUTOMATIONS / "app.py").read_text().count("schedule=") == 1  # summary_schedule(): hourly or "off"
