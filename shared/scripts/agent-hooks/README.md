# Agent hooks: the same guard rails in Claude Code, Codex and Grok

One script, `guard-files.sh`, runs before every tool call in all three coding tools. It gets the
call as JSON on stdin and blocks it with exit code 2 and a reason on stderr, which all three tools
read the same way.

| Rule | What it blocks | What stays allowed |
|---|---|---|
| 1. Key files | Any edit to `.env` or `.env.*` (edit tools, patches, and shell writes such as `>`, `>>`, `tee`, `sed -i`, `cp`/`mv` onto it, `rm`) | Reading `.env` (tab 3 loads it with `. ./.env`), `.env.example`, `.env.sample`, `.env.template`, and the set-up scripts that write keys (`connect_db.py secret`) |

## Where it is wired

| Tool | File | Event and matcher | Turn it on |
|---|---|---|---|
| Claude Code | `.claude/settings.json` | `PreToolUse`, `Edit\|Write\|MultiEdit\|NotebookEdit\|Bash` | On at once |
| Codex | `.codex/hooks.json` | `PreToolUse`, `Bash\|apply_patch\|Edit\|Write` (file edits come as `apply_patch`, the patch text in `tool_input.command`) | Trust the project, then review and trust the hook once with `/hooks`. Codex skips a new or changed hook until it is trusted. |
| Grok (Grok Build) | `.grok/hooks/guard-files.json` | `PreToolUse`, `search_replace\|write_file\|run_terminal_command\|...` (Grok sends `toolName` and `toolInput`) | Trust the project once: `/hooks-trust`, or start Grok with `--trust`. |

Grok also reads `.claude/settings.json`, so in Grok the guard runs twice. Both runs give the same
answer, so this does no harm, and the `.grok` file still works if someone turns off Grok's Claude
file reading. All three files also run `tools/sync_skills.py` at the start of a session, so each
tool sees the skills after a clone or a pull.

## Add a rule

Add it to `guard-files.sh`, with a test in `test_guard_files.py` for each tool's input shape.
Run: `python3 -m pytest shared/scripts/agent-hooks`.

## Sources (checked 11 Nov 2026)

- Claude Code: https://docs.anthropic.com/en/docs/claude-code/hooks (PreToolUse, `tool_name`, `tool_input.file_path`, exit 2 blocks). Also proven here: Claude Code 2.1.322 run on a copy of this repo was blocked on an Edit and on `echo A=3 >> .env`, and `.env` did not change.
- Codex: https://developers.openai.com/codex/hooks (now served at https://learn.chatgpt.com/docs/hooks.md): hook files `<repo>/.codex/hooks.json`; PreToolUse covers Bash and `apply_patch` file edits; matcher values `apply_patch`, `Edit`, `Write`; exit code 2 with the reason on stderr; hooks must be trusted. Second source: https://codex.danielvaughan.com/2026/04/15/codex-cli-hooks-complete-guide-events-policy-patterns/
- Grok Build: https://docs.x.ai/build/features/hooks (`<project>/.grok/hooks/*.json`, `toolName`/`toolInput`, exit 2 denies, project hooks need trust, reads `.claude/settings.json` too). Second source: the CLI's own guide, https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md (tool aliases `Edit`/`Write` -> `search_replace`, `Bash` -> `run_terminal_command`), and the tool's source for the `search_replace` input field `file_path`: https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-tools/src/implementations/grok_build/search_replace/mod.rs
- Not proven on a real Codex or Grok run: neither is installed on the build computer. Their payloads are tested from the documented shapes.
