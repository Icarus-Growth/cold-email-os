"""Propose sending domain names for one client. Read only: it buys nothing and writes nothing.

    python3 skills/fulfilment/sending-domain-names/scripts/propose_domains.py --client "Acme Dental"
    python3 skills/fulfilment/sending-domain-names/scripts/propose_domains.py --client "Acme Dental" --count 20 --style mix
    python3 skills/fulfilment/sending-domain-names/scripts/propose_domains.py --client <row id> --offline   (no registrar check)
    python3 skills/fulfilment/sending-domain-names/scripts/propose_domains.py --client "Acme Dental" --json

Exit 0 = the count was met. Exit 2 = a plain stop (no client, a key missing, not enough free names).
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
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import argparse  # noqa: E402
import json  # noqa: E402
from typing import Any, Dict, Optional  # noqa: E402

import sending_naming as naming  # noqa: E402
from sending_registrars import get_registrar  # noqa: E402

SKILL = "sending-domain-names"


def propose_for(db: Any, client_ref: Any, count: int = 10, style: Optional[str] = None, website: Optional[str] = None,
                brand: Optional[str] = None, offline: bool = False, cfg: Optional[Dict[str, Any]] = None,
                registrar: Any = None) -> Dict[str, Any]:
    """The names for one client, checked free at the registrar (unless offline). Pure apart from
    reads: the database (who uses what) and the registrar (what is free)."""
    cfg = cfg or naming.load_config()
    client = naming.find_client(db, client_ref)
    reg = registrar or get_registrar(cfg.get("registrar"))
    taken = naming.taken_domains(db)
    if offline:
        check = naming.unchecked
    else:
        taken |= reg.owned()
        check = reg.check_many
    result = naming.propose_for_client(
        int(count), style or cfg.get("default_style"), check, cfg, taken,
        company_name=client.get("client_name"), website=website or client.get("website"), brand=brand,
        seed=str(client.get("id") or client.get("client_name")))
    result.update(client_id=client.get("id"), client_name=client.get("client_name"), offline=offline,
                  registrar=reg.name, main_domain=naming.domain_of(website or client.get("website")))
    return result


def table(result: Dict[str, Any]) -> str:
    lines = ["  #  domain                          tier  style     price a year"]
    for i, d in enumerate(result["domains"], 1):
        price = "not checked" if result["offline"] else "{0:.2f} USD".format(d["price"] or 0)
        lines.append("{0:>3}  {1:<31} {2:<5} {3:<9} {4}".format(i, d["domain"], d["tier"], d["style"], price))
    lines.append("")
    lines.append("{0} names for {1} ({2}). {3} checked at {4}, {5} left out. Never used: {6}.".format(
        len(result["domains"]), result["client_name"], result["style"], result["checked"], result["registrar"],
        len(result["rejected"]), result["main_domain"] or "no main domain on the client row"))
    if result["offline"]:
        lines.append("Offline: the registrar was not asked. These names may be taken.")
    lines.append("Nothing is bought. To plan inboxes and ask for approval, use the sending-estate-plan skill.")
    return "\n".join(lines)


def main(argv: Any = None) -> int:
    ap = argparse.ArgumentParser(description="Propose sending domain names (read only).")
    ap.add_argument("--client", required=True, help="the client's name or row id")
    ap.add_argument("--count", type=int, default=10, help="how many names (default 10)")
    ap.add_argument("--style", help="branded, generic or mix (default: config.json)")
    ap.add_argument("--website", help="use this website in place of the one on the client row")
    ap.add_argument("--brand", help="use this brand word in place of the website name")
    ap.add_argument("--offline", action="store_true", help="do not ask the registrar (names are not checked)")
    ap.add_argument("--json", action="store_true", help="print JSON for another script")
    args = ap.parse_args(argv)
    cfg = naming.load_config()
    reg = get_registrar(cfg.get("registrar"))
    ctx = skillkit.context(needs=[] if args.offline else reg.keys, where=reg.where)
    try:
        result = propose_for(ctx.db, args.client, args.count, args.style, args.website, args.brand,
                             args.offline, cfg, reg)
    except naming.NamingError as e:
        print("Stopped: {0}".format(e))
        return 2
    print(skillkit.dump(result) if args.json else table(result))
    return 0


if __name__ == "__main__":
    skillkit.main_guard(main)
