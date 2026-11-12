#!/usr/bin/env bash
# guard-files.sh: one guard for every coding tool in this repo (Claude Code, Codex, Grok).
#
# It runs before each tool call (the PreToolUse hook) and gets the call as JSON on stdin.
# Rule 1 (the only rule so far): no edit to .env or .env.* (the files that hold keys).
# .env.example (and .env.sample, .env.template) hold no keys, so they stay editable.
# Reading .env is allowed (tab 3 loads it with ". ./.env"); only writes are blocked.
#
# To block, it exits 2 and writes the reason on stderr. All three tools read that the same way:
#   Claude Code  exit 2 blocks the call; stderr goes to the AI
#   Codex        exit 2 blocks the call; stderr is the reason
#   Grok         exit 2 denies the call; the first stderr line is the reason
# Anything else exits 0 (allowed). A payload it cannot read is allowed: a broken hook must
# never stop all work. Needs python3 (every OS step already uses it). Wired from:
#   .claude/settings.json, .codex/hooks.json, .grok/hooks/guard-files.json
set -u
payload="$(cat)"
GUARD_PAYLOAD="$payload" exec python3 -c '
import json, os, re, sys

ALLOWED = {".env.example", ".env.sample", ".env.template"}

READ_ONLY = {"read", "read_file", "view", "grep", "glob", "ls", "list_dir", "notebookread", "webfetch", "web_search"}

def file_name(path):
    name = os.path.basename(str(path).strip().rstrip("/"))
    return re.split(r"[\x22\x27(=]", name)[-1]  # open(\x27.env -> .env

def guarded(path):
    name = file_name(path)
    return (name == ".env" or name.startswith(".env.")) and name not in ALLOWED

try:
    event = json.loads(os.environ.get("GUARD_PAYLOAD") or "{}")
except ValueError:
    sys.exit(0)
if not isinstance(event, dict):
    sys.exit(0)
# Claude Code and Codex send snake_case keys; Grok sends camelCase.
tool = str(event.get("tool_name") or event.get("toolName") or "")
if tool.lower() in READ_ONLY:
    sys.exit(0)  # reading .env is allowed; the rule is about edits
inp = event.get("tool_input") or event.get("toolInput") or {}
if not isinstance(inp, dict):
    inp = {"command": str(inp)}

paths = []
for key in ("file_path", "filePath", "path", "notebook_path", "target_file", "filename"):
    if isinstance(inp.get(key), str):
        paths.append(inp[key])
for edit in inp.get("edits") or []:
    if isinstance(edit, dict) and isinstance(edit.get("file_path"), str):
        paths.append(edit["file_path"])

command = inp.get("command") if isinstance(inp.get("command"), str) else ""
if isinstance(inp.get("command"), list):
    command = " ".join(str(c) for c in inp["command"])
# Codex file edits: apply_patch, with the patch text in tool_input.command.
for m in re.finditer(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$", command, re.M):
    paths.append(m.group(1) or m.group(2))

ENV = r"[^\s;|&<>]*\.env(?:\.[A-Za-z0-9_-]+)?"
END = r"(?=$|[\s;|&)\"\x27])"
writes = [
    r">>?\s*[\"\x27]?" + ENV + END,                                   # echo x > .env, >> .env
    r"\btee\b(?:\s+-\S+)*\s+[\"\x27]?" + ENV + END,                   # tee [-a] .env
    r"\b(?:sed|perl|ruby)\b[^;|&]*\s-i\S*[^;|&]*\s[\"\x27]?" + ENV + END,  # sed -i ... .env
    r"\b(?:cp|mv|install|ln|rsync)\b[^;|&]*\s[\"\x27]?" + ENV + r"\s*(?=$|[;|&])",  # ... -> .env (last)
    r"\b(?:rm|truncate|shred|unlink)\b[^;|&]*\s[\"\x27]?" + ENV + END,  # rm .env
    r"\bopen\(\s*[\"\x27]" + ENV + r"[\"\x27]\s*,\s*[\"\x27][wa+]",   # python open(".env", "w")
]
hits = []
for pattern in writes:
    for m in re.finditer(pattern, command):
        found = re.findall(ENV, m.group(0))
        hits.extend(p for p in found if guarded(p))

blocked = [p for p in paths if guarded(p)] + hits
if blocked:
    sys.stderr.write(
        "Blocked by guard-files.sh: {0} holds keys and is never edited by an AI tool ({1}). "
        "Ask the person to change it by hand, or use the set-up script the guide names.\n".format(
            file_name(blocked[0]), tool or "unknown tool"
        )
    )
    sys.exit(2)
sys.exit(0)
'
