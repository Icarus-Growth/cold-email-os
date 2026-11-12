"""The entry the automation server calls (skillkit.run_skill): run(ctx, client=..., volume=...)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import plan_estate  # noqa: E402


def run(ctx, client, volume=None, style=None, senders=None, enterprise=False, preview=False):
    reg = plan_estate.get_registrar(plan_estate.naming.load_config().get("registrar"))
    plan_estate.skillkit.need(reg.keys, reg.where)
    plan = plan_estate.make_plan(ctx, client, volume, style, senders, bool(enterprise), bool(preview), registrar=reg)
    return {"ok": True, "summary": plan_estate.summary(plan),
            "cards": [{k: c.get(k) for k in ("kind", "card_id", "provider", "link")} for c in plan["cards"]]}
