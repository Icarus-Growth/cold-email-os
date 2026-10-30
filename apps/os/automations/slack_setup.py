"""Set up Slack for the automations, from the repo root. Reads .env; never prints a key.

python3 apps/os/automations/slack_setup.py check
    The bot token works and has every permission the manifest asks for.
python3 apps/os/automations/slack_setup.py channels
    Every channel the bot can see, with its id.
python3 apps/os/automations/slack_setup.py make-channels
    Make (or find and join) every channel in channels.json, and save the ids there.
python3 apps/os/automations/slack_setup.py invite <channel key> <email> [<email> ...]
    Invite people to one automation channel, found by their email.
python3 apps/os/automations/slack_setup.py link-clients [--save] [--set "Client name=channel-name" ...]
    Match clients with no channel to the workspace's existing channels by name. Shows
    the match; --save writes the channel id and name on each client. It never makes a
    client channel, and nothing is ever posted in one.
python3 apps/os/automations/slack_setup.py link-team [--save]
    Find each team member in Slack by email. --save writes their Slack id.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from common import CHANNELS_FILE, load_json  # noqa: E402
from shared.slack_notify import SlackError, call, preflight  # noqa: E402
from shared.supabase_client import Supabase, load_dotenv  # noqa: E402

NEEDED = [
    "chat:write",
    "chat:write.customize",
    "channels:manage",
    "channels:read",
    "channels:join",
    "groups:read",
    "groups:write",
    "users:read",
    "users:read.email",
    "im:write",
]


def slug(text: str) -> str:
    """'Example Client A & Co.' -> 'example-client-a-co'. Slack channel names are
    lower case, with no spaces or dots."""
    s = re.sub(r"[^a-z0-9_-]+", "-", (text or "").lower())
    return re.sub(r"-{2,}", "-", s).strip("-_")


def save_channels(data: Dict[str, Any]) -> None:
    CHANNELS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def all_channels() -> List[Dict[str, Any]]:
    """Every channel the bot can see (public, and private ones it is in). Pages of 200, at most 20."""
    out: List[Dict[str, Any]] = []
    cursor = ""
    for _ in range(20):
        body: Dict[str, Any] = {"types": "public_channel,private_channel", "exclude_archived": True, "limit": 200}
        if cursor:
            body["cursor"] = cursor
        res = call("conversations.list", body)
        out.extend(res.get("channels", []))
        cursor = (res.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return out


def cmd_check() -> int:
    info = preflight()
    if not info["ok"]:
        print("FAIL: the bot token does not work ({0}). Copy the Bot User OAuth Token again.".format(info["error"]))
        return 1
    missing = [s for s in NEEDED if s not in info["scopes"]]
    print("Bot: {0} in workspace {1}".format(info["bot"], info["workspace"]))
    if missing:
        print(
            "FAIL: missing permissions: {0}. Paste the manifest again and reinstall the app.".format(", ".join(missing))
        )
        return 1
    print(
        "PASS: every permission is there. Logo address: {0}".format(
            info["icon_url"] or "(not set yet, the app icon is used)"
        )
    )
    return 0


def cmd_channels() -> int:
    for ch in sorted(all_channels(), key=lambda c: c["name"]):
        print(
            "{0:<40} {1}  {2}{3}".format(
                ch["name"],
                ch["id"],
                "private" if ch.get("is_private") else "public",
                "" if ch.get("is_member") else "  (bot not in it)",
            )
        )
    return 0


def cmd_make_channels(private: bool) -> int:
    data = load_json(CHANNELS_FILE)
    existing = {c["name"]: c for c in all_channels()}
    bad = 0
    for key, entry in data["channels"].items():
        name = slug(entry.get("name") or key)
        found = existing.get(name)
        if found:
            if not found.get("is_member"):
                if found.get("is_private"):
                    print(
                        "STOP: #{0} is private and the bot is not in it. In Slack, open it and type /invite @<the app>.".format(
                            name
                        )
                    )
                    bad += 1
                    continue
                call("conversations.join", {"channel": found["id"]})
            entry["id"], entry["name"] = found["id"], name
            print("found  #{0}  {1}".format(name, found["id"]))
        else:
            res = call("conversations.create", {"name": name, "is_private": private})
            entry["id"], entry["name"] = res["channel"]["id"], res["channel"]["name"]
            print("made   #{0}  {1}".format(entry["name"], entry["id"]))
    save_channels(data)
    print("Saved the ids in {0}.".format(CHANNELS_FILE.relative_to(REPO)))
    return 1 if bad else 0


def lookup(email: str) -> Optional[str]:
    try:
        return call("users.lookupByEmail", {"email": email.strip().lower()})["user"]["id"]
    except SlackError as e:
        if e.code == "users_not_found":
            return None
        raise


def cmd_invite(key: str, emails: List[str]) -> int:
    channel = (load_json(CHANNELS_FILE)["channels"].get(key) or {}).get("id")
    if not channel:
        print("FAIL: no channel '{0}' with an id in channels.json. Run make-channels first.".format(key))
        return 1
    ids = []
    for email in emails:
        uid = lookup(email)
        print("{0:<40} {1}".format(email, uid or "NOT FOUND in Slack"))
        if uid:
            ids.append(uid)
    if ids:
        call("conversations.invite", {"channel": channel, "users": ",".join(ids), "force": True})
        print("Invited {0} to #{1}.".format(len(ids), key))
    return 0


def match_clients(
    clients: List[Dict[str, Any]], channels: List[Dict[str, Any]], fixes: Dict[str, str]
) -> List[Dict[str, Any]]:
    """For each client, the channel whose name holds the client's name. Pure."""
    by_name = {c["name"]: c for c in channels}
    out = []
    for cl in clients:
        fixed = fixes.get(cl["client_name"].lower())
        if fixed is not None:
            hit = by_name.get(slug(fixed))
        else:
            key = slug(cl["client_name"])
            hits = [c for c in channels if key and key in c["name"]]
            hits.sort(key=lambda c: len(c["name"]))
            hit = hits[0] if hits else None
        out.append({"client": cl, "channel": hit})
    return out


def cmd_link_clients(save: bool, sets: List[str]) -> int:
    db = Supabase()
    fixes = {}
    for s in sets:
        name, _, channel = s.partition("=")
        fixes[name.strip().lower()] = channel.strip().lstrip("#")
    clients = db.select_all("clients", {"slack_channel_id": "is.null"}, columns="id,client_name", order="client_name")
    for m in match_clients(clients, all_channels(), fixes):
        ch = m["channel"]
        print("{0:<35} -> {1}".format(m["client"]["client_name"], "#" + ch["name"] if ch else "NO MATCH"))
        if save and ch:
            db.update("clients", m["client"]["id"], {"slack_channel_id": ch["id"], "slack_channel_name": ch["name"]})
    print("Saved." if save else "Nothing saved yet. Check the list, then run again with --save.")
    return 0


def cmd_link_team(save: bool) -> int:
    db = Supabase()
    for person in db.select_all(
        "team", {"status": "eq.Active"}, columns="id,full_name,email,slack_user_id", order="full_name"
    ):
        if person.get("slack_user_id"):
            print("{0:<30} already linked".format(person["full_name"]))
            continue
        uid = lookup(person["email"])
        print("{0:<30} {1}".format(person["full_name"], uid or "NOT FOUND in Slack (" + person["email"] + ")"))
        if save and uid:
            db.update("team", person["id"], {"slack_user_id": uid})
    print("Saved." if save else "Nothing saved yet. Check the list, then run again with --save.")
    return 0


def main(argv: List[str]) -> int:
    load_dotenv(str(REPO / ".env"))
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "check":
            return cmd_check()
        if cmd == "channels":
            return cmd_channels()
        if cmd == "make-channels":
            return cmd_make_channels("--private" in rest)
        if cmd == "invite" and len(rest) >= 2:
            return cmd_invite(rest[0], rest[1:])
        if cmd == "link-clients":
            sets = [rest[i + 1] for i, a in enumerate(rest) if a == "--set" and i + 1 < len(rest)]
            return cmd_link_clients("--save" in rest, sets)
        if cmd == "link-team":
            return cmd_link_team("--save" in rest)
    except SlackError as e:
        print("FAIL: Slack said {0}.".format(e.code or e))
        return 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
