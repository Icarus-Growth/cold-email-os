"""Called once a day by the existing daily job (no schedule of its own).

For every Inbox set-ups card in stage 20, 30 or 40 it runs the set-up LIVE but WITHOUT buying:
it checks nameservers, inbox status, SPF/DKIM/DMARC, starts the warm-up and marks domains ready.
Buying and ordering need a person to run the skill with --live once. A card that is not approved
is left alone.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _d in (HERE, HERE.parents[1] / "sending-estate-plan" / "scripts", HERE.parents[1] / "sending-domain-names" / "scripts"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import json  # noqa: E402

import provision_estate  # noqa: E402,F401  (puts the kit on the path)
import skillkit  # noqa: E402
import sending_engine as engine  # noqa: E402


def run(db, slack, config, seen, today):
    ctx = skillkit.Context(db, slack, config, seen)
    cfg = json.loads((HERE.parent / "config.json").read_text())
    stages = cfg.get("daily_stages") or []
    cards = db.select(engine.BOARD, {"stage": "in.({0})".format(",".join('"{0}"'.format(s) for s in stages)),
                                     "archived_at": "is.null"})
    out = {"cards": 0, "moved": 0, "skipped": []}
    for card in cards:
        client = db.get("clients", str(card.get("client_id"))) or {}
        if client.get("archived_at"):
            out["skipped"].append(card.get("batch_name"))  # an archived client gets no daily work
            continue
        try:
            r = engine.provision(ctx, card["id"], live=True, spend=False, cfg=cfg)
        except skillkit.NotApproved:
            out["skipped"].append(card.get("batch_name"))
            continue
        except skillkit.MissingKey as e:
            if skillkit.first_time(seen, "sending-daily-keys"):
                skillkit.report_failure(ctx, engine.SKILL, "daily check", e)
            return dict(out, ok=False, error="keys missing")
        except Exception as e:  # noqa: BLE001 - one card's problem never stops the others
            skillkit.report_failure(ctx, engine.SKILL, "daily check of {0}".format(card.get("batch_name")), e,
                                    skillkit.card_link(ctx.settings(), engine.BOARD, str(card["id"])))
            continue
        out["cards"] += 1
        out["moved"] += int(r["stage"] != card.get("stage"))
    return dict(out, ok=True)
