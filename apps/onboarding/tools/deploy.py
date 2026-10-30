#!/usr/bin/env python3
"""Build the onboarding form and put it live on YOUR Cloudflare account.

    python3 apps/onboarding/tools/deploy.py --build-only
    python3 apps/onboarding/tools/deploy.py --domain onboarding.youragency.com
    python3 apps/onboarding/tools/deploy.py --verify-only --domain onboarding.youragency.com
    python3 apps/onboarding/tools/deploy.py               (no domain: the form stays on its pages.dev address)

It reads these from the .env file at the top of the repo (never from the chat):

    CLOUDFLARE_API_TOKEN    your Cloudflare API token (tab 2, Step 2: Pages Edit, DNS Edit, Zone Read)
    CLOUDFLARE_ACCOUNT_ID   your Cloudflare account ID
    CLOUDFLARE_API_KEY, CLOUDFLARE_EMAIL   only if you have no token: the global API key and
                            the email you sign in with (a token is used whenever one is set)
    SUPABASE_URL            your Supabase project address
    SUPABASE_SECRET_KEY     your Supabase secret key (stored as a Cloudflare secret)
    ONBOARDING_DOMAIN       optional, e.g. onboarding.youragency.com (same as --domain)
    ONBOARDING_PROJECT      optional, the Cloudflare Pages project name (default: onboarding-form)
    OS_AUTOMATIONS_URL      optional, set in tab 3: where a new form is announced
    OS_SHARED_SECRET        optional, set in tab 3: the secret that call carries

The steps, in this order, because each needs the one before it:

  1. CHECK + BUILD  validate_questions.py, then questions.json goes into
                    worker/worker.js to make site/_worker.js.
  2. PROJECT        make the Cloudflare Pages project if it is not there.
  3. SETTINGS       put the Supabase address and secret key on the project
                    BEFORE the deploy, or the new version starts without them.
  4. DEPLOY         wrangler pages deploy.
  5. DOMAIN         attach your domain. If the domain's DNS is on Cloudflare,
                    the record is added for you. If not, it prints the record
                    to add by hand.
  6. FORM LINK      write the form's address into the settings table, so the
                    OS "Copy form link" button uses it. Then read it back.

Then it checks the live site on its CONTENT, never only on the status code.
Python 3.9 or later. No packages to install. wrangler runs through npx.
"""

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent
REPO = APP.parent.parent
SITE = APP / "site"
QUESTIONS = APP / "questions.json"
WORKER_SRC = APP / "worker" / "worker.js"
WORKER_OUT = SITE / "_worker.js"

CF = "https://api.cloudflare.com/client/v4"
# The Cloudflare sign-in: an API token (the way tab 2 teaches), or the global API key with its
# email as a fallback. A token is used whenever one is set.
CF_SIGN_IN = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")


def read_env(path):
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def settings(need_cloudflare=True):
    e = read_env(REPO / ".env")

    def get(key):
        return os.environ.get(key) or e.get(key, "")

    c = {k: get(k) for k in CF_SIGN_IN + (
        "CLOUDFLARE_ACCOUNT_ID", "SUPABASE_URL",
        "SUPABASE_SECRET_KEY", "ONBOARDING_DOMAIN", "ONBOARDING_PROJECT", "OS_AUTOMATIONS_URL",
        "OS_SHARED_SECRET")}
    # A token left in the terminal from other work must not replace the global key that .env holds.
    if e.get("CLOUDFLARE_API_KEY") and not e.get("CLOUDFLARE_API_TOKEN"):
        c["CLOUDFLARE_API_TOKEN"] = ""
    c["ONBOARDING_PROJECT"] = c["ONBOARDING_PROJECT"] or "onboarding-form"
    if need_cloudflare:
        missing = [k for k in cf_keys(c) + ("SUPABASE_URL", "SUPABASE_SECRET_KEY") if not c[k]]
        if missing:
            sys.exit("These are empty in .env: %s\nAdd them to .env (never to the chat), then run this again."
                     % ", ".join(missing))
    return c


def uses_token(c):
    """True when CLOUDFLARE_API_TOKEN is set, or when neither sign-in is (then it is the one to ask for)."""
    return bool(c["CLOUDFLARE_API_TOKEN"]) or not c["CLOUDFLARE_API_KEY"]


def cf_keys(c):
    """The .env names the Cloudflare calls need with the sign-in in use."""
    sign_in = ("CLOUDFLARE_API_TOKEN",) if uses_token(c) else ("CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL")
    return sign_in + ("CLOUDFLARE_ACCOUNT_ID",)


def cf(c, path, data=None, method=None):
    """One Cloudflare API call, with the API token (or the global API key as a fallback)."""
    body = json.dumps(data).encode() if data is not None else None
    auth = ({"Authorization": "Bearer " + c["CLOUDFLARE_API_TOKEN"]} if uses_token(c) else
            {"X-Auth-Email": c["CLOUDFLARE_EMAIL"], "X-Auth-Key": c["CLOUDFLARE_API_KEY"]})
    req = urllib.request.Request(
        CF + path, data=body, method=method or ("POST" if body else "GET"),
        headers=dict(auth, **{"Content-Type": "application/json"}))
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        text = e.read().decode()[:600]
        try:
            out = json.loads(text)
        except ValueError:
            out = {}
        out.update({"success": False, "_status": e.code, "_body": text})
        return out


def supabase(c, path, data=None, method="GET"):
    """One call to the Supabase web API with the secret key."""
    body = json.dumps(data).encode() if data is not None else None
    key = c["SUPABASE_SECRET_KEY"]
    req = urllib.request.Request(
        c["SUPABASE_URL"].rstrip("/") + "/rest/v1" + path, data=body, method=method,
        headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Prefer": "return=representation"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode()
        return json.loads(text) if text else None


# ---------------------------------------------------------------------------


def build():
    """Check the questions, then put them into the worker. A file that fails the
    check is never built, so it is never deployed."""
    v = subprocess.run([sys.executable, str(HERE / "validate_questions.py"), str(QUESTIONS)],
                       capture_output=True, text=True)
    for line in (v.stdout or "").strip().splitlines():
        print("  " + line.strip())
    if v.returncode != 0:
        sys.exit("  questions.json has errors, so nothing was built. Fix the errors above.")

    spec = json.loads(QUESTIONS.read_text())
    src = WORKER_SRC.read_text()
    if "__QUESTIONS__" not in src:
        sys.exit("worker/worker.js has no __QUESTIONS__ placeholder")
    out = src.replace("__QUESTIONS__", json.dumps(spec, ensure_ascii=False, separators=(",", ":")))
    digest = hashlib.sha256()
    for f in sorted((SITE / "form").glob("*")) + [QUESTIONS]:
        if f.is_file():
            digest.update(f.read_bytes())
    out = out.replace("__BUILD_ID__", digest.hexdigest()[:12])
    WORKER_OUT.write_text(out)
    print("  built %s  (%d questions, %d pages, %.1f KB)"
          % (WORKER_OUT.relative_to(REPO), len(spec["flow"]), len(spec["steps"]), len(out) / 1024))
    return spec


def ensure_project(c):
    """The project, made if needed. Returns its pages.dev address (Cloudflare adds a few letters
    when the name is taken by someone else, so it is read back, not guessed)."""
    p = c["ONBOARDING_PROJECT"]
    r = cf(c, "/accounts/%s/pages/projects/%s" % (c["CLOUDFLARE_ACCOUNT_ID"], p))
    if r.get("success"):
        print("  project %s is there" % p)
    else:
        print("  making project %s" % p)
        r = cf(c, "/accounts/%s/pages/projects" % c["CLOUDFLARE_ACCOUNT_ID"], {"name": p, "production_branch": "main"})
        if not r.get("success"):
            sys.exit("could not make the Pages project: %s" % (r.get("errors") or r.get("_body")))
    sub = (r.get("result") or {}).get("subdomain") or "%s.pages.dev" % p
    print("  its own address: https://%s" % sub)
    return sub


def pages_address(c):
    """The project's pages.dev address, read from Cloudflare."""
    r = cf(c, "/accounts/%s/pages/projects/%s" % (c["CLOUDFLARE_ACCOUNT_ID"], c["ONBOARDING_PROJECT"]))
    return (r.get("result") or {}).get("subdomain") or "%s.pages.dev" % c["ONBOARDING_PROJECT"]


def set_env_vars(c):
    """The worker's settings. The secret key goes in as a secret, so it cannot be
    read back out of Cloudflare afterwards."""
    plain = {"SUPABASE_URL": c["SUPABASE_URL"]}
    secret = {"SUPABASE_SECRET_KEY": c["SUPABASE_SECRET_KEY"]}
    if c["OS_AUTOMATIONS_URL"] and c["OS_SHARED_SECRET"]:
        plain["OS_AUTOMATIONS_URL"] = c["OS_AUTOMATIONS_URL"]
        secret["OS_SHARED_SECRET"] = c["OS_SHARED_SECRET"]
    env_vars = {k: {"type": "plain_text", "value": v} for k, v in plain.items()}
    env_vars.update({k: {"type": "secret_text", "value": v} for k, v in secret.items()})
    r = cf(c, "/accounts/%s/pages/projects/%s" % (c["CLOUDFLARE_ACCOUNT_ID"], c["ONBOARDING_PROJECT"]),
           {"deployment_configs": {"production": {"env_vars": env_vars}, "preview": {"env_vars": env_vars}}},
           method="PATCH")
    if not r.get("success"):
        sys.exit("could not save the settings on the project: %s" % (r.get("errors") or r.get("_body")))
    print("  saved: %s (secrets: %s)" % (", ".join(sorted(plain)), ", ".join(sorted(secret))))
    if not secret.get("OS_SHARED_SECRET"):
        print("  (no OS_AUTOMATIONS_URL yet: new forms are not announced in Slack until tab 3)")


def deploy(c):
    # Only the Cloudflare sign-in in use, so a token left in the terminal never wins over .env.
    env = dict(os.environ)
    for k in CF_SIGN_IN:
        env.pop(k, None)
    env.update({k: c[k] for k in cf_keys(c)})
    cmd = ["npx", "--yes", "wrangler@3", "pages", "deploy", str(SITE),
           "--project-name", c["ONBOARDING_PROJECT"], "--branch", "main", "--commit-dirty=true"]
    print("  $ npx wrangler pages deploy site --project-name %s" % c["ONBOARDING_PROJECT"])
    p = subprocess.run(cmd, cwd=str(APP), env=env, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        sys.exit("wrangler failed (%d):\n%s" % (p.returncode, out[-2500:]))
    for line in out.splitlines():
        if line.strip():
            print("    " + line.strip()[:160])


def find_zone(c, domain):
    """The Cloudflare zone that holds `domain`, or None. Tries each parent name,
    so onboarding.youragency.co.uk finds youragency.co.uk."""
    parts = domain.split(".")
    for i in range(1, len(parts) - 1):
        name = ".".join(parts[i:])
        r = cf(c, "/zones?name=%s" % name)
        if r.get("result"):
            return r["result"][0]
    return None


def attach_domain(c, domain, target):
    """Attach the domain to the project, and add its DNS record (a CNAME to the
    project's pages.dev address) when the domain is on Cloudflare. Returns True
    when the record is in place."""
    r = cf(c, "/accounts/%s/pages/projects/%s/domains" % (c["CLOUDFLARE_ACCOUNT_ID"], c["ONBOARDING_PROJECT"]),
           {"name": domain})
    if not r.get("success") and "already" not in json.dumps(r.get("errors") or "").lower():
        print("  could not attach %s: %s" % (domain, r.get("errors") or r.get("_body")))
    zone = find_zone(c, domain)
    if not zone or zone.get("status") != "active":
        print("  %s is not on Cloudflare (or not active there yet)." % domain)
        print("  Add this record where your domain's DNS is kept, then run this again with --verify-only:")
        print("      type CNAME   name %s   value %s" % (domain.split(".")[0], target))
        return False
    have = (cf(c, "/zones/%s/dns_records?name=%s" % (zone["id"], domain)).get("result") or [])
    rec = {"type": "CNAME", "name": domain, "content": target, "proxied": True, "ttl": 1}
    if have:
        r = cf(c, "/zones/%s/dns_records/%s" % (zone["id"], have[0]["id"]), rec, method="PUT")
    else:
        r = cf(c, "/zones/%s/dns_records" % zone["id"], rec)
    if not r.get("success"):
        print("  could not write the DNS record: %s" % (r.get("errors") or r.get("_body")))
        return False
    print("  DNS: CNAME %s -> %s (proxied)" % (domain, target))
    return True


def domain_status(c, domain):
    """'active', 'pending', ... or None when the domain is not attached. A new
    domain is 'pending' for a few minutes while Cloudflare makes its certificate."""
    r = cf(c, "/accounts/%s/pages/projects/%s/domains" % (c["CLOUDFLARE_ACCOUNT_ID"], c["ONBOARDING_PROJECT"]))
    for x in r.get("result") or []:
        if x.get("name") == domain:
            return x.get("status")
    return None


def save_form_link(c, base):
    """Write the form's address into settings.onboarding_url, then read it back."""
    try:
        supabase(c, "/settings?id=eq.1", {"onboarding_url": base}, method="PATCH")
        back = supabase(c, "/settings?id=eq.1&select=onboarding_url")
    except urllib.error.HTTPError as e:
        print("  could not save the form address in the settings table: %s %s" % (e.code, e.read().decode()[:200]))
        return False
    got = (back or [{}])[0].get("onboarding_url")
    print("  settings.onboarding_url = %s  (%s)" % (got, "read back OK" if got == base else "DIFFERENT, check it"))
    return got == base


class _Follow308(urllib.request.HTTPRedirectHandler):
    """Python 3.9's urlopen does not follow 308."""
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, 301, msg, headers)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.build_opener(_Follow308).open(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001  (a failed check, whatever the reason)
        return type(e).__name__, ""


def verify(base):
    """Check on CONTENT. A parking page answers 200 too."""
    checks = [
        ("/", "Client onboarding", "the start page"),
        ("/form", 'id="rail"', "the form page"),
        ("/form/config.js", "/api/onboarding", "config.js"),
        ("/form/app.js", "ONBOARDING_FORM", "app.js (the form engine)"),
        ("/form/styles.css", "--brand", "styles.css"),
        ("/api/onboarding/flow", '"question_count"', "the server: the questions"),
        # A made-up code: the server must look it up in Supabase and answer "not
        # valid". A wrong secret key answers "server error" here instead.
        ("/api/onboarding/state?code=" + "0" * 32, '"invalid_link":true', "the server reaches Supabase"),
    ]
    bad = 0
    for path, needle, label in checks:
        found, code = False, "-"
        for _ in range(3):
            code, body = fetch(base + path)
            if needle in body:
                found = True
                break
            time.sleep(4)
        print("    %s %s  %s" % ("OK  " if found else "FAIL", code, label))
        bad += 0 if found else 1
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--build-only", action="store_true", help="only make site/_worker.js")
    ap.add_argument("--verify-only", action="store_true", help="check the live site, deploy nothing")
    ap.add_argument("--domain", default=None, help="e.g. onboarding.youragency.com")
    args = ap.parse_args()

    if args.build_only:
        print("1/6 check + build")
        build()
        return

    c = settings()
    domain = (args.domain or c["ONBOARDING_DOMAIN"] or "").strip().lower() or None

    if args.verify_only:
        pages = "https://%s" % pages_address(c)
        base = "https://%s" % domain if domain and domain_status(c, domain) == "active" else pages
        if domain and base == pages:
            print("  %s is not active yet: checking %s instead" % (domain, pages))
        print("checking %s" % base)
        sys.exit(1 if verify(base) else 0)

    print("1/6 check + build")
    build()
    print("2/6 project")
    sub = ensure_project(c)
    pages = "https://%s" % sub
    print("3/6 settings")
    set_env_vars(c)
    print("4/6 deploy")
    deploy(c)
    print("5/6 domain")
    wired = attach_domain(c, domain, sub) if domain else False
    if not domain:
        print("  no domain given: the form is on %s only" % pages)
    status = domain_status(c, domain) if domain else None
    base = "https://%s" % domain if status == "active" else pages
    if domain and status != "active":
        print("  %s is %s. Cloudflare usually needs a few minutes. Then run: "
              "python3 apps/onboarding/tools/deploy.py --verify-only --domain %s" % (domain, status or "not attached", domain))
    print("6/6 form link")
    save_form_link(c, base)

    print("\nchecking %s" % base)
    bad = verify(base)
    if bad:
        sys.exit("\n%d check(s) failed. The form is NOT working yet." % bad)
    print("\nLive: %s/form" % base)
    print("A client's own link: %s/form/<the client's form code>" % base)
    if domain and not wired:
        print("Your domain %s still needs its DNS record (see step 5)." % domain)


if __name__ == "__main__":
    main()
