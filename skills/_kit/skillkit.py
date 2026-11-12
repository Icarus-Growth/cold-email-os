"""What every skill shares: its card (the SKILL.md header), the keys it needs, the database,
Slack, batches that pick up where they stopped, the spend gate and the daily hook.

A skill script starts like this:

    import sys
    from pathlib import Path
    for _up in Path(__file__).resolve().parents:   # finds skills/_kit (or core/skills/_kit)
        _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
        if _kit:
            sys.path.insert(0, str(_kit[0]))
            break
    import skillkit

    ctx = skillkit.context(needs=["SERPER_API_KEY"], where={"SERPER_API_KEY": "serper.dev, Dashboard, API key"})

`context()` reads .env, stops with a plain message if a key is missing, and gives the skill
the database (`ctx.db`), Slack (`ctx.slack`) and the automation channels (`ctx.config`).
On the automation server (Modal) the daily job passes its own `db`, `slack` and `config`,
which have the same methods.

Nothing here prints a key value. Standard library only, Python 3.9.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, MutableMapping, Optional, Sequence

KIT = Path(__file__).resolve().parent
SKILLS = KIT.parent
ROOT = SKILLS.parent

AREAS = ("fulfilment", "owner", "global")
AGENCIES = ("all", "cold-email", "ads", "content", "email-marketing")
RUNS_ON = ("modal", "local", "either")
FIELDS = ("name", "description", "area", "agency", "needs", "runs_on")
BATCH_MAX = 500

ERROR_BOT = "🚨 Automation Failed"
APPROVAL_BOT = "💸 Spend Needs Approval"


def _put_root_on_path() -> None:
    for p in (str(ROOT),):
        if p not in sys.path:
            sys.path.insert(0, p)


# --------------------------------------------------------------------------- the skill card


def parse_frontmatter(text: str) -> Dict[str, Any]:
    """The `---` header at the top of a SKILL.md, as a dict. Handles `key: value`,
    `key: [a, b]`, `key: []` and a list written as `- item` lines. Pure."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: Dict[str, Any] = {}
    key = ""
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        item = re.match(r"^\s+-\s*(.*)$", line)
        if item and key:
            if not isinstance(out.get(key), list):
                out[key] = []
            out[key].append(_scalar(item.group(1)))
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            out[key] = [_scalar(x) for x in inner.split(",")] if inner else []
        else:
            out[key] = _scalar(raw) if raw else ""
    return {}  # no closing line: not a header


def _scalar(raw: str) -> Any:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    if raw.lower() in ("true", "yes"):
        return True
    if raw.lower() in ("false", "no"):
        return False
    return raw


def card_problems(card: Dict[str, Any], folder: Path) -> List[str]:
    """What is wrong with one skill's header, in plain words. Empty list = fine."""
    probs = []
    for f in FIELDS:
        if f not in card:
            probs.append("the header has no '{0}' line".format(f))
    name = str(card.get("name", ""))
    if name and name != folder.name:
        probs.append("'name: {0}' must match the folder name '{1}'".format(name, folder.name))
    if name and not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
        probs.append("the name must be small letters, numbers and dashes")
    if len(name) > 64:
        probs.append("the name is longer than 64 characters")
    area = card.get("area")
    if "area" in card and area not in AREAS:
        probs.append("'area' must be one of {0}".format(", ".join(AREAS)))
    if "area" in card and folder.parent.name in AREAS and area != folder.parent.name:
        probs.append("'area: {0}' but the skill is in skills/{1}/".format(area, folder.parent.name))
    if "agency" in card and card.get("agency") not in AGENCIES:
        probs.append("'agency' must be one of {0}".format(", ".join(AGENCIES)))
    if "runs_on" in card and card.get("runs_on") not in RUNS_ON:
        probs.append("'runs_on' must be one of {0}".format(", ".join(RUNS_ON)))
    needs = card.get("needs")
    if "needs" in card:
        if not isinstance(needs, list):
            probs.append("'needs' must be a list, for example [SUPABASE_URL, SUPABASE_SECRET_KEY] or []")
        else:
            bad = [n for n in needs if not re.match(r"^[A-Z][A-Z0-9_]*$", str(n))]
            if bad:
                probs.append("these 'needs' are not .env key names: {0}".format(", ".join(map(str, bad))))
    desc = str(card.get("description", ""))
    if "description" in card and len(desc) < 20:
        probs.append("the description must say what the skill does and when to use it")
    if len(desc) > 1024:
        probs.append("the description is longer than 1024 characters")
    return probs


def find_skills(root: Path = ROOT) -> List[Dict[str, Any]]:
    """Every skill in <root>/skills/<area>/<name>/SKILL.md, with its header and any problems.
    Folders that start with "_" (like this kit) are not skills."""
    out = []
    base = Path(root) / "skills"
    if not base.is_dir():
        return out
    for skill_md in sorted(base.glob("*/*/SKILL.md")):
        folder = skill_md.parent
        if folder.name.startswith("_") or folder.parent.name.startswith("_"):
            continue
        card = parse_frontmatter(skill_md.read_text(errors="ignore"))
        out.append(
            {
                "folder": folder,
                "card": card,
                "name": card.get("name") or folder.name,
                "problems": card_problems(card, folder),
            }
        )
    for stray in sorted(base.glob("*/SKILL.md")):
        out.append({"folder": stray.parent, "card": {}, "name": stray.parent.name,
                    "problems": ["a skill must sit in skills/<fulfilment|owner|global>/<name>/"]})
    return out


def can_run(area: str, access: str) -> bool:
    """The role rule the connector checks: skills/owner/ is for Owners and Admins only;
    skills/fulfilment/ and skills/global/ are for everyone on the team."""
    if area == "owner":
        return access in ("Owner", "Admin")
    return area in ("fulfilment", "global")


def list_skills(root: Path = ROOT, access: str = "Owner") -> List[Dict[str, Any]]:
    """The skills one person may run, for the connector's skills.list. Broken skills are left out."""
    rows = []
    for s in find_skills(root):
        card = s["card"]
        if s["problems"] or not can_run(card.get("area", ""), access):
            continue
        rows.append(
            {
                "id": "{0}/{1}".format(card["area"], card["name"]),
                "name": card["name"],
                "description": card["description"],
                "area": card["area"],
                "agency": card["agency"],
                "needs": card["needs"],
                "runs_on": card["runs_on"],
            }
        )
    return rows


# --------------------------------------------------------------------------- keys


class MissingKey(RuntimeError):
    """A key the skill needs is not in .env. The message says where to get it."""


def load_dotenv(path: Optional[Path] = None) -> None:
    """Values from the repo's .env into the environment. Values already set win. Never prints one."""
    p = Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k.strip() and v:
            os.environ.setdefault(k.strip(), v)


def need(keys: Sequence[str], where: Optional[Dict[str, str]] = None) -> None:
    """Stop (MissingKey) if any key is empty. Names only, never values."""
    where = where or {}
    missing = [k for k in keys if not (os.environ.get(k) or "").strip()]
    if not missing:
        return
    lines = ["This skill stops: {0} missing from .env.".format("a key is" if len(missing) == 1 else "keys are")]
    for k in missing:
        lines.append("- {0}: get it from {1}. Add it to .env as {0}=<value> (no spaces around =).".format(
            k, where.get(k, "the tool's settings page")))
    lines.append("Then run the skill again.")
    raise MissingKey("\n".join(lines))


# --------------------------------------------------------------------------- Slack and channels


class Channels:
    """The automation channels from apps/os/automations/channels.json. Same `channel_id`
    as the automations' own Config, so a skill takes either."""

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        if data is None:
            f = ROOT / "apps/os/automations/channels.json"
            data = json.loads(f.read_text()) if f.exists() else {"channels": {}}
        self.channels = data

    def channel_id(self, key: str) -> str:
        entry = self.channels.get("channels", {}).get(key) or {}
        return (entry.get("id") or "").strip()


class Slack:
    """Posts through shared/slack_notify.py, the one Slack sender. Same `post` as the automations'."""

    def post(self, channel: str, bot_name: str, text: str, blocks: Optional[list] = None,
             thread_ts: Optional[str] = None) -> str:
        _put_root_on_path()
        from shared.slack_notify import post_message

        return post_message(channel, bot_name, text, blocks=blocks, thread_ts=thread_ts).get("ts", "")


class Context:
    def __init__(self, db: Any, slack: Any, config: Any, seen: Optional[MutableMapping[str, Any]] = None) -> None:
        self.db = db
        self.slack = slack
        self.config = config
        self.seen = seen if seen is not None else {}

    def settings(self) -> Dict[str, Any]:
        try:
            return self.db.get("settings", "1") or {}
        except Exception:  # noqa: BLE001 - links are a nice-to-have
            return {}


def context(needs: Sequence[str] = (), where: Optional[Dict[str, str]] = None, db: bool = True) -> Context:
    """Read .env, check the keys, and build the database and Slack for a local run."""
    load_dotenv()
    keys = list(needs)
    if db:
        keys = ["SUPABASE_URL", "SUPABASE_SECRET_KEY"] + [k for k in keys if k not in ("SUPABASE_URL", "SUPABASE_SECRET_KEY")]
    w = {"SUPABASE_URL": "Supabase, Project Settings, Data API (tab 1)",
         "SUPABASE_SECRET_KEY": "Supabase, Project Settings, API Keys, secret key (tab 1)",
         "SLACK_BOT_TOKEN": "api.slack.com/apps, your app, OAuth & Permissions (tab 3)"}
    w.update(where or {})
    need(keys, w)
    _put_root_on_path()
    database = None
    if db:
        from shared.supabase_client import Supabase

        database = Supabase()
    return Context(database, Slack(), Channels())


def os_link(settings: Dict[str, Any], path: str) -> str:
    """A link into the OS (settings.os_url + path), or "" when the OS address is not set."""
    base = (settings.get("os_url") or "").strip().rstrip("/")
    if not base:
        return ""
    if not base.startswith("http"):
        base = "https://" + base
    return base + "/" + path.lstrip("/")


def card_link(settings: Dict[str, Any], board: str, row_id: str) -> str:
    return os_link(settings, "board/{0}/{1}".format(board, row_id))


def post(ctx: Context, channel_key: str, bot_name: str, text: str, link: str = "", button: str = "Open the card") -> str:
    """One post in an automation channel, with an optional link button. Returns the message
    time stamp, or "" if the channel is not set up (then nothing is posted)."""
    channel = ctx.config.channel_id(channel_key)
    if not channel:
        return ""
    blocks = None
    if link:
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": button}, "url": link}]},
        ]
    return ctx.slack.post(channel, bot_name, text, blocks=blocks)


def first_time(seen: Optional[MutableMapping[str, Any]], key: str, hours: float = 24) -> bool:
    """True the first time `key` is seen in `hours` hours, and remembers it."""
    if seen is None:
        return True
    now = time.time()
    try:
        last = seen.get(key)
    except Exception:  # noqa: BLE001
        last = None
    if last and now - float(last) < hours * 3600:
        return False
    try:
        seen[key] = now
    except Exception:  # noqa: BLE001
        pass
    return True


def report_failure(ctx: Context, skill: str, step: str, error: BaseException, record_link: str = "") -> None:
    """One post in pipeline-errors, with the record and the error. The same failure once a day at most."""
    key = "error:skill:{0}:{1}:{2}".format(skill, step, str(error))[:200]
    if not first_time(ctx.seen, key):
        return
    lines = ["*Skill:* {0}".format(skill), "*Step:* {0}".format(step),
             "*Error:* {0}: {1}".format(type(error).__name__, str(error)[:300])]
    if record_link:
        lines.append("*Record:* <{0}|[LINK]>".format(record_link))
    lines.append("_Nothing after this step ran. Fix the cause, then run the skill again: it picks up where it stopped._")
    try:
        post(ctx, "pipeline-errors", ERROR_BOT, "\n".join(lines))
    except Exception:  # noqa: BLE001 - never let the error report hide the error
        traceback.print_exc()


# --------------------------------------------------------------------------- batches


def batches(rows: Iterable[Any], size: int = BATCH_MAX) -> Iterator[List[Any]]:
    """Groups of at most `size` (never more than 500) rows."""
    size = max(1, min(int(size), BATCH_MAX))
    group: List[Any] = []
    for r in rows:
        group.append(r)
        if len(group) == size:
            yield group
            group = []
    if group:
        yield group


def run_in_batches(
    todo: Callable[[int], List[Dict[str, Any]]],
    work: Callable[[List[Dict[str, Any]]], int],
    size: int = BATCH_MAX,
    max_batches: Optional[int] = None,
) -> Dict[str, int]:
    """Resume by design: `todo(limit)` reads the next rows NOT done yet (a column still empty),
    `work(rows)` does them and writes each result back. A crash loses at most the batch in
    hand; the next run reads only what is still not done. Stops when `todo` returns nothing,
    when a batch did no work (so it never loops), or after `max_batches`."""
    size = max(1, min(int(size), BATCH_MAX))
    done = runs = 0
    while max_batches is None or runs < max_batches:
        rows = todo(size)
        if not rows:
            break
        n = work(rows)
        runs += 1
        done += n
        if n == 0:
            break
    return {"batches": runs, "done": done}


# --------------------------------------------------------------------------- the spend gate


class NotApproved(RuntimeError):
    """A step that spends money ran before a person approved it."""


def approval(db: Any, board: str, row_id: str, approval_stage: str) -> Optional[Dict[str, Any]]:
    """The approval fact: the stage log row where a PERSON moved the card out of
    `approval_stage` to a later stage. None if nobody has. A move made by an automation
    (no person on the row) does not count."""
    rows = db.select("stage_log", {"board": "eq." + board, "record_id": "eq." + row_id,
                                   "from_stage": "eq." + approval_stage}, order="changed_at.desc")
    for r in rows or []:
        if r.get("changed_by_id") and _stage_no(r.get("to_stage")) > _stage_no(approval_stage):
            return r
    return None


def require_approval(db: Any, board: str, row_id: str, approval_stage: str) -> Dict[str, Any]:
    fact = approval(db, board, row_id, approval_stage)
    if not fact:
        raise NotApproved(
            "Nobody has approved this spend. A person must move the card out of '{0}' in the OS first.".format(
                approval_stage))
    return fact


def ask_for_approval(ctx: Context, title: str, lines: List[str], link: str) -> str:
    """The Slack post that asks for a spend: what it buys, what it costs, and how to approve
    (move the card on). Goes to the review channel, never a client channel."""
    text = "*{0}*\n{1}\n_To approve, open the card and move it to the next stage. Nothing is bought before that._".format(
        title, "\n".join(lines))
    return post(ctx, "review", APPROVAL_BOT, text, link=link)


def _stage_no(stage: Any) -> int:
    m = re.match(r"^\s*(\d+)", str(stage or ""))
    return int(m.group(1)) if m else -1


# --------------------------------------------------------------------------- AI judgement

AI_URL = "https://api.anthropic.com/v1/messages"
AI_VERSION = "2026-10-21"
AI_DEFAULT_MODEL = "claude-haiku-5-5"
AI_WHERE = {"ANTHROPIC_API_KEY": "console.anthropic.com, Settings, API Keys"}


class AIError(RuntimeError):
    """The AI call failed or declined. The message says why in plain words."""


def ask_ai(prompt: str, system: str = "", schema: Optional[Dict[str, Any]] = None, max_tokens: int = 2000,
           effort: str = "low", model: Optional[str] = None, timeout: int = 120) -> Any:
    """One Claude call for a judgement (classify, score, rewrite). With `schema`, the answer is
    JSON that matches it and comes back as a dict. Without, it comes back as text.

    Raw HTTP on purpose: this repo is standard-library Python 3.9, and the Anthropic SDK needs
    3.10. The model is AI_MODEL in .env, or Claude Haiku 5.5 (the low-cost model) when it is
    empty. The agency pays for every call. Set AI_MODEL to a larger model (for example
    claude-sonnet-5-5) only for a skill that needs harder judgement.
    """
    import urllib.error
    import urllib.request

    need(["ANTHROPIC_API_KEY"], AI_WHERE)
    body: Dict[str, Any] = {
        "model": model or os.environ.get("AI_MODEL") or AI_DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {"effort": effort},
    }
    if system:
        body["system"] = system
    if schema:
        body["output_config"]["format"] = {"type": "json_schema", "schema": schema}
    headers = {"content-type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"],
               "anthropic-version": AI_VERSION}
    if body["model"] in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-2"):
        # If a safety check declines, the server tries a fallback model by itself.
        body["fallbacks"] = "default"
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
    req = urllib.request.Request(AI_URL, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        raise AIError("The AI call failed ({0}): {1}".format(e.code, detail))
    except urllib.error.URLError as e:
        raise AIError("The AI service could not be reached: {0}".format(e.reason))
    if out.get("stop_reason") == "refusal":
        raise AIError("The AI declined this item. Check it by hand.")
    text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    if out.get("stop_reason") == "max_tokens":
        raise AIError("The AI answer was cut off. Raise max_tokens.")
    if schema:
        try:
            return json.loads(text)
        except ValueError:
            raise AIError("The AI answer was not valid JSON.")
    return text


# --------------------------------------------------------------------------- the daily hook


def daily_skills(root: Path = ROOT) -> List[Dict[str, Any]]:
    """Skills whose header says `daily: true`. Each has scripts/daily.py with
    run(db, slack, config, seen, today) -> dict."""
    return [s for s in find_skills(root) if not s["problems"] and s["card"].get("daily") is True
            and (s["folder"] / "scripts/daily.py").exists()]


def run_daily_skills(db: Any, slack: Any, config: Any, seen: Optional[MutableMapping[str, Any]] = None,
                     today: Optional[date] = None, root: Path = ROOT) -> Dict[str, Any]:
    """Called once a day by the existing daily job (no new schedule). One skill failing is
    posted once to pipeline-errors and does not stop the others."""
    import importlib.util

    today = today or date.today()
    ctx = Context(db, slack, config, seen)
    results: Dict[str, Any] = {}
    for s in daily_skills(root):
        name = s["card"]["name"]
        try:
            spec = importlib.util.spec_from_file_location("skill_daily_" + name.replace("-", "_"),
                                                          str(s["folder"] / "scripts/daily.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            results[name] = mod.run(db, slack, config, seen, today)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            report_failure(ctx, name, "daily run", e)
            results[name] = {"ok": False, "error": str(e)[:200]}
    return results


def find_skill(name: str, root: Path = ROOT) -> Optional[Dict[str, Any]]:
    for s in find_skills(root):
        if s["card"].get("name") == name and not s["problems"]:
            return s
    return None


def run_skill(name: str, args: Optional[Dict[str, Any]], db: Any, slack: Any, config: Any,
              seen: Optional[MutableMapping[str, Any]] = None, where: str = "modal",
              root: Path = ROOT) -> Dict[str, Any]:
    """Run one skill's scripts/run.py `run(ctx, **args)`. The automations app calls this from
    its one `run_skill` function and its /skill/<name> address, so a new skill on Modal needs
    no new app, no new function and no new schedule. A skill marked `runs_on: local` is refused
    on the server."""
    import importlib.util

    s = find_skill(name, root)
    if not s:
        return {"ok": False, "error": "No skill named '{0}' (or its header has a problem).".format(name)}
    if where == "modal" and s["card"].get("runs_on") == "local":
        return {"ok": False, "error": "'{0}' runs only on a computer (runs_on: local).".format(name)}
    script = s["folder"] / "scripts/run.py"
    if not script.exists():
        return {"ok": False, "error": "'{0}' has no scripts/run.py. An AI follows its SKILL.md instead.".format(name)}
    ctx = Context(db, slack, config, seen)
    try:
        spec = importlib.util.spec_from_file_location("skill_run_" + name.replace("-", "_"), str(script))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        out = mod.run(ctx, **(args or {}))
        return out if isinstance(out, dict) else {"ok": True, "result": out}
    except (MissingKey, NotApproved, ValueError) as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        report_failure(ctx, name, "run", e)
        return {"ok": False, "error": "{0}: {1}".format(type(e).__name__, str(e)[:200])}


def main_guard(fn: Callable[[], int]) -> None:
    """Run a skill's main(). A MissingKey or NotApproved prints its plain message and exits 2."""
    try:
        sys.exit(fn())
    except (MissingKey, NotApproved) as e:
        print(str(e))
        sys.exit(2)


def now_iso() -> str:
    """Now, in UTC, as the database writes it."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


__all__ = [
    "AIError", "ask_ai", "AREAS", "AGENCIES", "RUNS_ON", "FIELDS", "BATCH_MAX", "Channels", "Context", "MissingKey",
    "NotApproved", "Slack", "approval", "ask_for_approval", "batches", "can_run", "card_link",
    "card_problems", "context", "daily_skills", "find_skills", "first_time", "list_skills",
    "load_dotenv", "main_guard", "now_iso", "need", "os_link", "parse_frontmatter", "post", "report_failure",
    "find_skill", "require_approval", "run_daily_skills", "run_skill", "run_in_batches",
]
