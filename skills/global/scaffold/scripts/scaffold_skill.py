"""Make a new skill folder in the skill format, ready to fill in.

    python3 skills/global/scaffold/scripts/scaffold_skill.py \
        --name review-reminder --area fulfilment --agency all \
        --kind rows --runs-on modal \
        --description "Reminds the reviewer about cards waiting in review. Use when ..." \
        --needs SUPABASE_URL,SUPABASE_SECRET_KEY,SLACK_BOT_TOKEN \
        [--table tasks] [--daily] [--spends] [--dry-run]

Kinds:
  rows    reads rows not done yet from one table, does each one, writes the result back
          (batches of at most 500; a crash picks up where it stopped)
  job     one job from start to end each time it runs (a check, a post, a report)
  steps   no code: numbered steps an AI follows (Claude Code, Codex, Grok or another agent)

Where it runs (--runs-on):
  modal   the automation server. The ONE app runs it: on demand, from the daily job
          (--daily), or from an address. No new app, no new schedule.
  grok    the steps are for the Grok coding tool (or any AI). Same folder, runs_on: local.
  server  your own server or computer, from a terminal or a cron line. runs_on: local.
  either  both the automation server and a computer.

It makes skills/<area>/<name>/ with SKILL.md, config.json, scripts/ and tests/, then links it
for Claude Code (tools/sync_skills.py). It never changes a folder that already exists.
Standard library only, Python 3.9.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

for _up in Path(__file__).resolve().parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
import skillkit  # noqa: E402

KINDS = ("rows", "job", "steps")
TARGETS = {"modal": "modal", "grok": "local", "server": "local", "either": "either"}

WHERE = {
    "SUPABASE_URL": "Supabase, Project Settings, Data API (tab 1)",
    "SUPABASE_SECRET_KEY": "Supabase, Project Settings, API Keys, secret key (tab 1)",
    "SLACK_BOT_TOKEN": "api.slack.com/apps, your app, OAuth & Permissions (tab 3)",
    "ANTHROPIC_API_KEY": "console.anthropic.com, Settings, API Keys",
}

KIT_IMPORT = '''import sys
from pathlib import Path

for _up in Path(__file__).resolve().parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
import skillkit  # noqa: E402
'''


def snake(name: str) -> str:
    return name.replace("-", "_")


def where_lines(needs: List[str]) -> str:
    rows = ["| `{0}` | {1} |".format(k, WHERE.get(k, "TODO: the page in that tool where you make the key"))
            for k in needs]
    return "\n".join(["| Key in .env | Where to get it |", "|---|---|"] + rows) if needs else "None."


# --------------------------------------------------------------------------- SKILL.md


def skill_md(a: argparse.Namespace, needs: List[str], runs_on: str) -> str:
    head = "\n".join([
        "---",
        "name: " + a.name,
        "description: " + a.description,
        "area: " + a.area,
        "agency: " + a.agency,
        "needs: [" + ", ".join(needs) + "]",
        "runs_on: " + runs_on,
    ] + (["daily: true"] if a.daily else []) + ["---", ""])
    title = a.name.replace("-", " ").capitalize()
    run_cmd = "python3 skills/{0}/{1}/scripts/run.py".format(a.area, a.name)

    how: List[str] = ["## How to run it", ""]
    if a.kind == "steps":
        how += ["An AI follows the steps below. Ask it: \"follow skills/{0}/{1}/SKILL.md\".".format(a.area, a.name)]
        if a.target == "grok":
            how += ["", "In the Grok coding tool, open this repo and ask the same. Grok reads `skills/` like every",
                    "other coding tool. It runs while Grok is open. To run it with the laptop closed, make it a",
                    "`modal` skill instead (run the scaffold again with `--runs-on modal`)."]
    else:
        how += ["On this computer (keys from `.env`):", "", "```", run_cmd + " --dry-run     # shows what it would do",
                run_cmd + "               # does it", "```", ""]
        if a.target in ("modal", "either"):
            how += ["On the automation server (the ONE Modal app; no new app, no new schedule):", "", "```",
                    "python3 -m modal run apps/os/automations/app.py::run_skill --name {0}".format(a.name), "```", "",
                    "Or from another tool: POST `<OS_AUTOMATIONS_URL>/skill/{0}` with the header".format(a.name),
                    "`X-OS-Secret` and a JSON body of the arguments. Deploy again after a change:",
                    "`python3 -m modal deploy apps/os/automations/app.py`. Put each key in the `agency-os` secret on Modal."]
            if a.daily:
                how += ["", "It also runs once a day inside the daily job (`daily: true`, `scripts/daily.py`)."]
        if a.target == "server":
            how += ["On your own server or computer, once a day at 08:00 (a cron line; `crontab -e`):", "", "```",
                    "0 8 * * * cd /path/to/this/repo && {0} >> skill-{1}.log 2>&1".format(run_cmd, a.name), "```", "",
                    "The machine must be on at that time. The keys come from `.env` on that machine."]

    steps: List[str] = ["## Steps", ""]
    if a.kind == "steps":
        steps += ["1. TODO: what the AI reads first (tables, files, notes).",
                  "2. TODO: what it does, one action per step.",
                  "3. TODO: what it writes back, and where.",
                  "4. Show the person what changed, read back from where it was written."]
    else:
        steps += ["1. Check the keys: the script stops and says which key is missing and where to get it.",
                  "2. Run it with `--dry-run` first. Read what it would do.",
                  "3. Run it without `--dry-run`.",
                  "4. Read the result back from the database. Do not trust the \"OK\" from the write.",
                  "5. Tell the person where to look: the Slack channel, the screen, the record."]
    if a.spends:
        steps += ["", "**Spend gate.** Before any step that spends money or sends something to a client or a",
                  "prospect, the script posts the cost in the `review` channel and stops. A person approves by",
                  "moving the card to the next stage in the OS. Only then does the spend run."]

    rules = ["## Rules", "",
             "- Slack posts go only through `shared/slack_notify.py`, only to automation channels. Never a client channel.",
             "- A failure is posted once to `pipeline-errors`, with the record and the error.",
             "- Rules a person may change live in `config.json`, not in the code."]
    if a.kind == "rows":
        rules.append("- Rows are done in batches of at most 500. A crash picks up at the next row not done.")
    done = ["## Done when", "",
            "- [ ] `python3 -m pytest skills/{0}/{1}` passes (one test with example data, one with bad input).".format(
                a.area, a.name),
            "- [ ] It ran once on real or example data, and the result was read back.",
            "- [ ] One bad input failed cleanly: a plain message, nothing written.",
            "- [ ] One line in DECISIONS.md says what was chosen and why.",
            "- [ ] `python3 tools/sync_skills.py --check` passes."]
    body = ["# " + title, "", a.description, "", "## What it needs", "", where_lines(needs), ""]
    return head + "\n".join(body + how + [""] + steps + [""] + rules + [""] + done) + "\n"


# --------------------------------------------------------------------------- scripts


def run_py(a: argparse.Namespace, needs: List[str]) -> str:
    table = a.table or "tasks"
    where = {k: WHERE.get(k, "TODO: where to get it") for k in needs}
    common = '''"""{desc}

    python3 skills/{area}/{name}/scripts/run.py --dry-run
    python3 skills/{area}/{name}/scripts/run.py
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

{kit}
HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE.parent / "config.json").read_text())
NEEDS = {needs!r}
WHERE = {where!r}
SKILL = "{name}"
'''.format(desc=a.description.replace('"', "'"), area=a.area, name=a.name, kit=KIT_IMPORT, needs=needs,
           where=where)
    gate = ""
    if a.spends:
        gate = '''

def spend_gate(ctx: Any, row: Dict[str, Any], dry_run: bool) -> bool:
    """True only when a person moved the card on in the OS. Otherwise it asks in the review
    channel (once a day per card) and the row waits. Nothing is spent on a row that waits."""
    board, stage = CONFIG["approval_board"], CONFIG["approval_stage"]
    if skillkit.approval(ctx.db, board, row["id"], stage):
        return True
    if not dry_run and skillkit.first_time(ctx.seen, "ask:" + SKILL + ":" + str(row["id"])):
        link = skillkit.card_link(ctx.settings(), board, row["id"])
        skillkit.ask_for_approval(ctx, "TODO: what this buys", ["TODO: the cost estimate"], link)
    return False
'''
    if a.kind == "rows":
        logic = '''

def check(row: Dict[str, Any]) -> None:
    """Bad input stops here, before anything is written. TODO: the real checks."""
    if not row.get("id"):
        raise ValueError("A row has no id.")


def do_one(ctx: Any, row: Dict[str, Any]) -> Dict[str, Any]:
    """TODO: the work for one row. Return the columns to write back. Pure where you can."""
    return {{CONFIG["done_column"]: skillkit.now_iso()}}


def run(ctx: Any, dry_run: bool = False, limit: int = skillkit.BATCH_MAX, max_batches: int = 0) -> Dict[str, Any]:
    """Every row of {table} whose done column is still empty, in batches of at most 500."""
    table, done_col = CONFIG["table"], CONFIG["done_column"]
    planned: List[Dict[str, Any]] = []
    skipped: List[str] = []

    def todo(size: int) -> List[Dict[str, Any]]:
        return ctx.db.select(table, {{done_col: "is.null"}}, limit=size)

    def work(rows: List[Dict[str, Any]]) -> int:
        for row in rows:
            check(row)
        n = 0
        for row in rows:{gate_call}
            values = do_one(ctx, row)
            if dry_run:
                planned.append({{"id": row["id"], "would_write": values}})
                continue
            ctx.db.update(table, row["id"], values)
            n += 1
        return n if not dry_run else len(planned)

    # A dry run looks at one batch only: it writes nothing, so the same rows would come back.
    out = skillkit.run_in_batches(todo, work, size=limit, max_batches=1 if dry_run else (max_batches or None))
    out.update({{"ok": True, "dry_run": dry_run, "waiting_for_approval": skipped}})
    if dry_run:
        out["planned"] = planned
    return out
'''.format(table=table, gate_call="\n            if not spend_gate(ctx, row, dry_run):\n                skipped.append(row[\"id\"])\n                continue" if a.spends else "")
    else:
        logic = '''

def check(args: Dict[str, Any]) -> None:
    """Bad input stops here, before anything is written. TODO: the real checks."""
    unknown = sorted(set(args) - set(CONFIG.get("arguments", [])))
    if unknown:
        raise ValueError("Unknown input: {{0}}.".format(", ".join(unknown)))


def run(ctx: Any, dry_run: bool = False, **args: Any) -> Dict[str, Any]:
    """TODO: the job. Read, decide, write back, tell the right channel."""
    check(args)
    rows = ctx.db.select(CONFIG["table"], {{}}, limit=skillkit.BATCH_MAX)
    text = "*{title}*\\n{{0}} rows checked.".format(len(rows))
    if dry_run:
        return {{"ok": True, "dry_run": True, "would_post": text}}
    skillkit.post(ctx, CONFIG["channel"], CONFIG["bot_name"], text)
    return {{"ok": True, "rows": len(rows)}}
'''.format(title=a.name.replace("-", " ").capitalize())
    main = '''

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="show what it would do; change nothing")
    a = ap.parse_args()
    ctx = skillkit.context(needs=NEEDS, where=WHERE)
    try:
        out = run(ctx, dry_run=a.dry_run)
    except Exception as e:  # noqa: BLE001 - one plain line, and one post in pipeline-errors
        if not isinstance(e, (skillkit.MissingKey, skillkit.NotApproved, ValueError)):
            skillkit.report_failure(ctx, SKILL, "run", e)
        raise
    print(skillkit.dump(out))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    skillkit.main_guard(main)
'''
    return common + gate + logic + main


def daily_py(a: argparse.Namespace) -> str:
    return '''"""Called once a day by the daily job (no schedule of its own).

The daily job passes its own database, Slack and channels. The same `run` as on demand.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent


def run(db: Any, slack: Any, config: Any, seen: Any, today: Any) -> Dict[str, Any]:
    spec = importlib.util.spec_from_file_location("{snake}_run", str(HERE / "run.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    key = "daily:{name}:" + str(today)
    if not mod.skillkit.first_time(seen, key, hours=20):
        return {{"ok": True, "skipped": "already ran today"}}
    return mod.run(mod.skillkit.Context(db, slack, config, seen))
'''.format(snake=snake(a.name), name=a.name)


def test_py(a: argparse.Namespace) -> str:
    table = a.table or "tasks"
    if a.kind == "rows":
        good = '''    db = fakes.FakeDB({{"{table}": [{{"id": "r1", "{done}": None}}, {{"id": "r2", "{done}": None}}]}})
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    {approve}out = mod.run(ctx)
    assert out["ok"] and out["done"] == 2
    assert db.select("{table}", {{"{done}": "is.null"}}) == []     # read back, not the "OK"
'''
        bad = '''    db = fakes.FakeDB({{"{table}": [{{"id": "", "{done}": None}}]}})
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    with pytest.raises(ValueError):
        mod.run(ctx)
    assert db.writes == []                                         # nothing written
'''
        approve = ""
        if a.spends:
            approve = ('db.tables["stage_log"] = [{"id": "s", "board": mod.CONFIG["approval_board"], "record_id": rid,\n'
                       '        "from_stage": mod.CONFIG["approval_stage"], "to_stage": "999 - Next", "changed_by_id": "p1"}\n'
                       '        for rid in ("r1", "r2")]\n    ')
        good = good.format(table=table, done="done_at", approve=approve)
        bad = bad.format(table=table, done="done_at")
    else:
        good = '''    db = fakes.FakeDB({{"{table}": [{{"id": "r1"}}]}})
    ctx = skillkit.Context(db, fakes.FakeSlack(), fakes.FakeConfig())
    out = mod.run(ctx)
    assert out["ok"]
    assert ctx.slack.posts and ctx.slack.posts[0]["channel"] == "chan-" + mod.CONFIG["channel"]
'''.format(table=table)
        bad = '''    ctx = skillkit.Context(fakes.FakeDB(), fakes.FakeSlack(), fakes.FakeConfig())
    with pytest.raises(ValueError):
        mod.run(ctx, not_an_input=1)
    assert ctx.slack.posts == [] and ctx.db.writes == []
'''
    return '''"""{name}: one test with example data, one with bad input. TODO: make them test the real logic.

    python3 -m pytest skills/{area}/{name} -q
"""

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
for _up in HERE.parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
import skill_fakes as fakes  # noqa: E402
import skillkit  # noqa: E402

_spec = importlib.util.spec_from_file_location("{snake}_run", str(HERE.parents[1] / "scripts/run.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_{snake}_example_data():
{good}

def test_{snake}_bad_input_fails_cleanly():
{bad}'''.format(name=a.name, area=a.area, snake=snake(a.name), good=good, bad=bad)


def config_json(a: argparse.Namespace) -> str:
    cfg: Dict[str, object] = {"_about": "Rules a person may change. The code reads them; change them here, not in the code.",
                              "table": a.table or "tasks", "channel": "task-updates",
                              "bot_name": a.name.replace("-", " ").title()}
    if a.kind == "rows":
        cfg["done_column"] = "done_at"
        cfg["_done_column"] = ("A column on the table that stays empty until this skill has done the row. "
                               "Add it to the parent table if it is not there (DATABASE_RULES.md).")
    else:
        cfg["arguments"] = []
    if a.spends:
        cfg["approval_board"] = a.table or "tasks"
        cfg["approval_stage"] = "10 - Approval Needed"
    return json.dumps(cfg, indent=2) + "\n"


# --------------------------------------------------------------------------- main


def plan_files(a: argparse.Namespace, root: Path) -> Dict[Path, str]:
    needs = [n.strip() for n in (a.needs or "").split(",") if n.strip()]
    if a.kind != "steps":
        for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY"):
            if k not in needs:
                needs.insert(0 if k == "SUPABASE_URL" else 1, k)
        if "SLACK_BOT_TOKEN" not in needs:
            needs.append("SLACK_BOT_TOKEN")
    runs_on = TARGETS[a.target]
    folder = root / "skills" / a.area / a.name
    files = {folder / "SKILL.md": skill_md(a, needs, runs_on)}
    if a.kind != "steps":
        files[folder / "config.json"] = config_json(a)
        files[folder / "scripts/run.py"] = run_py(a, needs)
        files[folder / "tests/test_{0}.py".format(snake(a.name))] = test_py(a)
        if a.daily:
            files[folder / "scripts/daily.py"] = daily_py(a)
    return files


def problems(a: argparse.Namespace, root: Path) -> List[str]:
    out = []
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", a.name or "") or len(a.name) > 64:
        out.append("The name must be small letters, numbers and dashes, for example 'review-reminder'.")
    if len((a.description or "").strip()) < 20:
        out.append("The description must say what the skill does and when to use it.")
    if a.kind == "steps" and (a.daily or a.target in ("modal", "either")):
        out.append("A 'steps' skill has no code, so it cannot run on the automation server or daily. "
                   "Pick --kind job or rows.")
    for s in skillkit.find_skills(root):
        if s["card"].get("name") == a.name or s["folder"].name == a.name:
            out.append("A skill named '{0}' is already in {1}. Pick another name.".format(
                a.name, s["folder"].relative_to(root)))
    if (root / "skills" / a.area / a.name).exists():
        out.append("skills/{0}/{1}/ exists already. Nothing was changed.".format(a.area, a.name))
    bad = [n for n in (a.needs or "").split(",") if n.strip() and not re.match(r"^[A-Z][A-Z0-9_]*$", n.strip())]
    if bad:
        out.append("These are not .env key names: {0}".format(", ".join(bad)))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Make a new skill folder.")
    ap.add_argument("--name", required=True)
    ap.add_argument("--description", required=True)
    ap.add_argument("--area", choices=skillkit.AREAS, default="fulfilment")
    ap.add_argument("--agency", choices=skillkit.AGENCIES, default="all")
    ap.add_argument("--kind", choices=KINDS, default="job")
    ap.add_argument("--runs-on", dest="target", choices=tuple(TARGETS), default="modal")
    ap.add_argument("--needs", default="", help="the .env keys, comma separated")
    ap.add_argument("--table", default="", help="the table it reads (rows and job)")
    ap.add_argument("--daily", action="store_true", help="the daily job runs it once a day")
    ap.add_argument("--spends", action="store_true", help="it spends money or sends to clients: add the gate")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default=str(skillkit.ROOT), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()

    probs = problems(a, root)
    if probs:
        for p in probs:
            print("STOP: " + p)
        return 2
    files = plan_files(a, root)
    for path in files:
        print(("would make " if a.dry_run else "made ") + str(path.relative_to(root)))
    if a.dry_run:
        return 0
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    sync = root / "tools/sync_skills.py"
    if sync.exists():
        subprocess.run([sys.executable, str(sync), "--root", str(root)], check=False)
    print("Next: fill in each TODO, then run `python3 -m pytest skills/{0}/{1} -q`.".format(a.area, a.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
