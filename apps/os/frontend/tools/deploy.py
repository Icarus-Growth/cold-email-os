#!/usr/bin/env python3
"""Build the OS and put it live on YOUR Cloudflare account.

    python3 apps/os/frontend/tools/deploy.py --domain app.youragency.com
    python3 apps/os/frontend/tools/deploy.py --verify-only --domain app.youragency.com
    python3 apps/os/frontend/tools/deploy.py --owner-login
    python3 apps/os/frontend/tools/deploy.py --owner-login --reset --email you@youragency.com
    python3 apps/os/frontend/tools/deploy.py --dry-run --domain app.youragency.com
    python3 apps/os/frontend/tools/deploy.py               (no domain: the OS stays on its pages.dev address)

It reads these from the .env file at the top of the repo (never from the chat):

    CLOUDFLARE_API_TOKEN    your Cloudflare API token (tab 2, Step 2: Pages Edit, DNS Edit, Zone Read)
    CLOUDFLARE_ACCOUNT_ID   your Cloudflare account ID
    CLOUDFLARE_API_KEY, CLOUDFLARE_EMAIL   only if you have no token: the global API key and
                            the email you sign in with (a token is used whenever one is set)
    SUPABASE_URL            your Supabase project address
    SUPABASE_PUBLISHABLE_KEY  built into the OS (safe in a browser: every table is team-only)
    SUPABASE_SECRET_KEY     stored as a Cloudflare secret, for "Add team member" and "Resend access"
    SUPABASE_PROJECT_REF, SUPABASE_ACCESS_TOKEN   from tab 1: to set the sign-in address
    OS_DOMAIN               optional, e.g. app.youragency.com (same as --domain)
    OS_PROJECT              optional, the Cloudflare Pages project name (default: agency-os)
    OS_AUTOMATIONS_URL      optional, set in tab 3: new team members also get their sign-in in Slack
    OS_SHARED_SECRET        optional, set in tab 3: the secret that call carries

The steps, in this order, because each needs the one before it:

  1. BUILD          npm ci (first time), then npm run build: checks the code, then makes dist/.
  2. PROJECT        make the Cloudflare Pages project if it is not there.
  3. SETTINGS       put the Supabase values on the project BEFORE the deploy, or the new
                    version starts without them. The secret key goes in as a secret.
  4. DEPLOY         wrangler pages deploy (the screens, and the two server steps in functions/).
  5. DOMAIN         attach your address. If its DNS is on Cloudflare, the record is added for
                    you. If not, use domain.py record (it prints the command).
  6. SIGN-IN        set the OS address as the Supabase sign-in address. Then read it back.
  7. OS ADDRESS     write the address into settings.os_url (Slack buttons and links use it).
                    Then read it back.
  8. CHECK          check the live site on its CONTENT, never only on the status code.

--owner-login makes the sign-in for each Owner on the team list who has none yet, and prints
their temporary password ONCE. It is never saved. They choose their own at the first sign-in.

Python 3.9 or later. No packages to install. Node.js 20 or later (wrangler runs through npx).
"""

import argparse
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import cloud

APP = cloud.APP
DIST = APP / "dist"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")

KEYS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL", "CLOUDFLARE_ACCOUNT_ID", "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_PROJECT_REF", "SUPABASE_ACCESS_TOKEN",
        "OS_DOMAIN", "OS_PROJECT", "OS_AUTOMATIONS_URL", "OS_SHARED_SECRET")
NEEDED = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY")


def run(cmd, env=None, quiet=False):
    """Run a command in the app folder. Stops with its last lines when it fails."""
    shown = " ".join(cmd)
    if cloud.DRY:
        print("  [dry run] command    %s   (in apps/os/frontend)" % shown)
        return ""
    print("  $ " + shown)
    p = subprocess.run(cmd, cwd=str(APP), env=env, capture_output=True, text=True,
                       shell=(sys.platform == "win32"))
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        sys.exit("That failed (%d):\n%s" % (p.returncode, out[-2500:]))
    if not quiet:
        for line in out.splitlines():
            if line.strip():
                print("    " + line.strip()[:160])
    return out


def child_env(c, extra=None):
    return cloud.cf_env(c, extra)


# ---------------------------------------------------------------------------


def build(c):
    if not cloud.DRY and not shutil.which("npx" if sys.platform != "win32" else "npx.cmd"):
        sys.exit("Node.js is not installed. Install the LTS version from nodejs.org, then run this again.")
    if not (APP / "node_modules").exists():
        run(["npm", "ci", "--no-audit", "--no-fund"], quiet=True)
    # The publishable key is built into the page. The secret key never is: the build refuses one.
    run(["npm", "run", "build"], env=child_env(c, {"SUPABASE_URL": c["SUPABASE_URL"],
                                                    "SUPABASE_PUBLISHABLE_KEY": c["SUPABASE_PUBLISHABLE_KEY"]}),
        quiet=True)
    if not cloud.DRY:
        if not (DIST / "index.html").exists():
            sys.exit("The build made no dist/index.html.")
        print("  built dist/ (%d files)" % sum(1 for p in DIST.rglob("*") if p.is_file()))


def ensure_project(c):
    """The project, made if needed. Returns its pages.dev address (Cloudflare adds a few letters
    when the name is taken by someone else, so it is read back, not guessed)."""
    acct, p = c["CLOUDFLARE_ACCOUNT_ID"], c["OS_PROJECT"]
    r = cloud.cf(c, "/accounts/%s/pages/projects/%s" % (acct, p))
    if r.get("success"):
        print("  project %s is there" % p)
    else:
        print("  making project %s" % p)
        r = cloud.cf(c, "/accounts/%s/pages/projects" % acct, {"name": p, "production_branch": "main"})
        if not r.get("success"):
            sys.exit("could not make the Pages project: %s" % (r.get("errors") or r.get("_body")))
    sub = (r.get("result") or {}).get("subdomain") or "%s.pages.dev" % p
    print("  its own address: https://%s" % sub)
    return sub


def set_env_vars(c):
    """The settings the server steps read. Secrets cannot be read back out of Cloudflare."""
    plain = {"SUPABASE_URL": c["SUPABASE_URL"], "SUPABASE_PUBLISHABLE_KEY": c["SUPABASE_PUBLISHABLE_KEY"]}
    secret = {"SUPABASE_SECRET_KEY": c["SUPABASE_SECRET_KEY"]}
    automations = c["OS_AUTOMATIONS_URL"] and c["OS_SHARED_SECRET"] and not c["OS_AUTOMATIONS_URL"].startswith("<")
    if automations:
        plain["OS_AUTOMATIONS_URL"] = c["OS_AUTOMATIONS_URL"]
        secret["OS_SHARED_SECRET"] = c["OS_SHARED_SECRET"]
    env_vars = {k: {"type": "plain_text", "value": v} for k, v in plain.items()}
    env_vars.update({k: {"type": "secret_text", "value": v} for k, v in secret.items()})
    r = cloud.cf(c, "/accounts/%s/pages/projects/%s" % (c["CLOUDFLARE_ACCOUNT_ID"], c["OS_PROJECT"]),
                 {"deployment_configs": {"production": {"env_vars": env_vars}, "preview": {"env_vars": env_vars}}},
                 method="PATCH")
    if not r.get("success"):
        sys.exit("could not save the settings on the project: %s" % (r.get("errors") or r.get("_body")))
    print("  saved: %s (secrets: %s)" % (", ".join(sorted(plain)), ", ".join(sorted(secret))))
    if not automations:
        print("  (no OS_AUTOMATIONS_URL yet: new team members get no Slack message until tab 3)")


def deploy(c):
    # Run from the app folder, so wrangler also finds functions/ (the two server steps).
    run(["npx", "--yes", "wrangler@3", "pages", "deploy", "dist", "--project-name", c["OS_PROJECT"],
         "--branch", "main", "--commit-dirty=true"],
        env=child_env(c))


def attach_domain(c, domain, target):
    """Attach the address to the project, and add its DNS record when the domain is on
    Cloudflare. True when the record is in place."""
    r = cloud.cf(c, "/accounts/%s/pages/projects/%s/domains" % (c["CLOUDFLARE_ACCOUNT_ID"], c["OS_PROJECT"]),
                 {"name": domain})
    if not r.get("success") and "already" not in str(r.get("errors") or "").lower():
        print("  could not attach %s: %s" % (domain, r.get("errors") or r.get("_body")))
    zone = cloud.find_zone(c, domain)
    if zone and zone.get("status") != "active":
        print("  %s is on Cloudflare but not active yet. When domain.py zone-status says \"active\", run this again."
              % zone.get("name"))
        return False
    if not zone:
        print("  %s is not on this Cloudflare account. Add its record with:" % domain)
        print("      python3 apps/os/frontend/tools/domain.py record %s %s --dns porkbun   (or --dns manual)"
              % (domain, target))
        return False
    return cloud.cname(c, zone, domain, target)


def domain_status(c, domain):
    """'active', 'pending', ... or None when not attached. A new address is 'pending' for a few
    minutes while Cloudflare makes its certificate."""
    r = cloud.cf(c, "/accounts/%s/pages/projects/%s/domains" % (c["CLOUDFLARE_ACCOUNT_ID"], c["OS_PROJECT"]))
    for x in r.get("result") or []:
        if x.get("name") == domain:
            return x.get("status")
    return None


def save_sign_in_address(c, base, others):
    """Supabase's sign-in address (Site URL) and the addresses it may send people back to."""
    if not c["SUPABASE_ACCESS_TOKEN"] or not c["SUPABASE_PROJECT_REF"]:
        print("  SUPABASE_ACCESS_TOKEN or SUPABASE_PROJECT_REF is empty. Set it by hand: Supabase dashboard → "
              "Authentication → URL Configuration → Site URL = %s" % base)
        return False
    status, cfg = cloud.management(c, "/config/auth")
    if status == 401:
        print("  The Supabase access token from tab 1 has run out. Make a new one (tab 1, step 1), put it in "
              ".env, and run this again. Or set it by hand: Authentication → URL Configuration → Site URL = %s" % base)
        return False
    if status >= 400:
        print("  could not read the sign-in settings: %s %s" % (status, cfg))
        return False
    allow = [u for u in str((cfg or {}).get("uri_allow_list") or "").split(",") if u.strip()]
    for u in [base] + others:
        if u + "/**" not in allow:
            allow.append(u + "/**")
    status, out = cloud.management(c, "/config/auth", {"site_url": base, "uri_allow_list": ",".join(allow)},
                                   method="PATCH")
    if status >= 400:
        print("  could not save the sign-in address: %s %s" % (status, out))
        return False
    status, back = cloud.management(c, "/config/auth")
    got = (back or {}).get("site_url")
    ok = cloud.DRY or got == base
    print("  Supabase sign-in address = %s  (%s)" % (got if not cloud.DRY else base, "read back OK" if ok else
                                                      "DIFFERENT, check it"))
    return ok


def save_os_url(c, base):
    status, _ = cloud.supabase(c, "/settings?id=eq.1", {"os_url": base}, method="PATCH")
    if status >= 400:
        print("  could not save the OS address in the settings table (%s)" % status)
        return False
    status, back = cloud.supabase(c, "/settings?id=eq.1&select=os_url")
    got = ((back or [{}])[0] or {}).get("os_url") if isinstance(back, list) else None
    ok = cloud.DRY or got == base
    print("  settings.os_url = %s  (%s)" % (base if cloud.DRY else got, "read back OK" if ok else "DIFFERENT, check it"))
    return ok


# ---------------------------------------------------------------------------


class _Follow308(urllib.request.HTTPRedirectHandler):
    """Python 3.9's urlopen does not follow 308."""
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, 301, msg, headers)


def fetch(url, method="GET"):
    if cloud.DRY:
        print("  [dry run] check      %-6s %s" % (method, url))
        return 0, ""
    req = urllib.request.Request(url, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"User-Agent": UA, "Accept": "*/*", "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(_Follow308).open(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001  (a failed check, whatever the reason)
        return type(e).__name__, ""


def verify(c, base):
    """Each check looks for something only the real OS answers. A parking page answers 200 too."""
    host = re.sub(r"^https?://", "", c["SUPABASE_URL"]).rstrip("/")
    page = {"body": ""}

    def home(body):
        page["body"] = body
        return '<div id="root">' in body and "/assets/" in body

    def bundle(_body):
        m = re.search(r'src="(/assets/[^"]+\.js)"', page["body"])
        if not m:
            return False
        _, js = fetch(base + m.group(1))
        return host in js and "sb_secret_" not in js and c["SUPABASE_SECRET_KEY"] not in js

    checks = [
        ("GET", "/", home, "the OS page"),
        ("GET", "/", bundle, "the database address is built in, the secret key is not"),
        ("GET", "/clients/check-link", lambda b: '<div id="root">' in b, "a deep link opens the OS (page routing)"),
        # No sign-in: the server step must answer "Sign in first". "not set up yet" means the
        # Supabase settings are missing on the project.
        ("POST", "/api/team/add", lambda b: "Sign in first" in b, "the Add team member server step"),
    ]
    bad = 0
    for method, path, ok, label in checks:
        found, code = False, "-"
        for _ in range(3):
            code, body = fetch(base + path, method)
            if cloud.DRY or ok(body):
                found = True
                break
            time.sleep(4)
        if not cloud.DRY:
            print("    %s %s  %s" % ("OK  " if found else "FAIL", code, label))
        bad += 0 if found else 1
    return bad


# ---------------------------------------------------------------------------


def temp_password():
    """4 groups of 4, no look-alike letters, always a capital, a small letter and a number."""
    abc = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    while True:
        p = "".join(secrets.choice(abc) for _ in range(16))
        if re.search(r"[A-Z]", p) and re.search(r"[a-z]", p) and re.search(r"[2-9]", p):
            return "-".join(p[i:i + 4] for i in range(0, 16, 4))


def owner_login(c, email, reset):
    """Make the sign-in for each Owner who has none. Prints each temporary password once."""
    flt = "access=eq.Owner&can_sign_in=is.true&status=eq.Active&select=full_name,email"
    if email:
        flt += "&email=eq." + urllib.parse.quote(email.lower())
    status, owners = cloud.supabase(c, "/team?" + flt)
    if cloud.DRY:
        owners = [{"full_name": "Jane Doe", "email": email or "jane@youragency.com"}]
    elif status >= 400 or not owners:
        sys.exit("No Active Owner with \"can sign in\" ticked%s. Tab 1 step 6 adds you: "
                 "python3 apps/os/backend/db.py add-owner --name \"Your Name\" --email you@youragency.com"
                 % (" with that email" if email else ""))
    status, users = cloud.supabase(c, "/admin/users?page=1&per_page=1000", auth=True)
    have = {}
    for u in ((users or {}).get("users") or []) if isinstance(users, dict) else []:
        have[str(u.get("email", "")).lower()] = u.get("id")
    base = c.get("_base")
    if not base:   # no --domain: the address step 7 of the deploy saved
        _, row = cloud.supabase(c, "/settings?id=eq.1&select=os_url")
        base = ((row or [{}])[0] or {}).get("os_url") if isinstance(row, list) else None
    base = base or "your OS address"
    for o in owners:
        mail = o["email"].lower()
        meta = {"full_name": o["full_name"], "must_set_password": True}
        if mail in have and not reset:
            print("%s already has a sign-in. Nothing changed. (Lost the password? Run this again with "
                  "--reset --email %s)" % (mail, mail))
            continue
        password = temp_password()
        if mail in have:
            status, out = cloud.supabase(c, "/admin/users/%s" % have[mail],
                                         {"password": password, "email_confirm": True, "user_metadata": meta},
                                         method="PUT", auth=True)
        else:
            status, out = cloud.supabase(c, "/admin/users", {"email": mail, "password": password,
                                                             "email_confirm": True, "user_metadata": meta},
                                         method="POST", auth=True)
        if status >= 400:
            sys.exit("Could not make the sign-in for %s: %s %s" % (mail, status, out))
        print("")
        print("Sign-in for %s (%s)" % (o["full_name"], mail))
        print("  Temporary password: %s" % ("<shown here once>" if cloud.DRY else password))
        print("  Copy it now. It is not saved anywhere. Sign in at %s and choose your own password." % base)


# Made-up answers for --dry-run, so every step shows.
def dry_answers(c, domain):
    p = c["OS_PROJECT"]
    cloud.fake("/accounts/%s/pages/projects/%s/domains" % (c["CLOUDFLARE_ACCOUNT_ID"], p), "GET",
               {"success": True, "result": [{"name": domain, "status": "active"}] if domain else []})
    cloud.fake("/accounts/%s/pages/projects/%s" % (c["CLOUDFLARE_ACCOUNT_ID"], p), "GET", {"success": False})
    cloud.fake("/accounts/%s/pages/projects" % c["CLOUDFLARE_ACCOUNT_ID"], "POST",
               {"success": True, "result": {"subdomain": "%s.pages.dev" % p}})
    cloud.fake("/zones?name=", "GET", lambda path: {"success": True, "result": [
        {"id": "<zone id>", "status": "active", "name": path.split("=", 1)[1]}] if path.count(".") == 1 else []})
    cloud.fake("/zones/", "GET", {"success": True, "result": []})
    cloud.fake("management:/config/auth", "GET", {"site_url": "http://localhost:3000", "uri_allow_list": ""})
    cloud.fake("supabase:/auth/v1/admin/users", "GET", {"users": []})
    cloud.fake("supabase:/rest/v1/settings?id=eq.1&select=os_url", "GET",
               [{"os_url": "https://%s" % (domain or "%s.pages.dev" % p)}])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--domain", default=None, help="e.g. app.youragency.com")
    ap.add_argument("--verify-only", action="store_true",
                    help="check the live site; once the address is active, also save it as the sign-in address and os_url")
    ap.add_argument("--owner-login", action="store_true", help="make the Owner's sign-in and print its temporary password once")
    ap.add_argument("--email", default=None, help="with --owner-login: only this Owner")
    ap.add_argument("--reset", action="store_true", help="with --owner-login: give an existing sign-in a new temporary password")
    ap.add_argument("--dry-run", action="store_true", help="print every call and command, make none")
    args = ap.parse_args()

    cloud.DRY = args.dry_run
    c = cloud.env(KEYS)
    if not c["OS_PROJECT"] or c["OS_PROJECT"] == "<OS_PROJECT>":
        c["OS_PROJECT"] = "agency-os"
    domain = (args.domain or ("" if c["OS_DOMAIN"].startswith("<") else c["OS_DOMAIN"]) or "").strip().lower() or None
    if cloud.DRY:
        dry_answers(c, domain)
        print("DRY RUN: nothing is built, made, changed or deployed. Address: %s"
              % (domain or "none (the free pages.dev address)"))

    if args.owner_login:
        if args.reset and not args.email:
            sys.exit("Add --email with the Owner whose password is lost. --reset never changes anyone else's.")
        cloud.need(c, ("SUPABASE_URL", "SUPABASE_SECRET_KEY"), "the Supabase values from tab 1")
        c["_base"] = "https://%s" % domain if domain else None
        owner_login(c, args.email, args.reset)
        return

    cloud.need(c, cloud.cf_keys(c) + NEEDED, "the Cloudflare token from tab 2 step 2, and the Supabase values from tab 1")
    acct = c["CLOUDFLARE_ACCOUNT_ID"]
    if args.verify_only:
        r = cloud.cf(c, "/accounts/%s/pages/projects/%s" % (acct, c["OS_PROJECT"]))
        pages = "https://%s" % ((r.get("result") or {}).get("subdomain") or "%s.pages.dev" % c["OS_PROJECT"])
        active = bool(domain) and domain_status(c, domain) == "active"
        base = "https://%s" % domain if active else pages
        if domain and not active:
            print("  %s is not active yet: checking %s instead" % (domain, pages))
        print("checking %s" % base)
        bad = verify(c, base)
        if active and not bad:
            print("saving the address")
            save_sign_in_address(c, base, [pages])
            save_os_url(c, base)
        sys.exit(1 if bad else 0)

    print("1/8 build")
    build(c)
    print("2/8 project")
    sub = ensure_project(c)
    pages = "https://%s" % sub
    print("3/8 settings")
    set_env_vars(c)
    print("4/8 deploy")
    deploy(c)
    print("5/8 domain")
    wired = attach_domain(c, domain, sub) if domain else False
    if not domain:
        print("  no address given: the OS is on %s only" % pages)
    status = domain_status(c, domain) if domain else None
    base = "https://%s" % domain if status == "active" else pages
    if domain and status != "active":
        print("  %s is %s. Cloudflare usually needs a few minutes after the record is in place. Then run:\n"
              "      python3 apps/os/frontend/tools/deploy.py --verify-only --domain %s"
              % (domain, status or "not attached", domain))
    print("6/8 sign-in address")
    save_sign_in_address(c, base, [pages] if base != pages else [])
    print("7/8 OS address")
    save_os_url(c, base)
    print("8/8 check")
    print("checking %s" % base)
    bad = verify(c, base)
    if bad:
        sys.exit("\n%d check(s) failed. The OS is NOT working yet." % bad)
    print("\nLive: %s" % base)
    if domain and not wired:
        print("Your address %s still needs its DNS record (see step 5)." % domain)
    if cloud.DRY:
        print("\nThen, once: python3 apps/os/frontend/tools/deploy.py --owner-login   (see --dry-run --owner-login)")


if __name__ == "__main__":
    main()
