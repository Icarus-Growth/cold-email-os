#!/usr/bin/env python3
"""Check questions.json against what the form engine reads.

    python3 apps/onboarding/tools/validate_questions.py
    python3 apps/onboarding/tools/validate_questions.py path/to/questions.json

Why it exists: a question file can say something the page does not read (a
type it cannot draw, an option list on a text box, a show_if that waits for an
answer that can never come). The page then breaks for the client, and no
server test sees it. tools/deploy.py runs this check first and will not deploy
a file that fails it.

Every rule below matches a line in site/form/app.js or worker/worker.js. If
you change one of those, change the rule with it.
"""

import json
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
DEFAULT = APP / "questions.json"

# app.js fieldNode(): the kinds of question it can draw.
TYPES = {"short_text", "long_text", "email", "url", "number", "single_select", "multi_select", "checkbox"}
SELECT_TYPES = {"single_select", "multi_select"}
TEXT_TYPES = {"short_text", "long_text", "email", "url", "number"}
# worker.js PUBLIC_KEYS: the only keys the page ever sees.
KNOWN_KEYS = {
    "step", "id", "label", "type", "required", "help", "placeholder", "rows", "options", "chips",
    "info", "prefill", "show_if", "option_help", "none_option", "links",
}
# The worker files these three by name (who sent the form, which company), and
# the form link's ?email=&company_name= fill them in.
MUST_HAVE = {"full_name": "short_text", "email": "email", "company_name": "short_text"}
# Keys, tokens and passwords are never stored in a table. The form never asks for one.
SECRET_WORDS = re.compile(r"\b(password|passcode|api key|api token|secret key|access token|private key)\b", re.I)
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def check(spec):
    errs, warns = [], []
    flow, steps = spec.get("flow") or [], spec.get("steps") or []

    if not isinstance(spec.get("form_key"), str) or not spec["form_key"].strip():
        errs.append("form_key must be a non-empty text")
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        errs.append("title must be a non-empty text")
    if [s.get("step") for s in steps] != list(range(1, len(steps) + 1)):
        errs.append("steps must be numbered 1..N with no gaps")
    for s in steps:
        if not s.get("title"):
            errs.append("step %r has no title" % s.get("step"))
    if len(steps) < 2:
        errs.append("there must be at least one page of questions and the review page")

    review = len(steps)
    ids = [q.get("id") for q in flow]
    by_id = {q.get("id"): q for q in flow}

    seen = set()
    for q in flow:
        qid = q.get("id", "?")
        where = "question %r" % qid
        if qid in seen:
            errs.append("%s: the id is used twice" % where)
        seen.add(qid)
        if not isinstance(qid, str) or not ID_RE.match(qid):
            errs.append("%s: the id must be lower case letters, numbers and _" % where)
        if q.get("type") not in TYPES:
            errs.append("%s: type %r is not one the page draws (%s)" % (where, q.get("type"), ", ".join(sorted(TYPES))))
            continue
        if not (isinstance(q.get("step"), int) and 1 <= q["step"] < review):
            errs.append("%s: step %r must be between 1 and %d" % (where, q.get("step"), review - 1))
        if not q.get("label"):
            errs.append("%s: no label" % where)
        for k in set(q) - KNOWN_KEYS:
            warns.append("%s: key %r is never read by the page" % (where, k))
        if not isinstance(q.get("required", False), bool):
            errs.append("%s: required must be true or false" % where)

        words = " ".join(str(q.get(k) or "") for k in ("label", "help", "placeholder"))
        if SECRET_WORDS.search(words):
            errs.append("%s: asks for a password or key. Never collect these in a form; ask the client "
                        "to invite you to the tool instead" % where)

        if q["type"] in SELECT_TYPES:
            opts = q.get("options")
            if not opts or not all(isinstance(o, str) and o.strip() for o in opts):
                errs.append("%s: a %s needs a list of options" % (where, q["type"]))
            elif len(set(opts)) != len(opts):
                errs.append("%s: an option is listed twice" % where)
            stray = set(q.get("option_help") or {}) - set(opts or [])
            if stray:
                errs.append("%s: option_help names options that do not exist: %s" % (where, sorted(stray)))
        elif q.get("options") or q.get("option_help"):
            warns.append("%s: options on a %s question are never shown" % (where, q["type"]))

        for c in q.get("chips") or []:
            if not (isinstance(c, str) or (isinstance(c, dict) and c.get("label"))):
                errs.append("%s: chip %r must be a text or {label, starter}" % (where, c))
        if q.get("chips") and q["type"] != "long_text":
            warns.append("%s: chips are only shown on long_text questions" % where)
        if q.get("rows") and q["type"] != "long_text":
            warns.append("%s: rows is only read on long_text questions" % where)

        if "info" in q:
            info = q["info"]
            if not (isinstance(info, dict) and info.get("title")):
                errs.append("%s: info needs a title (it is the button text)" % where)
            elif not (isinstance(info.get("items"), list) and info["items"]):
                errs.append("%s: info has no items, so the window would open empty" % where)

        for link in q.get("links") or []:
            if not (isinstance(link, dict) and link.get("label") and str(link.get("url", "")).startswith("http")):
                errs.append("%s: each link needs a label and a url that starts with http" % where)

        if "none_option" in q:
            none = q["none_option"]
            if not (isinstance(none, dict) and isinstance(none.get("label"), str) and none["label"].strip()
                    and isinstance(none.get("value"), str) and none["value"].strip()):
                errs.append("%s: none_option must be {label, value}, both non-empty text" % where)
            if q["type"] not in TEXT_TYPES:
                errs.append("%s: none_option is only shown under a text box" % where)

        cond = q.get("show_if")
        if cond:
            ctrl = by_id.get(cond.get("question"))
            if not ctrl:
                errs.append("%s: show_if points at an unknown question %r" % (where, cond.get("question")))
            elif not any(k in cond for k in ("equals", "equals_any", "includes")):
                errs.append("%s: show_if needs equals, equals_any or includes" % where)
            else:
                if ctrl.get("step", 0) > q.get("step", 0):
                    errs.append("%s: show_if waits for %r, which is on a LATER page" % (where, ctrl["id"]))
                if "includes" in cond:
                    vals = [cond["includes"]]
                    if ctrl.get("type") != "multi_select":
                        errs.append("%s: show_if uses includes, which is only for a multi_select" % where)
                else:
                    vals = cond.get("equals_any") or [cond.get("equals")]
                if ctrl.get("type") in SELECT_TYPES:
                    bad = [v for v in vals if v not in (ctrl.get("options") or [])]
                    if bad:
                        errs.append("%s: show_if waits for %s, which %r can never be" % (where, bad, ctrl["id"]))
                if ctrl.get("type") == "checkbox" and any(not isinstance(v, bool) for v in vals):
                    errs.append("%s: show_if on a yes/not yet question must wait for true or false" % where)

    for qid, kind in MUST_HAVE.items():
        q = by_id.get(qid)
        if not q:
            errs.append("question %r is missing. The form needs it (who sent the form, which company)" % qid)
        elif q.get("type") != kind or q.get("step") != 1 or not q.get("required"):
            errs.append("question %r must be a required %s on page 1" % (qid, kind))

    for s in range(1, review):
        if not [q for q in flow if q.get("step") == s]:
            errs.append("page %d has no questions" % s)

    intro = spec.get("intro")
    if intro is not None:
        if not isinstance(intro, dict):
            errs.append("intro must be {minutes, bring}")
        else:
            if "minutes" in intro and not (isinstance(intro["minutes"], int) and intro["minutes"] > 0):
                errs.append("intro.minutes must be a whole number")
            if "bring" in intro and not (isinstance(intro["bring"], list) and all(isinstance(b, str) for b in intro["bring"])):
                errs.append("intro.bring must be a list of texts")

    done = spec.get("done")
    if done is not None:
        if not isinstance(done, dict):
            errs.append("done must be {heading, blurb, next, links}")
        else:
            items = (done.get("next") or {}).get("items", [])
            if not (isinstance(items, list) and all(isinstance(i, str) for i in items)):
                errs.append("done.next.items must be a list of texts")
            for link in done.get("links") or []:
                if not (isinstance(link, dict) and "url" in link):
                    errs.append("each done.links entry needs a url (it may be empty to hide it)")

    if len(ids) > 80:
        warns.append("%d questions is a long form. Clients stop part-way through long forms" % len(ids))
    return errs, warns


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    try:
        spec = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        print("  ERROR cannot read %s: %s" % (path, e))
        return 1
    errs, warns = check(spec)
    for w in warns:
        print("  warn  " + w)
    for e in errs:
        print("  ERROR " + e)
    print("%s: %d questions, %d pages, %d error(s), %d warning(s)"
          % (path.name, len(spec.get("flow") or []), len(spec.get("steps") or []), len(errs), len(warns)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
