"""The agency's logo on every Slack post, from the repo root. Reads .env; never prints a key.

    python3 apps/os/automations/logo.py fetch youragency.com
        Get the logo for that domain from logo.dev as a 512 x 512 PNG, and save it at
        apps/os/frontend/public/slack-logo.png. Open the file to check it before you use it.
    python3 apps/os/automations/logo.py check https://app.youragency.com/slack-logo.png
        After the OS is deployed again: the address shows a PNG, so Slack can show it. A failed
        look waits 30 seconds and tries again, 3 times, before it says FAIL.

Slack needs a web address for the picture, not the picture itself. So the PNG is kept in
the OS app (it is published with the OS) and SLACK_ICON_URL holds its address.
"""

from __future__ import annotations

import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, List, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TARGET = REPO / "apps/os/frontend/public/slack-logo.png"
PNG = b"\x89PNG\r\n\x1a\n"


def read_key() -> str:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.split("=", 1)[0].strip() == "LOGO_DEV_PUBLISHABLE_KEY" and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def logo_url(domain: str, key: str) -> str:
    query = urllib.parse.urlencode({"token": key, "format": "png", "size": "512", "fallback": "404"})
    return "https://img.logo.dev/{0}?{1}".format(urllib.parse.quote(domain), query)


def clean_domain(text: str) -> str:
    """'https://www.YourAgency.com/about' -> 'youragency.com'."""
    d = re.sub(r"^[a-z]+://", "", text.strip().lower()).split("/")[0]
    return d[4:] if d.startswith("www.") else d


def cmd_fetch(domain: str) -> int:
    key = read_key()
    if not key:
        print("LOGO_DEV_PUBLISHABLE_KEY is empty in .env. Copy the publishable key from logo.dev into it.")
        return 1
    domain = clean_domain(domain)
    req = urllib.request.Request(logo_url(domain, key), headers={"User-Agent": "agency-os-logo"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(
                "logo.dev has no logo for {0}. Check the domain, or save your own square PNG at {1}.".format(
                    domain, TARGET.relative_to(REPO)
                )
            )
        else:
            print("logo.dev said {0}. Check LOGO_DEV_PUBLISHABLE_KEY is the publishable key.".format(e.code))
        return 1
    if not data.startswith(PNG):
        print("logo.dev did not send a PNG. Nothing saved.")
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(data)
    print("Saved {0} ({1} KB). Open it and check it is your logo.".format(TARGET.relative_to(REPO), len(data) // 1024))
    return 0


TRIES_AFTER_FIRST = 3
WAIT_SECONDS = 30


def check_once(url: str) -> Tuple[bool, str]:
    """(passed, what it saw) for one look at the address."""
    req = urllib.request.Request(url, headers={"User-Agent": "agency-os-logo"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(16)
            kind = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return False, "it answered {0}".format(e.code)
    except (urllib.error.URLError, OSError) as e:
        return False, "it could not be reached ({0})".format(getattr(e, "reason", e))
    if data.startswith(PNG):
        return True, kind
    return False, "it does not show a PNG ({0}); the OS may be sending its main page".format(kind or "no type")


def cmd_check(
    url: str,
    look: Callable[[str], Tuple[bool, str]] = check_once,
    wait: Callable[[float], None] = time.sleep,
) -> int:
    """A fresh deploy can take about a minute to show a new file. So a failed look waits 30
    seconds and looks again, 3 more times (about 90 seconds), before it fails."""
    for attempt in range(TRIES_AFTER_FIRST + 1):
        passed, seen = look(url)
        if passed:
            print("PASS: {0} shows the PNG ({1}). Put this address in SLACK_ICON_URL.".format(url, seen))
            return 0
        if attempt < TRIES_AFTER_FIRST:
            print(
                "Not yet: {0}. A new deploy can take a minute. Waiting {1} seconds, then trying again "
                "({2} of {3}).".format(seen, WAIT_SECONDS, attempt + 1, TRIES_AFTER_FIRST)
            )
            wait(WAIT_SECONDS)
    print(
        "FAIL: {0}: {1}, after {2} tries over about {3} seconds. Deploy the OS again (tab 2), "
        "then check again.".format(url, seen, TRIES_AFTER_FIRST + 1, TRIES_AFTER_FIRST * WAIT_SECONDS)
    )
    return 1


def main(argv: List[str]) -> int:
    if len(argv) == 2 and argv[0] == "fetch":
        return cmd_fetch(argv[1])
    if len(argv) == 2 and argv[0] == "check":
        return cmd_check(argv[1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
