"""The parts deploy.py and domain.py share: the .env file, and one call each to Cloudflare,
Porkbun, the Supabase web API and the Supabase Management API.

Python 3.9 or later. No packages to install. Never prints a key.

DRY RUN. When DRY is True, no call leaves this computer. Each call is printed instead (method,
address and body, with every key and password hidden), and a made-up answer comes back, so the
script can show every step it would take.
"""

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent                      # apps/os/frontend
REPO = APP.parent.parent.parent        # the top of the repo

CF = "https://api.cloudflare.com/client/v4"
PORKBUN = "https://api.porkbun.com/api/json/v3"
SUPABASE_API = "https://api.supabase.com/v1/projects"

DRY = False
SECRET_WORDS = ("key", "secret", "password", "token", "authorization")


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


# The Cloudflare sign-in: an API token (the way tab 2 teaches), or the global API key with its
# email as a fallback. A token is used whenever one is set.
CF_SIGN_IN = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL")


def env(keys):
    """The values of `keys`, from the environment first, then from .env at the top of the repo."""
    e = read_env(REPO / ".env")
    out = {k: os.environ.get(k) or e.get(k, "") for k in keys}
    # A token left in the terminal from other work must not replace the global key that .env holds.
    if "CLOUDFLARE_API_TOKEN" in out and e.get("CLOUDFLARE_API_KEY") and not e.get("CLOUDFLARE_API_TOKEN"):
        out["CLOUDFLARE_API_TOKEN"] = ""
    if DRY:   # a dry run shows a name in place of anything not filled in yet
        out = {k: v or "<%s>" % k for k, v in out.items()}
    return out


def filled(c, k):
    return bool(c.get(k)) and c[k] != "<%s>" % k


def need(c, keys, why):
    missing = [k for k in keys if not filled(c, k)]
    if missing and not DRY:
        sys.exit("These are empty in .env: %s\n(%s)\nAdd them to .env (never to the chat), then run this again."
                 % (", ".join(missing), why))


def uses_token(c):
    """True when the Cloudflare calls use CLOUDFLARE_API_TOKEN: always when it is set, and when
    neither sign-in is set (then the token is the one to ask for)."""
    return filled(c, "CLOUDFLARE_API_TOKEN") or not filled(c, "CLOUDFLARE_API_KEY")


def cf_keys(c):
    """The .env names the Cloudflare calls need with the sign-in in use."""
    sign_in = ("CLOUDFLARE_API_TOKEN",) if uses_token(c) else ("CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL")
    return sign_in + ("CLOUDFLARE_ACCOUNT_ID",)


def cf_env(c, extra=None):
    """The environment for a command (wrangler): only the Cloudflare sign-in in use, so a token
    left in the terminal never wins over the one in .env."""
    e = dict(os.environ)
    for k in CF_SIGN_IN:
        e.pop(k, None)
    e.update({k: c[k] for k in cf_keys(c)})
    e.update(extra or {})
    return e


def hide(value, masked=False):
    """A copy of a body with every value under a key, secret, password or token name replaced by ***."""
    if isinstance(value, dict):
        return {k: hide(v, masked or any(w in k.lower() for w in SECRET_WORDS)) for k, v in value.items()}
    if isinstance(value, list):
        return [hide(v, masked) for v in value]
    return "***" if masked and isinstance(value, str) else value


def show_call(service, method, url, body):
    line = "  [dry run] %-10s %-6s %s" % (service, method, url)
    if body is not None:
        line += "\n               body: " + json.dumps(hide(body))
    print(line)


def _send(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text.strip() else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode()[:800]
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, {"_body": text}


# A made-up answer for each call in a dry run, picked by the start of its address.
FAKE = []


def fake(prefix, method, answer):
    FAKE.append((prefix, method, answer))


def _fake_answer(path, method):
    for prefix, m, answer in FAKE:
        if path.startswith(prefix) and (m is None or m == method):
            return answer(path) if callable(answer) else answer
    return {"success": True, "result": {}}


def cf_auth(c):
    if uses_token(c):
        return {"Authorization": "Bearer " + c["CLOUDFLARE_API_TOKEN"]}
    return {"X-Auth-Email": c["CLOUDFLARE_EMAIL"], "X-Auth-Key": c["CLOUDFLARE_API_KEY"]}


def cf(c, path, data=None, method=None):
    """One Cloudflare API call, with the API token (or the global API key as a fallback)."""
    method = method or ("POST" if data is not None else "GET")
    if DRY:
        show_call("Cloudflare", method, path, data)
        return _fake_answer(path, method)
    req = urllib.request.Request(
        CF + path, data=json.dumps(data).encode() if data is not None else None, method=method,
        headers=dict(cf_auth(c), **{"Content-Type": "application/json"}))
    status, out = _send(req, 90)
    out = out if isinstance(out, dict) else {}
    if status >= 400:
        out.update({"success": False, "_status": status})
    return out


def porkbun(c, path, data=None):
    """One Porkbun API call. The keys go in the headers, never in the printed body."""
    body = dict(data or {})
    if DRY:
        show_call("Porkbun", "POST", path, body)
        return _fake_answer("porkbun:" + path, "POST")
    req = urllib.request.Request(
        PORKBUN + path, data=json.dumps(body).encode(), method="POST",
        headers={"X-API-Key": c["PORKBUN_API_KEY"], "X-Secret-API-Key": c["PORKBUN_SECRET_KEY"],
                 "Content-Type": "application/json"})
    status, out = _send(req, 60)
    out = out if isinstance(out, dict) else {}
    if status >= 400 and out.get("status") != "ERROR":
        out.update({"status": "ERROR", "message": out.get("message") or out.get("_body") or str(status)})
    return out


def supabase(c, path, data=None, method="GET", auth=False):
    """One call to the project's own web API with the secret key. auth=True: /auth/v1, else /rest/v1."""
    base = "/auth/v1" if auth else "/rest/v1"
    if DRY:
        show_call("Supabase", method, base + path, data)
        return 200, _fake_answer("supabase:" + base + path, method)
    key = c["SUPABASE_SECRET_KEY"]
    req = urllib.request.Request(
        c["SUPABASE_URL"].rstrip("/") + base + path, data=json.dumps(data).encode() if data is not None else None,
        method=method, headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json",
                                "Prefer": "return=representation"})
    return _send(req, 30)


def management(c, path, data=None, method="GET"):
    """One call to the Supabase Management API with the personal access token from tab 1."""
    url = "%s/%s%s" % (SUPABASE_API, c["SUPABASE_PROJECT_REF"] or "<project ref>", path)
    if DRY:
        show_call("Supabase", method, url.replace(SUPABASE_API, "management:/v1/projects"), data)
        return 200, _fake_answer("management:" + path, method)
    req = urllib.request.Request(
        url, data=json.dumps(data).encode() if data is not None else None, method=method,
        headers={"Authorization": "Bearer " + c["SUPABASE_ACCESS_TOKEN"], "Content-Type": "application/json",
                 "User-Agent": "agency-os-deploy"})
    return _send(req, 30)


def find_zone(c, domain):
    """The Cloudflare zone that holds `domain`, or None. Tries each parent name, so
    app.youragency.co.uk finds youragency.co.uk."""
    parts = domain.split(".")
    for i in range(0, len(parts) - 1):
        r = cf(c, "/zones?name=%s" % ".".join(parts[i:]))
        if r.get("result"):
            return r["result"][0]
    return None


def cname(c, zone, host, target):
    """Make or update one proxied CNAME in a Cloudflare zone. True when it is in place."""
    have = cf(c, "/zones/%s/dns_records?name=%s" % (zone["id"], host)).get("result") or []
    rec = {"type": "CNAME", "name": host, "content": target, "proxied": True, "ttl": 1}
    if have:
        r = cf(c, "/zones/%s/dns_records/%s" % (zone["id"], have[0]["id"]), rec, method="PUT")
    else:
        r = cf(c, "/zones/%s/dns_records" % zone["id"], rec)
    if not r.get("success"):
        print("  could not write the DNS record: %s" % (r.get("errors") or r.get("_body")))
        return False
    print("  DNS on Cloudflare: CNAME %s -> %s (proxied)" % (host, target))
    return True


def resolve(name, rtype):
    """What the public DNS says for `name` (a list of answers), through Cloudflare's DNS over HTTPS."""
    if DRY:
        show_call("DNS", "GET", "https://cloudflare-dns.com/dns-query?name=%s&type=%s" % (name, rtype), None)
        return []
    req = urllib.request.Request("https://cloudflare-dns.com/dns-query?name=%s&type=%s" % (name, rtype),
                                 headers={"Accept": "application/dns-json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception:  # noqa: BLE001  (no answer is the same as "not yet")
        return []
    return [a.get("data", "").rstrip(".") for a in data.get("Answer") or []]
