"""guard-files.sh with a fake payload in each tool's own input shape, run through the exact
command each tool's hook file holds (so the wiring is tested too).

    python3 -m pytest shared/scripts/agent-hooks      (from the repo root)

Input shapes, from each tool's docs (links in the README next to this file):
  Claude Code  {"tool_name": "Edit", "tool_input": {"file_path": ...}}; Bash: tool_input.command
  Codex        {"tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch ..."}}; Bash too
  Grok         {"toolName": "search_replace", "toolInput": {"file_path": ...}}; run_terminal_command
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = HERE / "guard-files.sh"
WIRING = {
    "claude": REPO / ".claude" / "settings.json",
    "codex": REPO / ".codex" / "hooks.json",
    "grok": REPO / ".grok" / "hooks" / "guard-files.json",
}


def patch(path, kind="Update"):
    return "*** Begin Patch\n*** {0} File: {1}\n@@\n-OLD=1\n+NEW=2\n*** End Patch\n".format(kind, path)


BLOCK = {
    "claude": [
        {"tool_name": "Edit", "tool_input": {"file_path": "/work/os/.env", "old_string": "a", "new_string": "b"}},
        {"tool_name": "Write", "tool_input": {"file_path": ".env.local", "content": "X=1"}},
        {"tool_name": "MultiEdit", "tool_input": {"file_path": "apps/os/frontend/.env.production", "edits": []}},
        {"tool_name": "Bash", "tool_input": {"command": "echo 'SLACK_BOT_TOKEN=x' >> .env"}},
        {"tool_name": "Bash", "tool_input": {"command": "sed -i '' 's/a/b/' .env"}},
        {"tool_name": "Bash", "tool_input": {"command": "cp .env.example .env"}},
        {"tool_name": "Bash", "tool_input": {"command": "printf 'A=1' | tee -a ./.env"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm -f .env"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"open('.env', 'w').write('x')\""}},
    ],
    "codex": [
        {"tool_name": "apply_patch", "tool_input": {"command": patch(".env")}},
        {"tool_name": "apply_patch", "tool_input": {"command": patch("config/.env.staging", "Add")}},
        {"tool_name": "apply_patch", "tool_input": {"command": patch("notes.md") + "*** Move to: .env\n"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat secrets.txt > .env"}},
    ],
    "grok": [
        {"toolName": "search_replace", "toolInput": {"file_path": ".env", "old_string": "a", "new_string": "b"}},
        {"toolName": "write_file", "toolInput": {"path": "/abs/repo/.env.local", "content": "x"}},
        {"toolName": "run_terminal_command", "toolInput": {"command": "echo X=1 > .env"}},
    ],
}
ALLOW = {
    "claude": [
        {"tool_name": "Edit", "tool_input": {"file_path": "apps/os/automations/app.py"}},
        {"tool_name": "Write", "tool_input": {"file_path": ".env.example", "content": "X="}},
        {"tool_name": "Write", "tool_input": {"file_path": "src/settings.env.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "set -a; . ./.env; set +a"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"import re;print(open('.env').read().count('='))\""}},
        {"tool_name": "Bash", "tool_input": {"command": "cp .env .env.backup.txt.example && git status"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 apps/os/automations/connect_db.py secret"}},
        {"tool_name": "Read", "tool_input": {"file_path": ".env"}},
    ],
    "codex": [
        {"tool_name": "apply_patch", "tool_input": {"command": patch("apps/os/automations/app.py")}},
        {"tool_name": "Bash", "tool_input": {"command": "grep -c = .env"}},
    ],
    "grok": [
        {"toolName": "search_replace", "toolInput": {"file_path": "README.md"}},
        {"toolName": "read_file", "toolInput": {"path": ".env"}},
    ],
}


def run_hook(tool, payload, shell="bash", cwd=None):
    """Run the hook exactly as the tool's own hook file says, from the repo root."""
    spec = json.loads(WIRING[tool].read_text())
    command = spec["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    env = dict(os.environ)
    if tool == "claude":
        env["CLAUDE_PROJECT_DIR"] = str(REPO)
    return subprocess.run(
        [shell, "-c", command], input=json.dumps(payload), capture_output=True, text=True, cwd=cwd or REPO, env=env,
        timeout=30,
    )  # fmt: skip


@pytest.mark.parametrize("tool,payload", [(t, p) for t, ps in BLOCK.items() for p in ps])
def test_every_edit_of_a_key_file_is_blocked(tool, payload):
    out = run_hook(tool, payload)
    assert out.returncode == 2, (tool, payload, out.stderr)
    assert out.stderr.startswith("Blocked by guard-files.sh: .env") and "holds keys" in out.stderr


@pytest.mark.parametrize("tool,payload", [(t, p) for t, ps in ALLOW.items() for p in ps])
def test_everything_else_is_allowed(tool, payload):
    out = run_hook(tool, payload)
    assert out.returncode == 0 and out.stderr == "", (tool, payload, out.stderr)


def test_the_matchers_cover_each_tools_edit_and_shell_tools():
    import re

    names = {
        "claude": ["Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"],
        "codex": ["Bash", "apply_patch", "Edit", "Write"],
        "grok": ["search_replace", "write_file", "run_terminal_command"],
    }
    for tool, wanted in names.items():
        matcher = json.loads(WIRING[tool].read_text())["hooks"]["PreToolUse"][0]["matcher"]
        for name in wanted:
            assert re.fullmatch(matcher, name), (tool, name)
        assert not re.fullmatch(matcher, "Read") and not re.fullmatch(matcher, "read_file")


def test_a_payload_it_cannot_read_is_allowed():
    for bad in ("", "not json", "[1, 2]", '{"tool_name": "Edit"}'):
        out = subprocess.run(["bash", str(SCRIPT)], input=bad, capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, bad


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is not installed")
def test_it_runs_the_same_from_zsh_and_from_a_sub_folder():
    payload = BLOCK["claude"][0]
    assert run_hook("codex", payload, shell="zsh").returncode == 2
    assert run_hook("grok", payload, shell="zsh", cwd=REPO / "shared").returncode in (0, 2)
