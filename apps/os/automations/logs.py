"""The automations app's log from Modal, with every AI connector link hidden.

Modal writes the address of each web request in its log. A person whose AI tool takes only an
address (claude.ai) uses an /mcp/s/<token>/ link, so that token is in Modal's log. This prints
the log with each token replaced by ***, so it can be read in a chat without giving the link away.

    python3 apps/os/automations/logs.py            the log, as `modal app logs` gives it
    python3 apps/os/automations/logs.py --help     Modal's own options pass through

Standard library only, Python 3.9.
"""

from __future__ import annotations

import re
import subprocess
import sys

APP = "agency-os-automations"
_LINK = re.compile(r"(/mcp/s/)[^/\s?\"']+")
_BEARER = re.compile(r"(?i)(bearer\s+)[^\s\"',]+")


def mask(line: str) -> str:
    """Hide connector tokens in one log line. Pure."""
    return _BEARER.sub(r"\1***", _LINK.sub(r"\1***", line))


def main(args: list) -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "modal", "app", "logs", APP, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            sys.stdout.write(mask(line))
            sys.stdout.flush()
    except KeyboardInterrupt:
        proc.terminate()
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
