"""The entry the automation server calls (skillkit.run_skill): run(ctx, batch=..., live=False).
Each call moves the card as far as it can now and returns; it never sleeps, so it fits the
server's time limit. Call it again to go on."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _d in (HERE, HERE.parents[1] / "sending-estate-plan" / "scripts", HERE.parents[1] / "sending-domain-names" / "scripts"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import provision_estate  # noqa: E402,F401  (puts the kit on the path)
import sending_engine as engine  # noqa: E402


def run(ctx, batch, live=False, domains=None, now=False):
    only = [d for d in str(domains or "").split(",") if d.strip()] or None
    out = engine.provision(ctx, batch, live=bool(live), force=bool(now), only=only)
    return dict(out, summary=provision_estate.report(out))
