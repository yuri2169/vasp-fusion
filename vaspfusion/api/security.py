"""Login and audit, in front of every `/api` route.

* **Login.** A request carries the officer's token as `Authorization: Bearer ...` or in
  the session cookie the login sets (HttpOnly, SameSite=Strict, so a page on another
  site can neither read it nor ride on it; cross-origin writes are refused anyway).
  The token is checked on every request, and the account must still exist and be
  enabled.
* **Audit.** Every `/api` request leaves one row: who, which action, on what, the HTTP
  status. Never a request body. A repeat of the same read within 30 seconds (a page
  polling a running trace) is one row; writes are never folded.

The action names are the vocabulary of the log; `ACTIONS` maps each route to one.
"""
from __future__ import annotations

import time

SESSION_COOKIE = "vf_session"
# always answer: is the server up, who am I, let me in, let me out
OPEN_PATHS = frozenset({"/api/health", "/api/auth/me", "/api/auth/login", "/api/auth/logout"})
NOT_LOGGED = frozenset({("GET", "/api/health"), ("GET", "/api/auth/me")})
FOLD_S = 30.0

HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
           "Referrer-Policy": "no-referrer"}

# (method, route template) -> (action, how the target is read from the path / query)
ACTIONS: dict[tuple[str, str], tuple[str, str | None]] = {
    ("POST", "/api/cases"): ("case.open", None),                # target set by the handler
    ("GET", "/api/cases"): ("case.list", None),
    ("GET", "/api/cases/{case_id}"): ("case.view", "case_id"),
    ("GET", "/api/cases/{case_id}.pdf"): ("case.export", "case_id"),
    ("GET", "/api/cases/{case_id}/pdf"): ("case.export", "case_id"),
    ("GET", "/api/cases/{case_id}/receipt"): ("case.receipt", "case_id"),
    ("POST", "/api/cases/{case_id}/verify"): ("case.verify", "case_id"),
    ("GET", "/api/wallets/{chain}/{address}"): ("wallet.view", "chain:address"),
    ("GET", "/api/labels/search"): ("label.search", "?q"),
    ("GET", "/api/desk"): ("desk.view", None),
    ("GET", "/api/vasps/{name}"): ("vasp.view", "name"),
    ("POST", "/api/requests"): ("request.draft", None),         # target set by the handler
    ("GET", "/api/requests/{request_id}"): ("request.view", "request_id"),
    ("PATCH", "/api/requests/{request_id}"): ("request.status", "request_id"),
    ("GET", "/api/requests/{request_id}.pdf"): ("request.export", "request_id"),
    ("GET", "/api/requests/{request_id}/pdf"): ("request.export", "request_id"),
    ("GET", "/api/dashboard"): ("dashboard.view", None),
    ("GET", "/api/model"): ("model.view", None),
    ("GET", "/api/audit"): ("audit.view", None),
    ("POST", "/api/auth/login"): ("auth.login", None),          # target set by the handler
    ("POST", "/api/auth/logout"): ("auth.logout", None),
}

_recent: dict[tuple, float] = {}


def _now() -> float:
    return time.monotonic()


def describe(method: str, template: str | None, path_params: dict, query) -> tuple[str, str | None]:
    """(action, target) of a request, from the route it matched."""
    action, how = ACTIONS.get((method, template or ""), ("api.other", None))
    if how is None:
        return action, None
    if how.startswith("?"):
        return action, (query.get(how[1:]) or "")[:200] or None
    return action, ":".join(str(path_params.get(p, "")) for p in how.split(":"))[:200]


def is_repeat(method: str, key: tuple) -> bool:
    """True for a read that this officer made, with this result, under 30 seconds ago."""
    if method != "GET":
        return False
    now = _now()
    for k in [k for k, t in _recent.items() if now - t > FOLD_S]:
        del _recent[k]
    if key in _recent:
        return True
    _recent[key] = now
    return False


def forget() -> None:
    """Drop the folding memory (tests)."""
    _recent.clear()


def write_row(log, **row) -> None:
    log.append(**row)


def bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None
