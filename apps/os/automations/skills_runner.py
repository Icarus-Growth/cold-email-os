"""The automations' door to the team's skills (skills/_kit/skillkit.py, the skills kit).

On Modal the skills folder is at /app/skills; on a computer it is the repo's skills/. Before the
repo has the kit, every answer here is a plain "not set up", never a crash, so the daily summary
and the rest of the app keep working.
"""

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT_PLACES = [Path("/app/skills/_kit"), HERE.parents[2] / "skills" / "_kit" if len(HERE.parents) > 2 else HERE]
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
NOT_SET_UP = "The skills kit (skills/_kit/skillkit.py) is not in this deploy. Add the skills folder, then deploy again."


def kit():
    """The skillkit module, or None when this repo has no skills kit yet."""
    if "skillkit" in sys.modules:
        return sys.modules["skillkit"]
    for folder in KIT_PLACES:
        f = folder / "skillkit.py"
        if f.is_file():
            spec = importlib.util.spec_from_file_location("skillkit", str(f))
            mod = importlib.util.module_from_spec(spec)
            sys.modules["skillkit"] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                del sys.modules["skillkit"]
                raise
            return mod
    return None


def check(name):
    """None if the skill can be started on the server, else the reason it cannot."""
    if not NAME.match(name or ""):
        return "A skill name is lower case letters, numbers and '-' only."
    k = kit()
    if k is None:
        return NOT_SET_UP
    s = k.find_skill(name)
    if not s:
        return "No skill named '{0}' (or its header has a problem).".format(name)
    if s["card"].get("runs_on") == "local":
        return "'{0}' runs only on a computer (runs_on: local).".format(name)
    if not (s["folder"] / "scripts" / "run.py").exists():
        return "'{0}' has no scripts/run.py. An AI follows its SKILL.md instead.".format(name)
    return None


def run_skill(name, args, db, slack, config, seen):
    k = kit()
    if k is None:
        return {"ok": False, "error": NOT_SET_UP}
    return k.run_skill(name, args or {}, db, slack, config, seen, where="modal")


def run_daily_skills(db, slack, config, seen, today=None):
    """Once a day, inside the daily summary job (no new schedule). A second summary on the same
    day (the button, or a hand run) does not run them again."""
    today = today or date.today()
    k = kit()
    if k is None:
        return {"skipped": "no skills kit"}
    key = "daily-skills:{0}".format(today.isoformat())
    if seen is not None and key in seen:
        return {"skipped": "already ran today"}
    if seen is not None:
        seen[key] = True
    return k.run_daily_skills(db, slack, config, seen, today=today)
