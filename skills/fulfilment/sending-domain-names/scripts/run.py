"""The entry the automation server calls (skillkit.run_skill): run(ctx, client=..., count=...)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import propose_domains  # noqa: E402
import sending_naming as naming  # noqa: E402
from sending_registrars import get_registrar  # noqa: E402


def run(ctx, client, count=10, style=None, website=None, brand=None, offline=False):
    cfg = naming.load_config()
    reg = get_registrar(cfg.get("registrar"))
    if not offline:
        propose_domains.skillkit.need(reg.keys, reg.where)
    result = propose_domains.propose_for(ctx.db, client, int(count), style, website, brand, bool(offline), cfg, reg)
    return {"ok": True, "client": result["client_name"], "style": result["style"],
            "domains": [{"domain": d["domain"], "price_usd": d["price"]} for d in result["domains"]]}
