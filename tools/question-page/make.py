"""Make a question page from a JSON list of questions, and open it in the browser.

    python3 tools/question-page/make.py business                 a set in sets/ (business, second-brain, who-are-you)
    python3 tools/question-page/make.py path/to/my-questions.json  your own set (shape: README.md)
    python3 tools/question-page/make.py second-brain --choices "areas=Sales;Offers;Delivery"
    python3 tools/question-page/make.py business --no-open       make it, do not open it

The page is written to tools/question-page/out/<set>.html (git ignores that folder) and opened.
Nothing is sent anywhere: the answers stay in the browser until the person presses "Copy answers"
and pastes the text into the chat. Exit 1 with a plain message if the JSON is wrong.
"""

import argparse
import json
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETS = HERE / "sets"
OUT = HERE / "out"
TYPES = {"single", "multi", "text", "textarea"}
DESTS = {"about", "team", "decision", "brain", "chat"}


def load(name: str) -> dict:
    path = Path(name)
    if not path.suffix:
        path = SETS / (name + ".json")
    if not path.exists():
        known = ", ".join(sorted(p.stem for p in SETS.glob("*.json")))
        raise ValueError(f"There is no question set '{name}'. Use one of: {known}, or the path to a .json file.")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name} is not valid JSON: {e}")
    data.setdefault("id", path.stem)
    return data


def check(data: dict) -> list:
    """Every problem with the set, in plain words (empty = good)."""
    out = []
    if not str(data.get("title", "")).strip():
        out.append('The set needs a "title".')
    qs = data.get("questions")
    if not isinstance(qs, list) or not qs:
        return out + ['The set needs a "questions" list with at least one question.']
    seen = set()
    for i, q in enumerate(qs, start=1):
        where = f"Question {i}"
        qid = q.get("id")
        if not qid or not str(qid).replace("_", "").replace("-", "").isalnum():
            out.append(f'{where} needs an "id" made of letters, numbers, "-" or "_".')
        elif qid in seen:
            out.append(f'{where}: the id "{qid}" is used twice.')
        seen.add(qid)
        if not str(q.get("text", "")).strip():
            out.append(f'{where} needs a "text" (the question).')
        if q.get("dest") and q["dest"] not in DESTS:
            out.append(f'{where}: "dest" must be one of {", ".join(sorted(DESTS))}.')
        parts = q.get("parts")
        if not isinstance(parts, list) or not parts:
            out.append(f'{where} needs a "parts" list (the boxes to answer in).')
            continue
        keys = set()
        for p in parts:
            if p.get("type") not in TYPES:
                out.append(f'{where}: a part has type "{p.get("type")}". Use one of: {", ".join(sorted(TYPES))}.')
            if not p.get("k") or p["k"].startswith("_") or p["k"] in keys:
                out.append(f'{where}: each part needs its own "k" (a short name, not starting with "_").')
            keys.add(p.get("k"))
            if p.get("type") in ("single", "multi") and not (isinstance(p.get("opts"), list) and p["opts"]):
                out.append(f'{where}: a "{p["type"]}" part needs "opts" (the choices).')
    return out


def set_choices(data: dict, specs: list) -> None:
    """--choices "<question id>=<a;b;c>": replace the choices of that question's first choice part."""
    for spec in specs:
        qid, _, raw = spec.partition("=")
        opts = [x.strip() for x in raw.split(";") if x.strip()]
        q = next((q for q in data["questions"] if q.get("id") == qid.strip()), None)
        part = q and next((p for p in q["parts"] if p.get("type") in ("single", "multi")), None)
        if not part or not opts:
            raise ValueError(f'--choices "{spec}": no question "{qid}" with choices, or no choices given (use a;b;c).')
        part["opts"] = opts


def page(data: dict) -> str:
    template = (HERE / "page.html").read_text()
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    if "/*SET*/null" not in template:
        raise ValueError("page.html has lost its /*SET*/null mark. Get a fresh copy of tools/question-page/page.html.")
    return template.replace("/*SET*/null", blob, 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Make a question page and open it.")
    ap.add_argument("set", help="a set name in sets/, or a path to a .json file")
    ap.add_argument("--choices", action="append", default=[], help='"<question id>=<a;b;c>": the choices for one question')
    ap.add_argument("--out", default=str(OUT), help="the folder to write the page to")
    ap.add_argument("--no-open", action="store_true", help="make the page, do not open it")
    a = ap.parse_args(argv)
    try:
        data = load(a.set)
        set_choices(data, a.choices)
        problems = check(data)
        if problems:
            raise ValueError("The question set has problems:\n  - " + "\n  - ".join(problems))
        html = page(data)
    except ValueError as e:
        print(f"FAIL: {e}")
        return 1
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / (str(data["id"]) + ".html")
    target.write_text(html)
    print(f"Made the page: {target}")
    print(f'{len(data["questions"])} questions. The person answers, presses "Copy answers" and pastes the text into the chat.')
    if not a.no_open:
        opened = webbrowser.open(target.resolve().as_uri())
        print("Opened it in the browser." if opened else f"Could not open a browser. Ask the person to open this file: {target.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
