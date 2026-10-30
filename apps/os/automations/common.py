"""What every automation shares: the two settings files, OS links, Slack, people and errors.

Nothing here imports Modal, so every part can be tested on a laptop with fakes:
`db` is anything with the `shared.supabase_client.Supabase` methods, `slack` is a
`Slack` (or a fake with the same `post` and `call`), and `seen` is any dict-like store
(a Modal Dict in the app, a plain dict in tests).
"""

from __future__ import annotations

import json
import re
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, MutableMapping, Optional

HERE = Path(__file__).resolve().parent
RULES_FILE = HERE / "alert_rules.json"
CHANNELS_FILE = HERE / "channels.json"

ERROR_BOT = "🚨 Automation Failed"
PERSON_BOT = "🙋 Needs A Person"
ONCE_HOURS = 24


# --------------------------------------------------------------------------- config


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())


class Config:
    """alert_rules.json (which stage move posts where) + channels.json (the channel ids)."""

    def __init__(self, rules: Dict[str, Any], channels: Dict[str, Any]) -> None:
        self.rules = rules
        self.channels = channels

    @classmethod
    def load(cls, rules_file: Path = RULES_FILE, channels_file: Path = CHANNELS_FILE) -> "Config":
        return cls(load_json(rules_file), load_json(channels_file))

    @property
    def boards(self) -> Dict[str, Dict[str, Any]]:
        return self.rules.get("boards", {})

    def board_label(self, board: str) -> str:
        return self.boards.get(board, {}).get("label") or board.replace("_", " ").title()

    def channel_id(self, key: str) -> str:
        """The Slack id for a channel key ("review", "pipeline-errors"). "" if not set up."""
        entry = self.channels.get("channels", {}).get(key) or {}
        return (entry.get("id") or "").strip()

    def review_stages(self) -> Dict[str, List[str]]:
        """Per board, the stages whose alert goes to the review channel."""
        out: Dict[str, List[str]] = {}
        for rule in self.rules.get("rules", []):
            if rule.get("channel") == "review":
                for board in self.boards if rule.get("board") == "*" else [rule.get("board")]:
                    out.setdefault(board, []).extend(rule.get("to", []))
        return out


# --------------------------------------------------------------------------- settings and links


def os_base(settings: Dict[str, Any]) -> str:
    url = (settings.get("os_url") or "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def card_link(settings: Dict[str, Any], board: str, row_id: str) -> str:
    base = os_base(settings)
    return "{0}/board/{1}/{2}".format(base, board, row_id) if base else ""


def client_link(settings: Dict[str, Any], client_id: str) -> str:
    base = os_base(settings)
    return "{0}/clients/{1}".format(base, client_id) if base else ""


def form_link(settings: Dict[str, Any], client: Dict[str, Any]) -> str:
    base = (settings.get("onboarding_url") or "").strip().rstrip("/")
    if not base or not client.get("form_code"):
        return ""
    if not base.startswith("http"):
        base = "https://" + base
    from urllib.parse import quote

    return "{0}/form/{1}?company_name={2}".format(base, client["form_code"], quote(client.get("client_name") or ""))


def read_settings(db: Any) -> Dict[str, Any]:
    return db.get("settings", "1") or {}


def is_archived(row: Optional[Dict[str, Any]]) -> bool:
    """An archived client or card (archived_at is set). It gets no alerts and is left out
    of the daily summary. Nothing is ever deleted; "Restore" brings it back."""
    return bool((row or {}).get("archived_at"))


def friendly_date(value: Any) -> str:
    """'2026-11-03' -> 'Nov 3 2026'. Empty stays empty."""
    if not value:
        return ""
    try:
        d = value if isinstance(value, date) else datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return str(value)
    return "{0} {1} {2}".format(d.strftime("%b"), d.day, d.year)


def stage_number(stage: Optional[str]) -> Optional[int]:
    m = re.match(r"\s*(-?\d+)", stage or "")
    return int(m.group(1)) if m else None


def button(label: str, url: str) -> Dict[str, Any]:
    return {
        "type": "actions",
        "elements": [{"type": "button", "text": {"type": "plain_text", "text": label}, "url": url}],
    }


def section(text: str) -> Dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


# --------------------------------------------------------------------------- Slack


class Slack:
    """The real Slack, through shared/slack_notify.py. Tests pass a fake with the same two methods."""

    def post(
        self, channel: str, bot_name: str, text: str, blocks: Optional[list] = None, thread_ts: Optional[str] = None
    ) -> str:
        from shared.slack_notify import post_message

        return post_message(channel, bot_name, text, blocks=blocks, thread_ts=thread_ts).get("ts", "")

    def call(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from shared.slack_notify import call

        return call(method, payload)


# --------------------------------------------------------------------------- people


class People:
    """Team rows by id, and Slack tags that name each person once per message.

    The first time a person is named, they are tagged (their phone buzzes). After that,
    only their name is written. A person with no Slack id is named, never tagged.
    """

    def __init__(self, team_rows: Iterable[Dict[str, Any]]) -> None:
        self.by_id = {r["id"]: r for r in team_rows if r.get("id")}
        self.tagged: set = set()

    @classmethod
    def load(cls, db: Any) -> "People":
        return cls(db.select_all("team", columns="id,full_name,email,access,status,slack_user_id"))

    def name(self, team_id: Optional[str]) -> str:
        row = self.by_id.get(team_id or "")
        return (row or {}).get("full_name") or ""

    def slack_id(self, team_id: Optional[str]) -> str:
        return ((self.by_id.get(team_id or "") or {}).get("slack_user_id") or "").strip()

    def tag(self, team_id: Optional[str]) -> str:
        if not team_id or team_id not in self.by_id:
            return ""
        sid = self.slack_id(team_id)
        if sid and team_id not in self.tagged:
            self.tagged.add(team_id)
            return "<@{0}>".format(sid)
        return self.name(team_id)

    def owners(self) -> List[str]:
        return [
            i for i, r in self.by_id.items() if r.get("access") == "Owner" and r.get("status", "Active") == "Active"
        ]


# --------------------------------------------------------------------------- once-only posts


def first_time(seen: Optional[MutableMapping[str, Any]], key: str, hours: int = ONCE_HOURS) -> bool:
    """True the first time `key` is seen in `hours` hours, and remembers it."""
    if seen is None:
        return True
    now = time.time()
    try:
        last = seen.get(key)
    except Exception:
        last = None
    if last and now - float(last) < hours * 3600:
        return False
    try:
        seen[key] = now
    except Exception:
        pass
    return True


def report_failure(
    slack: Any,
    config: Config,
    seen: Optional[MutableMapping[str, Any]],
    job: str,
    step: str,
    error: BaseException,
    record_link: str = "",
    what_to_do: str = "",
) -> None:
    """Post one message in pipeline-errors. The same failure is posted once a day at most.
    If even that post fails, stay silent: the team still has the board."""
    reason = getattr(error, "code", "") or str(error)
    key = "error:{0}:{1}:{2}".format(job, step, reason)[:200]
    if not first_time(seen, key):
        return
    lines = [
        "*Name:* {0}".format(job),
        "*Step:* {0}".format(step),
        "",
        "*Error:* {0}: {1}".format(type(error).__name__, str(error)[:300]),
    ]
    if record_link:
        lines += ["", "*Record:* <{0}|[LINK]>".format(record_link)]
    lines += [
        "",
        "_{0} This message is posted once a day at most, however often it fails. <!here>_".format(
            what_to_do
            or "This step was skipped, so nobody was told. Open the record and tell the right person yourself."
        ),
    ]
    channel = config.channel_id("pipeline-errors")
    if not channel:
        return
    try:
        slack.post(channel, ERROR_BOT, "\n".join(lines))
    except Exception:
        traceback.print_exc()


def needs_a_person(
    slack: Any,
    config: Config,
    seen: Optional[MutableMapping[str, Any]],
    key: str,
    text: str,
    link: str = "",
    link_label: str = "Open it in the OS",
) -> None:
    """Post once (a day) in needs-a-person: something only a person can fix."""
    if not first_time(seen, "person:" + key):
        return
    channel = config.channel_id("needs-a-person")
    if not channel:
        return
    blocks = [section(text)]
    if link:
        blocks.append(button(link_label, link))
    try:
        slack.post(channel, PERSON_BOT, text, blocks=blocks)
    except Exception:
        traceback.print_exc()
