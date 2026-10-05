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
# Routes with an API key of their own instead of an officer's login (docs/sahyog_contract.md).
OWN_KEY_PREFIX = "/api/sahyog/"
NOT_LOGGED = frozenset({("GET", "/api/health"), ("GET", "/api/auth/me")})
FOLD_S = 30.0

HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
           "Referrer-Policy": "no-referrer"}

# (method, route template) -> (action, how the target is read from the path / query)
ACTIONS: dict[tuple[str, str], tuple[str, str | None]] = {
    ("POST", "/api/cases"): ("case.open", None),                # target set by the handler
    ("GET", "/api/cases"): ("case.list", None),
    ("POST", "/api/cases/batch"): ("batch.upload", None),       # target set by the handler
    ("GET", "/api/batches"): ("batch.list", None),
    ("GET", "/api/batches/{batch_id}"): ("batch.view", "batch_id"),
    ("GET", "/api/batches/{batch_id}/results.csv"): ("batch.export", "batch_id"),
    ("GET", "/api/scale"): ("scale.view", None),
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
    ("GET", "/api/labels/coverage"): ("label.coverage", None),
    ("GET", "/api/watchlist"): ("watch.list", None),
    ("POST", "/api/watchlist"): ("watch.add", None),            # target set by the handler
    ("POST", "/api/watchlist/{watch_id}/check"): ("watch.check", "watch_id"),
    ("POST", "/api/watchlist/{watch_id}/seen"): ("watch.seen", "watch_id"),
    ("DELETE", "/api/watchlist/{watch_id}"): ("watch.remove", "watch_id"),
    ("GET", "/api/model"): ("model.view", None),
    ("GET", "/api/fx"): ("fx.view", None),
    ("GET", "/api/audit"): ("audit.view", None),
    ("GET", "/api/coverage"): ("coverage.view", None),
    # SAHYOG, system to system: its own API key, no officer (G2)
    ("POST", "/api/sahyog/complaints"): ("sahyog.complaint", None),   # target set by the handler
    ("GET", "/api/sahyog/complaints/{complaint_ref}"): ("sahyog.status", "complaint_ref"),
    ("POST", "/api/sahyog/requests/{request_id}/replies"): ("sahyog.reply", "request_id"),
    # the simulator screen, which plays the portal's side for the signed-in officer
    ("GET", "/api/sahyog-sim"): ("sim.view", None),
    ("POST", "/api/sahyog-sim/complaints"): ("sim.complaint", None),  # target set by the handler
    ("POST", "/api/sahyog-sim/requests/{request_id}/reply"): ("sim.reply", "request_id"),
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
    """True for a read that this officer made, from this address, with this result, under
    30 seconds ago. Nothing is remembered here: `remember` does that once the row is
    written, so a row that failed to write is tried again on the next request."""
    if method != "GET":
        return False
    now = _now()
    for k in [k for k, t in _recent.items() if now - t > FOLD_S]:
        del _recent[k]
    return key in _recent


def remember(method: str, key: tuple) -> None:
    if method == "GET":
        _recent[key] = _now()


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
