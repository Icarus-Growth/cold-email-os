#!/usr/bin/env python3
"""The domain steps of tab 2: find where a domain's records are, buy a new domain on Porkbun,
move it to Cloudflare, add a record, and wait until it works.

    python3 apps/os/frontend/tools/domain.py keys                  check the Cloudflare (and Porkbun) keys
    python3 apps/os/frontend/tools/domain.py where youragency.com  where this domain's records are kept
    python3 apps/os/frontend/tools/domain.py check youragencyos.com
                                     is it free, and what it costs (Porkbun). Buys nothing.
    python3 apps/os/frontend/tools/domain.py buy youragencyos.com --cost 999 --yes
                                     buy it. ONLY after the owner said yes to that price.
    python3 apps/os/frontend/tools/domain.py to-cloudflare youragencyos.com
                                     add it to Cloudflare and point Porkbun's name servers there
    python3 apps/os/frontend/tools/domain.py zone-status youragencyos.com
    python3 apps/os/frontend/tools/domain.py record app.youragency.com agency-os.pages.dev --dns porkbun
                                     add one CNAME record (--dns cloudflare | porkbun | manual)
    python3 apps/os/frontend/tools/domain.py wait app.youragency.com agency-os.pages.dev

Add --dry-run to any of them to see each call without making it.

It reads these from the .env file at the top of the repo (never from the chat):
    CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID   (or, with no token, CLOUDFLARE_API_KEY and CLOUDFLARE_EMAIL)
    PORKBUN_API_KEY, PORKBUN_SECRET_KEY   (only for a domain bought or kept on Porkbun)
Python 3.9 or later. No packages to install.
"""

import argparse
import sys
import time
import uuid

import cloud

KEYS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL", "CLOUDFLARE_ACCOUNT_ID",
        "PORKBUN_API_KEY", "PORKBUN_SECRET_KEY")
PB_KEYS = KEYS[4:]


def split(host, main):
    """('app', 'youragency.com') from app.youragency.com. `main` wins when given (for .co.uk and the like)."""
    host = host.lower().strip(".")
    if main:
        main = main.lower().strip(".")
        if host == main:
            return "", main
        if not host.endswith("." + main):
            sys.exit("%s is not under %s" % (host, main))
        return host[: -len(main) - 1], main
    parts = host.split(".")
    return ".".join(parts[:-2]), ".".join(parts[-2:])


def pb_ok(r, what):
    if r.get("status") != "SUCCESS":
        sys.exit("Porkbun refused %s: %s %s" % (what, r.get("code") or "", r.get("message") or r))
    for w in r.get("warnings") or []:
        print("  Porkbun says: %s" % w)
    return r


# ---------------------------------------------------------------------------


def cmd_keys(c, a):
    cloud.need(c, cloud.cf_keys(c), "the Cloudflare token, from tab 2 step 2")
    if cloud.uses_token(c):
        # A token may not read the account itself: check that it is active and can see Pages.
        who = cloud.cf(c, "/user/tokens/verify")
        acct = cloud.cf(c, "/accounts/%s/pages/projects" % c["CLOUDFLARE_ACCOUNT_ID"])
        ok = who.get("success") and (who.get("result") or {}).get("status", "active") == "active" and acct.get("success")
        fix = "CLOUDFLARE_API_TOKEN (Cloudflare Pages Edit, DNS Edit, Zone Read) and CLOUDFLARE_ACCOUNT_ID"
        name = "the token is active and can use Cloudflare Pages"
    else:
        who = cloud.cf(c, "/user")
        acct = cloud.cf(c, "/accounts/%s" % c["CLOUDFLARE_ACCOUNT_ID"])
        ok = who.get("success") and acct.get("success")
        fix = "CLOUDFLARE_API_KEY (the Global API Key), CLOUDFLARE_EMAIL and CLOUDFLARE_ACCOUNT_ID"
        name = "account \"%s\" (with the global key: a token is safer, see tab 2 step 2)" % (acct.get("result") or {}).get("name", "?")
    print("Cloudflare: %s" % ("OK, " + name if ok else
                              "NOT OK. Check %s: %s" % (fix, who.get("errors") or acct.get("errors"))))
    if c["PORKBUN_API_KEY"] or a.porkbun:
        cloud.need(c, PB_KEYS, "the Porkbun keys")
        r = cloud.porkbun(c, "/ping")
        print("Porkbun: %s" % ("OK" if r.get("status") == "SUCCESS" else "NOT OK: %s" % r.get("message")))
        ok = ok and r.get("status") == "SUCCESS"
    if not ok and not cloud.DRY:
        sys.exit(1)


def cmd_where(c, a):
    _, main = split(a.domain, a.main)
    ns = [n.lower() for n in cloud.resolve(main, "NS")]
    if not ns and not cloud.DRY:
        sys.exit("No name servers found for %s. Check the spelling." % main)
    if ns and all(n.endswith(".ns.cloudflare.com") for n in ns):
        where = "cloudflare"
    elif ns and all("porkbun.com" in n for n in ns):
        where = "porkbun"
    else:
        where = "elsewhere"
    print("%s: name servers %s" % (main, ", ".join(ns) or "(none)"))
    print("Its records are kept on: %s" % {"cloudflare": "Cloudflare (use --dns cloudflare)",
                                           "porkbun": "Porkbun (use --dns porkbun; needs the Porkbun keys)",
                                           "elsewhere": "another company (use --dns manual: add the record by hand)"}[where])


def quote(c, domain):
    """Free or taken, and the exact price in cents, from Porkbun. Buys nothing."""
    r = pb_ok(cloud.porkbun(c, "/domain/checkDomain/%s" % domain), "the check")
    info = r.get("response") or {}
    if str(info.get("avail")).lower() != "yes":
        sys.exit("%s is taken. Try another name." % domain)
    if str(info.get("premium")).lower() == "yes":
        sys.exit("%s is a premium name. Porkbun does not sell those through the API. Pick another name." % domain)
    tld = domain.rsplit(".", 1)[1]
    req = cloud.porkbun(c, "/domain/getRegistrationRequirements/%s" % tld)
    if req.get("status") == "SUCCESS" and req.get("apiRegisterable") is False:
        sys.exit(".%s cannot be bought through the API (%s). Pick a .com or another ending."
                 % (tld, req.get("notApiRegisterableReason") or "registry rules"))
    dry = pb_ok(cloud.porkbun(c, "/domain/create/%s" % domain, {"cost": 0, "agreeToTerms": "yes", "dryRun": True}),
                "the price check")
    return info, dry


def cmd_check(c, a):
    cloud.need(c, PB_KEYS, "the Porkbun keys, from tab 2 step 4")
    info, dry = quote(c, a.domain)
    cost = dry.get("cost")
    print("%s is free." % a.domain)
    print("  first year: %s   (renews at $%s a year)" % (dry.get("costDisplay") or "$" + str(info.get("price")),
                                                       info.get("regularPrice") or "?"))
    if dry.get("sufficientFunds") is False:
        print("  Your Porkbun credit is too low: add at least %s at https://porkbun.com/account/credit, then check again."
              % (("$%.2f" % (dry.get("shortfall", 0) / 100.0)) if dry.get("shortfall") else "the price"))
    print("To buy it, the owner must say yes to this price. Then run:")
    print("  python3 apps/os/frontend/tools/domain.py buy %s --cost %s --yes" % (a.domain, cost))


def cmd_buy(c, a):
    cloud.need(c, PB_KEYS, "the Porkbun keys, from tab 2 step 4")
    if not a.yes:
        sys.exit("Not bought. Show the owner the price from `check`, wait for their yes, then add --yes.")
    if not a.cost:
        sys.exit("Add --cost with the number `check` printed (the price in cents).")
    _, dry = quote(c, a.domain)
    if not cloud.DRY and dry.get("cost") != a.cost:
        sys.exit("The price changed: it is now %s (%s cents), not %s cents. Show the owner the new price first."
                 % (dry.get("costDisplay"), dry.get("cost"), a.cost))
    if dry.get("wouldSucceed") is False:
        sys.exit("Porkbun would refuse it: %s" % dry.get("message"))
    r = pb_ok(cloud.porkbun(c, "/domain/create/%s" % a.domain, {"cost": a.cost, "agreeToTerms": "yes"}), "the purchase")
    print("Bought %s for %s cents (order %s). Next: domain.py to-cloudflare %s"
          % (a.domain, r.get("cost", a.cost), r.get("orderId", "?"), a.domain))


def cmd_to_cloudflare(c, a):
    cloud.need(c, cloud.cf_keys(c) + PB_KEYS, "the Cloudflare token and the Porkbun keys")
    domain = a.domain.lower()
    have = cloud.cf(c, "/zones?name=%s" % domain).get("result") or []
    if cloud.DRY:
        have = []   # show the call that adds it
    if have:
        zone = have[0]
        print("%s is already on Cloudflare (%s)." % (domain, zone.get("status")))
    else:
        r = cloud.cf(c, "/zones", {"name": domain, "account": {"id": c["CLOUDFLARE_ACCOUNT_ID"]}, "type": "full"})
        if not r.get("success"):
            hint = ("\nA token needs Zone, Zone, Edit to add a domain: tab 2, Step 4, a new domain, part 6."
                    if cloud.uses_token(c) else "")
            sys.exit("Cloudflare would not add %s: %s%s" % (domain, r.get("errors") or r.get("_body"), hint))
        zone = r["result"]
        print("Added %s to Cloudflare." % domain)
    ns = zone.get("name_servers") or []
    if not ns:
        sys.exit("Cloudflare gave no name servers for %s." % domain)
    pb_ok(cloud.porkbun(c, "/domain/updateNs/%s" % domain, {"ns": ns}), "the name server change")
    print("Porkbun now points %s to Cloudflare: %s" % (domain, ", ".join(ns)))
    print("Cloudflare turns it on when it sees the change: usually within an hour, at most a day.")
    print("Check with: python3 apps/os/frontend/tools/domain.py zone-status %s" % domain)


def cmd_zone_status(c, a):
    cloud.need(c, cloud.cf_keys(c), "the Cloudflare token")
    have = cloud.cf(c, "/zones?name=%s" % a.domain.lower()).get("result") or []
    if not have:
        sys.exit("%s is not on Cloudflare. Run: domain.py to-cloudflare %s" % (a.domain, a.domain))
    z = have[0]
    if z.get("status") != "active" and not cloud.DRY:
        cloud.cf(c, "/zones/%s/activation_check" % z["id"], {}, method="PUT")   # asks Cloudflare to look again
    print("%s on Cloudflare: %s" % (a.domain, z.get("status")))
    print("Public name servers now: %s" % (", ".join(cloud.resolve(a.domain, "NS")) or "(none yet)"))
    if z.get("status") != "active":
        sys.exit(1)


def cmd_record(c, a):
    sub, main = split(a.host, a.main)
    target = a.target.lower().strip(".")
    if not sub:
        sys.exit("Give a subdomain (for example app.%s). The main domain itself keeps its website." % main)
    if a.dns == "cloudflare":
        cloud.need(c, cloud.cf_keys(c), "the Cloudflare token")
        zone = cloud.find_zone(c, a.host)
        if not zone:
            sys.exit("%s is not on this Cloudflare account. Use --dns porkbun or --dns manual." % main)
        if not cloud.cname(c, zone, a.host, target):
            sys.exit(1)
    elif a.dns == "porkbun":
        cloud.need(c, PB_KEYS, "the Porkbun keys")
        have = cloud.porkbun(c, "/dns/retrieveByNameType/%s/CNAME/%s" % (main, sub))
        if have.get("records"):
            pb_ok(cloud.porkbun(c, "/dns/editByNameType/%s/CNAME/%s" % (main, sub), {"content": target, "ttl": 600}),
                  "the record change")
        else:
            pb_ok(cloud.porkbun(c, "/dns/create/%s" % main, {"name": sub, "type": "CNAME", "content": target, "ttl": 600}),
                  "the new record")
        print("DNS on Porkbun: CNAME %s -> %s" % (a.host, target))
        print("If Porkbun says \"API access\" is off for %s: Porkbun → Domain Management → %s → Details → "
              "turn on API Access, then run this again." % (main, main))
    else:
        print("Add this record where %s's records are kept (the company you pay for the domain, or your DNS host):"
              % main)
        print("    Type: CNAME    Name (or Host): %s    Value (or Target): %s    TTL: automatic or 600" % (sub, target))
        print("If a record with that name is already there, change it instead of adding a second one.")
    print("Then: python3 apps/os/frontend/tools/domain.py wait %s %s" % (a.host, target))


def cmd_wait(c, a):
    target = a.target.lower().strip(".")
    end = time.time() + a.minutes * 60
    while True:
        names = [n.lower() for n in cloud.resolve(a.host, "CNAME")]
        addrs = cloud.resolve(a.host, "A")
        if target in names or (addrs and not names):
            print("%s works: %s" % (a.host, ", ".join(names or addrs)))
            return
        if cloud.DRY or time.time() > end:
            sys.exit("%s does not point to %s yet (now: %s). A new record can take up to an hour. "
                     "Check it was saved, then run this again." % (a.host, target, ", ".join(names or addrs) or "nothing"))
        print("  not yet (now: %s), looking again in 30 s" % (", ".join(names or addrs) or "nothing"))
        time.sleep(30)


# Made-up answers for --dry-run, so every step shows.
def dry_answers(example):
    cloud.fake("porkbun:/domain/checkDomain/", None, {"status": "SUCCESS", "response": {
        "avail": "yes", "premium": "no", "price": "9.99", "regularPrice": "9.99"}})
    cloud.fake("porkbun:/domain/getRegistrationRequirements/", None, {"status": "SUCCESS", "apiRegisterable": True})
    cloud.fake("porkbun:/domain/create/", None, {"status": "SUCCESS", "dryRun": True, "wouldSucceed": True,
                                                 "cost": 999, "costDisplay": "$9.99", "sufficientFunds": True,
                                                 "orderId": 1})
    cloud.fake("porkbun:/dns/retrieveByNameType/", None, {"status": "SUCCESS", "records": []})
    cloud.fake("porkbun:", None, {"status": "SUCCESS"})
    cloud.fake("/zones?name=", "GET", {"success": True, "result": [{"id": "<zone id>", "status": "active",
                                                                    "name": example, "name_servers": [
                                                                        "ada.ns.cloudflare.com", "bob.ns.cloudflare.com"]}]})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print each call, make none")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("keys"); s.add_argument("--porkbun", action="store_true", help="also check the Porkbun keys")
    s = sub.add_parser("where"); s.add_argument("domain"); s.add_argument("--main")
    s = sub.add_parser("check"); s.add_argument("domain")
    s = sub.add_parser("buy"); s.add_argument("domain"); s.add_argument("--cost", type=int); s.add_argument("--yes", action="store_true")
    s = sub.add_parser("to-cloudflare"); s.add_argument("domain")
    s = sub.add_parser("zone-status"); s.add_argument("domain")
    s = sub.add_parser("record"); s.add_argument("host"); s.add_argument("target")
    s.add_argument("--dns", choices=("cloudflare", "porkbun", "manual"), required=True); s.add_argument("--main")
    s = sub.add_parser("wait"); s.add_argument("host"); s.add_argument("target"); s.add_argument("--minutes", type=int, default=30)
    for p in sub.choices.values():
        p.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    a = ap.parse_args()
    cloud.DRY = a.dry_run
    if cloud.DRY:
        dry_answers(getattr(a, "domain", None) or getattr(a, "host", "example.com"))
        print("DRY RUN: nothing is bought, made or changed.")
    c = cloud.env(KEYS)
    {"keys": cmd_keys, "where": cmd_where, "check": cmd_check, "buy": cmd_buy, "to-cloudflare": cmd_to_cloudflare,
     "zone-status": cmd_zone_status, "record": cmd_record, "wait": cmd_wait}[a.cmd](c, a)


if __name__ == "__main__":
    main()
