"""The one door to every sending vendor (registrar, inbox provider, warm-up tool, DNS check).

Every vendor call goes through `call()`, and `call()` goes through the current transport:

- `HttpTransport` (the default) really sends the request.
- `RecordingTransport` sends nothing. It writes each request (secrets masked) to a list and
  answers from a simulator. A dry run swaps it in, so the "would do" list comes from the same
  code that runs live.

Tests replace the transport (`set_transport`) so no test ever reaches the network.
Standard library only. Never prints or logs a key.
"""

from __future__ import annotations

import copy
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

USER_AGENT = "agency-os-sending/1.0"
SECRET_KEYS = {"apikey", "secretapikey", "authorization", "x-api-key", "x-secret-api-key", "password",
               "api_key", "token", "username"}


class VendorError(RuntimeError):
    """A vendor call failed, or a key it needs is missing."""

    def __init__(self, message: str, status: Optional[int] = None, code: Optional[str] = None) -> None:
        super(VendorError, self).__init__(message)
        self.status = status
        self.code = code


class VendorNotReady(VendorError):
    """The vendor said "not yet" (still setting up, rate limited). The step waits; it has not failed."""


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if str(k).lower() in SECRET_KEYS and v not in (None, "") else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class HttpTransport(object):
    def request(self, method: str, url: str, headers: Dict[str, str], body: Any,
                timeout: int = 30) -> Tuple[int, Any, Dict[str, str]]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, _parse(r.read()), dict(r.headers.items())
        except urllib.error.HTTPError as e:
            return e.code, _parse(e.read()), dict(e.headers.items()) if e.headers else {}
        except urllib.error.URLError as e:
            raise VendorError("{0} cannot be reached: {1}".format(urllib.parse.urlparse(url).netloc, e.reason))


class RecordingTransport(object):
    """Sends nothing. Keeps every request (masked) in `calls` and answers from `responder`."""

    def __init__(self, responder: Optional[Callable[[str, str, Any], Any]] = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.responder = responder

    def request(self, method: str, url: str, headers: Dict[str, str], body: Any,
                timeout: int = 30) -> Tuple[int, Any, Dict[str, str]]:
        self.calls.append({"method": method, "url": url, "body": redact(copy.deepcopy(body))})
        answer = self.responder(method, url, body) if self.responder else None
        if answer is None:
            answer = {"status": "SUCCESS", "simulated": True}
        if isinstance(answer, tuple):
            return answer[0], answer[1], {}
        return 200, answer, {}


_transport: Any = HttpTransport()
_sleep: Callable[[float], None] = time.sleep
_dry_run = False
missing_keys: set = set()


def set_transport(transport: Any) -> Any:
    """Swap the transport. Returns the old one, so the caller can put it back."""
    global _transport
    old = _transport
    _transport = transport
    return old


def dry_run(on: bool) -> None:
    """In a dry run a missing key is not an error: the call shows '<missing:KEY>' and the key is
    listed in `missing_keys`, so the dry run doubles as the list of keys a live run still needs."""
    global _dry_run
    _dry_run = on
    if on:
        missing_keys.clear()


def key(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    if _dry_run:
        missing_keys.add(name)
        return "<missing:{0}>".format(name)
    raise VendorError("{0} is not in .env.".format(name))


def _parse(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return {"_raw": raw[:300].decode("utf-8", "replace")}


def _message(payload: Any) -> Tuple[str, Optional[str]]:
    if isinstance(payload, dict):
        code = payload.get("code")
        msg = payload.get("message") or payload.get("error") or payload.get("_raw") or ""
        return str(msg)[:300], (str(code) if code else None)
    return str(payload)[:300], None


def call(vendor: str, method: str, url: str, body: Any = None, headers: Optional[Dict[str, str]] = None,
         not_ready: Iterable[int] = (), retries_on_429: int = 2, timeout: int = 30) -> Any:
    """One request. Anything but 2xx raises. A 429 is waited out (Retry-After) a few times, then
    raised as VendorNotReady. Statuses in `not_ready` also raise VendorNotReady."""
    all_headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT}
    all_headers.update(headers or {})
    tries = 0
    while True:
        status, payload, resp_headers = _transport.request(method, url, all_headers, body, timeout=timeout)
        if 200 <= status < 300:
            if isinstance(payload, dict) and payload.get("status") == "ERROR":
                msg, code = _message(payload)
                raise VendorError("{0} {1}: {2}".format(vendor, code or "ERROR", msg), status, code)
            return payload
        msg, code = _message(payload)
        if status == 429 and tries < retries_on_429:
            tries += 1
            try:
                _sleep(min(float(resp_headers.get("Retry-After") or resp_headers.get("retry-after") or 10), 60.0))
            except ValueError:
                _sleep(10.0)
            continue
        if status == 429 or status in tuple(not_ready):
            raise VendorNotReady("{0} is not ready (HTTP {1}): {2}".format(vendor, status, msg), status, code)
        raise VendorError("{0} {1} {2} gave HTTP {3}{4}: {5}".format(
            vendor, method, urllib.parse.urlparse(url).path, status, " " + code if code else "", msg), status, code)


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def query(params: Dict[str, Any]) -> str:
    return urllib.parse.urlencode(params)
