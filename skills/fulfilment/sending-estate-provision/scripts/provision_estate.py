"""Set up an approved Inbox set-ups card: buy the domains, set the DNS, make the inboxes, start
the warm-up, and move the card on. A DRY RUN unless you add --live.

    python3 skills/fulfilment/sending-estate-provision/scripts/provision_estate.py --batch <card id>            dry run
    python3 skills/fulfilment/sending-estate-provision/scripts/provision_estate.py --batch <card id> --live     buys
    python3 skills/fulfilment/sending-estate-provision/scripts/provision_estate.py --batch <card id> --live --domains a.com,b.com
    python3 skills/fulfilment/sending-estate-provision/scripts/provision_estate.py --batch <card id> --live --now   check again now

It stops each domain at the first thing it must wait for (nameservers, inboxes being built,
14 days of warm-up). Run it again at any time: each domain goes on from its own status.
The daily job also runs it (without buying) for every card in stages 20, 30 and 40.
"""

import sys
from pathlib import Path

for _up in Path(__file__).resolve().parents:
    _kit = [k for k in (_up / "skills/_kit", _up / "core/skills/_kit") if (k / "skillkit.py").exists()]
    if _kit:
        sys.path.insert(0, str(_kit[0]))
        break
import skillkit  # noqa: E402

HERE = Path(__file__).resolve().parent
for _d in (HERE, HERE.parents[1] / "sending-estate-plan" / "scripts", HERE.parents[1] / "sending-domain-names" / "scripts"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import argparse  # noqa: E402
from typing import Any, Dict  # noqa: E402

import sending_engine as engine  # noqa: E402


def report(out: Dict[str, Any]) -> str:
    lines = ["{0} run of '{1}'. Card stage: {2}.".format("LIVE" if out["live"] else "DRY", out["batch_name"],
                                                           out["stage"])]
    for d in out["domains"]:
        why = d["error"] or d["waiting_for"] or "; ".join(d["notes"][-2:])
        lines.append("  {0:<30} {1:<16} {2:<8} {3}".format(d["domain"], d["status"], d["state"], (why or "")[:110]))
    counts: Dict[str, int] = {}
    for d in out["domains"]:
        counts[d["state"]] = counts.get(d["state"], 0) + 1
    lines.append("Domains: " + ", ".join("{0} {1}".format(v, k) for k, v in sorted(counts.items())) if counts
                 else "Every domain is ready. Nothing to do.")
    if not out["live"]:
        lines.append("Nothing was sent: {0} vendor calls were recorded, not made. Each domain row has a note "
                     "saying what a live run would do.".format(out["vendor_calls"]))
        if out["missing_keys"]:
            lines.append("A live run still needs these keys in .env: " + ", ".join(out["missing_keys"]))
        lines.append("To buy for real: add --live.")
    if out["link"]:
        lines.append("Card: " + out["link"])
    return "\n".join(lines)


def main(argv: Any = None) -> int:
    ap = argparse.ArgumentParser(description="Set up an approved Inbox set-ups card (a dry run unless --live).")
    ap.add_argument("--batch", required=True, help="the Inbox set-ups card's row id")
    ap.add_argument("--live", action="store_true", help="really buy and set up (the card must be approved)")
    ap.add_argument("--domains", help="only these domains, comma separated")
    ap.add_argument("--now", action="store_true", help="check again now, even if a domain's next check is later")
    args = ap.parse_args(argv)
    ctx = skillkit.context(needs=["SLACK_BOT_TOKEN"] if args.live else [])
    only = [d for d in (args.domains or "").split(",") if d.strip()] or None
    try:
        out = engine.provision(ctx, args.batch, live=args.live, force=args.now, only=only)
    except (skillkit.NotApproved, skillkit.MissingKey, ValueError) as e:
        print("Stopped: {0}".format(e))
        return 2
    except Exception as e:  # noqa: BLE001
        skillkit.report_failure(ctx, engine.SKILL, "set up the card", e,
                                skillkit.card_link(ctx.settings(), engine.BOARD, args.batch))
        raise
    print(report(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    skillkit.main_guard(main)
