"""FastAPI surface. Every route in docs/api_contract.md is declared here with its
response model, so the OpenAPI schema (and ui/src/api/types.ts) is complete from
day one.

Until the backend phases land, routes answer from mocks/*.json (validated
against the same models) and say so in the `X-Data-Source` header. Live so far:
the label store (B1: label search, wallet labels), cases (B3: POST traces the
wallet in the background and stores the result in data/case.duckdb; the three
mock demo cases stay listed after the live ones), the model (B6/B7) and the request
desk (B8: desk, VASP pages, requests and letter PDFs, from the case store and
data/desk.duckdb; the mock desk answers until a finished case names an exchange).
The dashboard is still mock, apart from its label coverage.

Login and audit (B9, api/security.py): every `/api` request leaves a row in the audit
log. A login is required once an officer account exists (`cli officer add`), or when
VASPFUSION_AUTH=required; with no account the tool answers as a single-officer
workstation, as BTC-FUSION did, and the log says "not signed in".
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import chains
from ..auth import tokens
from ..auth.officers import USERNAME, Locked, Officers
from ..cases import case_id_for, file_sha256, run_case, skeleton, trace_provider
from ..explain.progress import progress_sentence
from ..labels.lookup import DEFAULT_DB, LabelStore
from ..screening import screen
from ..store.audit import AuditLog
from ..store.cases import SUMMARY_KEYS, CaseStore
from ..store.queue import JobQueue, worker_name
from .. import risk as R
from ..trace import DEFAULT_WALLETS, TraceConfig
from . import schemas as S
from . import security

ROOT = Path(__file__).resolve().parents[2]
MOCKS = ROOT / "mocks"
LABEL_DB = DEFAULT_DB
MODEL_DIR = ROOT / "artifacts" / "model_v1"   # metrics.json per chain (`make model`)
ABSTAIN_DIR = ROOT / "artifacts" / "abstain_v1"   # validation.json per chain (`make abstain-eval`)
CASE_DB: Path | None = None      # None = data/case.duckdb (or VASPFUSION_CASE_DB)
DESK_DB: Path | None = None      # None = data/desk.duckdb (or VASPFUSION_DESK_DB)
WATCH_DB: Path | None = None     # None = data/watch.duckdb (or VASPFUSION_WATCH_DB)
OUTBOX: Path | None = None       # None = data/sahyog_outbox (or VASPFUSION_SAHYOG_OUTBOX)
DIRECTORY = ROOT / "data" / "vasp_directory.yaml"   # cited facts only (B8)
OFFICERS: Path | None = None     # None = data/officers.json (or VASPFUSION_OFFICERS)
AUDIT_DB: Path | None = None     # None = data/audit.duckdb (or VASPFUSION_AUDIT_DB)
AUTH_SECRET: Path | None = None  # None = data/auth_secret (or VASPFUSION_JWT_SECRET)
AUTH: str | None = None          # None = VASPFUSION_AUTH, else "auto"; "off" | "required"
SAHYOG_KEY: Path | None = None   # None = data/sahyog_api_key (or VASPFUSION_SAHYOG_KEY_FILE)
VERSION = "0.1.0"
# Chains a trace can run on today. BSC has no free data source; Solana and Avalanche
# have no adapter yet (PROGRESS.md, B2). Bitcoin is traced since B5 (chains/btc.py: an
# address's pro-rata share of each transaction; cluster.py: labels by co-spending).
TRACEABLE = ("tron", "ethereum", "bsc", "polygon", "arbitrum", "base", "optimism", "bitcoin",
             "solana")

app = FastAPI(title="VASP-FUSION",
              description="Nearest-VASP attribution for unknown crypto wallets, with "
                          "calibrated confidence. SIH 2026 · PS 26182 · I4C.",
              version=VERSION)

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def cross_origin_write(method: str, origin: str | None, host: str | None) -> bool:
    """A page on another site can still SEND a form POST - it is a CORS simple
    request, so no preflight - and dropping CORS only stops it reading the reply.
    Refusing on Origin is what stops the write."""
    if method in ("GET", "HEAD", "OPTIONS") or origin is None:
        return False
    o = urlsplit(origin)
    return not (o.netloc == (host or "") or o.hostname in _LOOPBACK)


@app.middleware("http")
async def refuse_cross_origin_writes(request: Request, call_next):
    if cross_origin_write(request.method, request.headers.get("origin"),
                          request.headers.get("host")):
        return JSONResponse({"detail": "cross-origin write refused"}, status_code=403)
    return await call_next(request)


# ------------------------------------------------------------------ login + audit (B9)
def auth_required() -> bool:
    """auto (the default): a login is required as soon as one officer account exists."""
    mode = (AUTH or os.environ.get("VASPFUSION_AUTH") or "auto").strip().lower()
    if mode == "off":
        return False
    if mode == "required":
        return True
    # any account, disabled or not: disabling the last officer must not open the tool
    return Officers(OFFICERS).exists()


def _officer_of(request: Request) -> dict | None:
    """The signed-in officer: a valid token (header or session cookie) for an account
    that still exists and is enabled."""
    token = security.bearer(request.headers.get("authorization")) \
        or request.cookies.get(security.SESSION_COOKIE)
    if not token:
        return None
    try:
        claims = tokens.check(token, tokens.load_secret(AUTH_SECRET))
        sub = claims.get("sub")
        return Officers(OFFICERS).get(sub) if isinstance(sub, str) else None
    except tokens.TokenError:
        return None
    except Exception:  # noqa: BLE001 - whatever a hostile header breaks, it is not a login
        return None


def _route_of(request: Request) -> tuple[str | None, dict]:
    from starlette.routing import Match
    for route in app.router.routes:
        match, child = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", None), child.get("path_params", {})
    return None, {}


def _note(request: Request, target: str | None = None, **detail) -> None:
    """What a handler adds to its audit row (never anything from a request body beyond
    the wallet, the exchange and the status it names)."""
    audit = getattr(request.state, "audit", None)
    if audit is not None:
        if target is not None:
            audit["target"] = target
        if detail:
            audit["detail"] = detail


def _by(request: Request) -> str | None:
    officer = getattr(request.state, "officer", None)
    return officer["username"] if officer else None


# Added after refuse_cross_origin_writes, so it wraps it: a refused write is logged too.
@app.middleware("http")
async def login_and_audit(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/"):
        response = await call_next(request)
        for k, v in security.HEADERS.items():
            response.headers.setdefault(k, v)
        return response
    officer = _officer_of(request)
    request.state.officer = officer
    request.state.audit = {}
    own_key = path.startswith(security.OWN_KEY_PREFIX)      # the route checks its API key
    if auth_required() and officer is None and path not in security.OPEN_PATHS and not own_key:
        response = JSONResponse({"detail": "Sign in to continue."}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
    else:
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - a request that broke the server is logged too
            response = JSONResponse({"detail": "The server could not answer this request. "
                                               "It has been logged."}, status_code=500)
    template, params = _route_of(request)
    if (request.method, template) not in security.NOT_LOGGED:
        action, target = security.describe(request.method, template, params,
                                           request.query_params)
        target = request.state.audit.get("target", target)
        who = officer["username"] if officer else None
        client = request.client.host if request.client else None
        fold = (who, client, action, target, response.status_code)
        if not security.is_repeat(request.method, fold):
            try:
                security.write_row(
                    AuditLog(AUDIT_DB), officer=who, action=action, target=target,
                    method=request.method,
                    path=path + (f"?{request.url.query}" if request.url.query else ""),
                    status=response.status_code, client=client,
                    detail=request.state.audit.get("detail"))
                security.remember(request.method, fold)
            except Exception:  # noqa: BLE001 - no reply without its audit row
                response = JSONResponse(
                    {"detail": "The audit log could not be written, so the reply is "
                               "withheld. The action itself may have been carried out. "
                               "Check the disk and data/audit.duckdb."}, status_code=503)
    for k, v in security.HEADERS.items():
        response.headers[k] = v
    response.headers.setdefault("Cache-Control", "no-store")
    return response


# ------------------------------------------------------------------ mocks
# Which model each mock file validates against. Paths mirror the API's URLs.
MOCK_MODELS: list[tuple[str, type[BaseModel]]] = [
    (r"cases", S.CaseList),
    (r"cases/[^/]+", S.CaseDetail),
    (r"cases/[^/]+/receipt", S.Receipt),
    (r"cases/[^/]+/context", S.CaseContext),
    (r"wallets/[^/]+/[^/]+", S.WalletDetail),
    (r"labels/search", S.LabelSearch),
    (r"desk", S.Desk),
    (r"vasps/[^/]+", S.VaspDetail),
    (r"requests", S.RequestList),
    (r"requests/[^/]+", S.RequestDetail),
    (r"dashboard", S.Dashboard),
    (r"model", S.ModelInfo),
    (r"labels/coverage", S.LabelCoverage),
    (r"watchlist", S.WatchList),
    (r"audit", S.AuditPage),
    (r"auth/me", S.Me),
    (r"fx", S.FxRate),
    (r"coverage", S.PsCoverage),
    (r"sahyog-sim", S.SahyogSim),
    (r"batches", S.BatchList),
    (r"batches/[^/]+", S.BatchDetail),
    (r"scale", S.ScaleMetrics),
]

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._&-]{0,99}$")


def mock_model_for(rel: str) -> type[BaseModel]:
    for pattern, model in MOCK_MODELS:
        if re.fullmatch(pattern, rel):
            return model
    raise KeyError(rel)


def load_mock(rel: str) -> dict:
    """Read mocks/<rel>.json, minus the top-level `_demo` markers."""
    if not all(_SAFE.match(p) for p in rel.split("/")):
        raise HTTPException(404, "not found")
    path = MOCKS / f"{rel}.json"
    if MOCKS.resolve() not in path.resolve().parents or not path.exists():
        raise HTTPException(404, "not found")
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def demo_mode() -> bool:
    """VASPFUSION_DEMO_MODE=1: the fixtures in mocks/ stand in where a store is empty
    (three fixture cases, a fixture desk, dashboard, request and model). Off, which is
    the default, every answer comes from the stores: an empty store gives an empty
    answer, an unknown id a 404."""
    return os.environ.get("VASPFUSION_DEMO_MODE", "").strip().lower() in ("1", "true", "on", "yes")


def demo_fixture(rel: str, missing: str) -> dict:
    """mocks/<rel>.json in demo mode; otherwise (and for an unknown one) 404 `missing`."""
    if demo_mode():
        try:
            return load_mock(rel)
        except HTTPException:
            pass
    raise HTTPException(404, missing)


def _no_case(case_id: str) -> str:
    return (f"There is no case with the id {case_id[:80]}. Open one from the wallet's "
            "address, or pick it from the list of cases.")


def _no_request(request_id: str) -> str:
    return (f"There is no request with the id {request_id[:80]}. Open it from the request "
            "desk or the register.")


LABELS_MISSING = "The label database is missing. Run `make labels` first."


def _source(response: Response, kind: str) -> None:
    response.headers["X-Data-Source"] = kind


def _labels() -> LabelStore | None:
    return LabelStore(LABEL_DB) if Path(LABEL_DB).exists() else None


# ------------------------------------------------------------------ live seams
def make_fetcher() -> chains.Fetcher:
    """Cache-first, OFFLINE=1 aware. Tests swap this for a replaying fetcher."""
    return chains.default_fetcher()


def _cases() -> CaseStore:
    return CaseStore(CASE_DB)


_label_sha: dict[tuple[str, float], str] = {}


def label_db_sha256() -> str | None:
    """SHA-256 of the label DB file, for provenance; rehashed only when the file changes."""
    path = Path(LABEL_DB)
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _label_sha:
        _label_sha[key] = file_sha256(path)
    return _label_sha[key]


# ------------------------------------------------------------------ health
@app.get("/api/health", response_model=S.Health)
def health():
    from ..provenance import git_state
    return S.Health(status="ok", version=VERSION, label_db=Path(LABEL_DB).exists(),
                    data_mode="mixed" if demo_mode() else "live", auth_required=auth_required(),
                    offline=chains.cache.offline_mode(), git_commit=git_state()[0])


@app.get("/api/fx", response_model=S.FxRate)
def get_fx(response: Response):
    """The reference rate rupee amounts are shown at, with its date and source."""
    from .. import fx
    rate = fx.usd_inr()
    _source(response, "live")
    return {**rate, "basis": fx.basis(rate)}


# ------------------------------------------------------------------ login (B9)
@app.post("/api/auth/login", response_model=S.LoginResult)
def login(body: S.Login, request: Request, response: Response):
    """Sign in. The token comes back in the body and as an HttpOnly session cookie; either
    is accepted on later requests. 401 for a wrong user name or password (the same words
    for both), 429 while an account is locked after five wrong passwords."""
    username = body.username.strip().lower()
    book = Officers(OFFICERS)
    # what was typed is logged only when it is the name of an account: a password typed
    # into the wrong box must not end up in the log
    known = bool(USERNAME.match(username)) and book.known(username)
    _note(request, target=username if known else "(unknown user name)")
    try:
        officer = book.verify(username, body.password)
    except Locked as e:
        raise HTTPException(429, str(e)) from None
    if officer is None:
        raise HTTPException(401, "Wrong user name or password.")
    now = datetime.now(timezone.utc)
    token = tokens.issue({"sub": officer["username"], "name": officer["name"]},
                         tokens.load_secret(AUTH_SECRET), now=now.timestamp())
    response.set_cookie(security.SESSION_COOKIE, token, max_age=tokens.TTL_S, httponly=True,
                        samesite="strict", path="/api", secure=request.url.scheme == "https")
    return {"token": token, "token_type": "bearer",
            "expires_at": now + timedelta(seconds=tokens.TTL_S), "officer": officer}


@app.post("/api/auth/logout", response_model=S.Ok)
def logout(response: Response):
    """Clear the session cookie. A token already handed out stays valid until it expires
    (8 hours) or its account is disabled."""
    response.delete_cookie(security.SESSION_COOKIE, path="/api")
    return {"ok": True}


@app.get("/api/auth/me", response_model=S.Me)
def me(request: Request):
    """Who is signed in, and whether a login is required at all. Always answers."""
    return {"auth_required": auth_required(),
            "officer": getattr(request.state, "officer", None)}


@app.get("/api/audit", response_model=S.AuditPage)
def get_audit(response: Response, limit: int = Query(100, ge=1, le=500),
              offset: int = Query(0, ge=0), officer: str | None = None,
              action: str | None = Query(None, description="An action (`case.view`) or a "
                                                           "family (`case`)"),
              target: str | None = Query(None, description="e.g. a case id: everything "
                                                           "done on that case"),
              verify: bool = Query(False, description="Recompute the whole hash chain")):
    """The audit log, newest first: who looked up what, and when."""
    log = AuditLog(AUDIT_DB)
    total, items = log.list(limit=limit, offset=offset, officer=officer, action=action,
                            target=target)
    _source(response, "live")
    return {"total": total, "limit": limit, "offset": offset, "items": items,
            "chain": log.verify_chain() if verify else None}


# ------------------------------------------------------------------ cases (B3)
def _demo_cases() -> list[dict]:
    return load_mock("cases")["items"] if demo_mode() else []


def _resolve(body: S.CaseCreate) -> tuple[str, str]:
    """(chain, address as the adapters and the label store spell it), or a 422."""
    address = body.address.strip()
    try:
        chain = body.chain or chains.detect_chain(address)
    except chains.InvalidAddress:
        raise HTTPException(422, "Could not tell which chain this address is on. "
                                 "Pick the chain and try again.") from None
    if not chains.validate(address, chain):
        raise HTTPException(422, f"{address[:64]} is not a valid {chain} address. Check it "
                                 "was copied whole, or pick another chain.")
    if chain not in TRACEABLE:
        raise HTTPException(422, f"Tracing is not available on {chain} yet. Supported "
                                 f"chains: {', '.join(TRACEABLE)}.")
    if chain in chains.EVM_FAMILY or address.lower().startswith("bc1"):
        address = address.lower()
    return chain, address


# Cases this process is tracing right now. A stored case that says queued/running but
# is not in here was orphaned (the server stopped mid-trace) and is run again on request.
# One server process is assumed, as everywhere else in this single-workstation tool.
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
# What each of those traces has read so far (`trace(on_progress=)`), for the officer who is
# watching the case. Kept here and never stored: a stored case is a result, with digests.
_PROGRESS: dict[str, dict] = {}
_NOTHING_READ = {"phase": "reading", "asset": None, "hop": 0, "wallets_read": 0,
                 "transfers_read": 0, "reached": []}


def _note_progress(case_id: str, snapshot: dict) -> None:
    with _ACTIVE_LOCK:
        _PROGRESS[case_id] = snapshot


# ------------------------------------------------------------------ the trace queue (G5)
# Every trace is a row in the queue (store/queue.py, a table in the case store) before it
# runs, so a restart loses nothing that was waiting. Who runs it depends on WORKERS:
# 0 (the default): this process, after the request has answered, one at a time;
# n > 0: a pool of n worker processes (workers.py). This process still claims every job
# and writes every result, so the case store has one writer; the workers only trace.
WORKERS: int | None = None       # None = VASPFUSION_WORKERS, else 0
_POOL = None                     # the running WorkerPool, when this server started one


def _queue() -> JobQueue:
    return JobQueue(CASE_DB)


def pool_size() -> int:
    if WORKERS is not None:
        return max(0, WORKERS)
    try:
        return max(0, int(os.environ.get("VASPFUSION_WORKERS", "0") or 0))
    except ValueError:
        return 0


def _tracing(case_id: str) -> bool:
    """Is the case waiting for a trace or being traced, here or in a worker?"""
    with _ACTIVE_LOCK:
        if case_id in _ACTIVE:
            return True
    return _queue().active(case_id)


def trace_only(queued: dict, max_hops: int, incident: datetime | None,
               budget: dict | None = None, on_progress=None, stats: dict | None = None,
               label_sha: str | None = None) -> dict:
    """Trace the wallet of a stored (queued) case and return the finished case. It reads
    the chain cache and the label store and writes nothing but the cache, so it runs the
    same in this process and in a worker. `budget` is the officer's (max_wallets,
    max_seconds); `stats`, when given, is filled with what the run read."""
    last: dict = {}

    def note(snapshot: dict) -> None:
        last.update(snapshot)
        if on_progress is not None:
            on_progress(snapshot)

    budget = budget or {}
    cfg = TraceConfig(max_hops=max_hops, since=incident,
                      max_nodes=budget.get("max_wallets") or DEFAULT_WALLETS,
                      max_seconds=budget.get("max_seconds"))
    fetcher = make_fetcher()
    try:
        provider = trace_provider(queued["chain"], fetcher, cfg)
        with LabelStore(LABEL_DB) as labels:
            detail = run_case(
                queued["address"], queued["chain"], provider, labels, case_id=queued["id"],
                meta=queued, cfg=cfg, fetcher=fetcher,
                label_db_sha256=label_sha or label_db_sha256(),
                now=datetime.fromisoformat(queued["created_at"].replace("Z", "+00:00")),
                demo=bool(queued.get("demo")),      # a demo wallet traced again is still one
                on_progress=note)
    finally:
        try:
            fetcher.close()                 # a replay holds the cache file open until here
        except Exception:  # noqa: BLE001
            pass
    if stats is not None:
        stats.update(transfers_read=last.get("transfers_read", 0),
                     wallets_read=last.get("wallets_read", 0),
                     transfers=len(detail["graph"]["edges"]),
                     pages=detail["provenance"].get("pages") or 0)
    return detail


def _store_failure(case_id: str, why: str, previous: dict | None) -> None:
    """The trace failed: the case says so, or keeps the result it had before a refresh."""
    try:
        if previous is not None:
            _cases().save({**previous, "status": "done", "error":
                           f"Refresh failed ({why}). Showing the result of "
                           f"{previous['created_at']}."})
        else:
            _cases().set_status(case_id, "failed", error=why)
    except Exception:  # noqa: BLE001 - the store itself is down; nothing more to record
        pass


def _run_case(case_id: str, max_hops: int, incident: datetime | None,
              previous: dict | None = None, budget: dict | None = None,
              stats: dict | None = None) -> str | None:
    """Trace the wallet in this process and store the result. `previous` is the finished
    case being refreshed: it is kept if the new run fails. Returns the error, or None
    when the case was stored."""
    try:
        store = _cases()
        queued = store.get(case_id)
        store.set_status(case_id, "running")
        _note_progress(case_id, dict(_NOTHING_READ))
        detail = trace_only(queued, max_hops, incident, budget,
                            lambda snapshot: _note_progress(case_id, snapshot), stats)
        store.save(detail)
        _notify_sahyog(case_id)
        return None
    except Exception as e:  # noqa: BLE001 - whatever went wrong, the case must say so
        why = f"{type(e).__name__}: {e}"[:500]
        _store_failure(case_id, why, previous)
        return why
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(case_id)
            _PROGRESS.pop(case_id, None)


def _peak_mb() -> float | None:
    """This process's peak resident memory, in MB (None where it cannot be read)."""
    try:
        import resource
        import sys
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(peak / (1 << 20 if sys.platform == "darwin" else 1 << 10), 1)
    except Exception:  # noqa: BLE001 - not on this platform
        return None


def _job_args(job: dict, stored: dict | None) -> tuple[datetime | None, dict | None, dict]:
    """A claimed job's (start date, the result to keep if a refresh fails, budget)."""
    params = job["params"]
    previous = None
    if params.get("previous_created_at") and stored is not None:
        # a refresh: what is stored is still the old result, marked queued
        previous = {**stored, "status": "done", "error": None,
                    "created_at": params["previous_created_at"]}
    since = params.get("since")
    return (datetime.fromisoformat(since) if since else None, previous,
            {k: params.get(k) for k in ("max_wallets", "max_seconds")})


def work_one(case_id: str | None = None, worker: str | None = None) -> bool:
    """Claim one job from the queue (the named case's, or the oldest) and trace it in
    this process. False when there was nothing to claim. The request's background task
    and the start-up drain come through here."""
    queue = _queue()
    worker = worker or worker_name()
    job = queue.claim(worker, case_id)
    if job is None:
        if case_id is not None:
            with _ACTIVE_LOCK:
                _ACTIVE.discard(case_id)
        return False
    cid = job["case_id"]
    with _ACTIVE_LOCK:
        _ACTIVE.add(cid)
    incident, previous, budget = _job_args(job, _cases().get(cid))
    stats: dict = {}
    started, error = time.perf_counter(), "the trace was interrupted"
    try:
        with queue.working(cid, worker):
            error = _run_case(cid, job["params"].get("max_hops", 3), incident, previous,
                              budget, stats)
    finally:
        stats["seconds"] = round(time.perf_counter() - started, 4)
        stats["peak_mb"] = _peak_mb()
        try:
            queue.finish(cid, worker, "failed" if error else "done", stats=stats, error=error)
        except Exception:  # noqa: BLE001 - the store is down; the job will be taken again
            pass
        with _ACTIVE_LOCK:
            _ACTIVE.discard(cid)
            _PROGRESS.pop(cid, None)
    return True


# The pool's side of a job (workers.py): this process marks the case running and hands
# the worker everything it needs; the worker traces and hands the case back; this
# process stores it. The case store is only ever written here.
def begin_job(job: dict) -> dict | None:
    """Mark a claimed job's case running. Returns what a worker needs to trace it, or
    None when the case no longer exists."""
    cid = job["case_id"]
    store = _cases()
    queued = store.get(cid)
    if queued is None:
        return None
    store.set_status(cid, "running")
    with _ACTIVE_LOCK:
        _ACTIVE.add(cid)
    _note_progress(cid, dict(_NOTHING_READ))
    return {"case_id": cid, "queued": queued, "params": job["params"],
            "label_sha": label_db_sha256()}


def end_job(job: dict, payload: dict, result: dict, worker: str) -> None:
    """Store what a worker handed back (`{"detail": ...}` or `{"error": ...}`, with
    `stats`) and close the job."""
    cid = job["case_id"]
    error = result.get("error")
    try:
        if error is None:
            try:
                _cases().save(result["detail"])
                _notify_sahyog(cid)
            except Exception as e:  # noqa: BLE001 - a result that cannot be stored is a failure
                error = f"{type(e).__name__}: {e}"[:500]
        if error is not None:
            _store_failure(cid, error, _job_args(job, payload["queued"])[1])
        _queue().finish(cid, worker, "failed" if error else "done",
                        stats=result.get("stats"), error=error)
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(cid)
            _PROGRESS.pop(cid, None)


def release_job(job: dict, worker: str) -> None:
    """A worker process died with this job: queue it again (or, after three tries, fail
    it and say so on the case)."""
    cid = job["case_id"]
    try:
        if _queue().release(cid, worker) == "failed":
            _cases().set_status(cid, "failed", error=GAVE_UP)
        else:
            _cases().set_status(cid, "queued")
    except Exception:  # noqa: BLE001
        pass
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(cid)
            _PROGRESS.pop(cid, None)


GAVE_UP = ("The trace stopped three times before it finished. Trace the wallet again, or "
           "with a smaller budget.")


def recover() -> tuple[list[str], list[str]]:
    """Queue again the jobs whose process died; a case that has stopped its trace three
    times is marked failed. Returns (requeued, failed)."""
    again, failed = _queue().requeue_stale()
    for cid in failed:
        try:
            _cases().set_status(cid, "failed", error=GAVE_UP)
        except Exception:  # noqa: BLE001
            pass
    return again, failed


def drain() -> int:
    """Trace everything that is queued, in this process. Returns how many it traced."""
    done = 0
    while work_one():
        done += 1
    return done


def start_pool(n: int):
    """Start `n` worker processes behind this process's queue (the server does this at
    start-up; the bench and the tests call it themselves)."""
    global _POOL
    from ..workers import WorkerPool
    _POOL = WorkerPool(n).start()
    return _POOL


def stop_pool() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.stop()
        _POOL = None


@app.on_event("startup")
def _start_workers() -> None:
    """Pick up what a previous run left queued or half-traced, then start the workers
    (or, with none configured, trace the leftovers here)."""
    try:
        recover()
        if pool_size():
            start_pool(pool_size())
        elif _queue().queued_ids():
            threading.Thread(target=drain, daemon=True).start()
    except Exception:  # noqa: BLE001 - a store that is not there yet must not stop the server
        pass


@app.on_event("shutdown")
def _stop_workers() -> None:
    stop_pool()


@app.post("/api/cases", response_model=S.CaseSummary, status_code=202)
def create_case(body: S.CaseCreate, request: Request, response: Response,
                background: BackgroundTasks,
                refresh: bool = Query(False, description="Trace again even if this wallet "
                                                         "already has a finished case")):
    for c in _demo_cases():          # the mock demo wallets are not on any chain
        if c["address"] == body.address.strip():
            _source(response, "mock")
            _note(request, target=c["id"], address=c["address"], chain=c["chain"])
            return c
    chain, address = _resolve(body)
    _note(request, target=case_id_for(chain, address), address=address, chain=chain)
    _source(response, "live")
    summary = _start_case(chain, address, body, background, refresh)
    _note(request, target=summary["id"], address=address, chain=chain)
    return summary


def _start_case(chain: str, address: str, body: S.CaseCreate, background: BackgroundTasks,
                refresh: bool = False, labels: LabelStore | None = None) -> dict:
    """Open (or find) the case of a wallet and queue its trace. The officer's POST and
    the SAHYOG intake both come through here, so a case is the same however it began."""
    if not Path(LABEL_DB).exists():
        raise HTTPException(503, "The label database is missing. Run `make labels` first.")
    store, queue = _cases(), _queue()
    existing = store.find(chain, address)
    cid = existing["id"] if existing else case_id_for(chain, address)
    waiting = existing is not None and queue.active(cid)     # queued, or a worker has it
    with _ACTIVE_LOCK:
        tracing = cid in _ACTIVE or waiting
        finished = existing is not None and existing["status"] == "done"
        if existing and (tracing or (finished and not refresh)):
            return {k: existing.get(k) for k in SUMMARY_KEYS}
        _ACTIVE.add(cid)
    # a re-run keeps the details the officer entered unless new ones are given
    old = existing or {}
    # screened against the threat tags now, before the trace: a direct hit shows at once
    if labels is not None:              # a batch keeps one open for all its rows
        screening = screen(labels.lookup(address, chain))
    else:
        with LabelStore(LABEL_DB) as own:
            screening = screen(own.lookup(address, chain))
    summary = S.CaseSummary(
        screening=screening,
        threats=[screening["tag"]["threat"]] if screening["tag"] else [],
        id=cid, address=address, chain=chain, status="queued",
        case_ref=body.case_ref or old.get("case_ref"),
        complaint_no=body.complaint_no or old.get("complaint_no"),
        amount_lost_inr=body.amount_lost_inr if body.amount_lost_inr is not None
        else old.get("amount_lost_inr"),
        created_at=datetime.now(timezone.utc)).model_dump(mode="json")
    try:
        if finished:    # keep the finished result on screen (and on disk) while it re-runs
            previous = {**existing, **{k: summary[k] for k in ("case_ref", "complaint_no",
                                                               "amount_lost_inr")}, "error": None}
            store.save({**previous, "status": "queued", "created_at": summary["created_at"]})
        else:
            previous = None
            store.save(skeleton(summary))
        incident = None
        if body.incident_date is not None:
            incident = datetime(body.incident_date.year, body.incident_date.month,
                                body.incident_date.day, tzinfo=timezone.utc)
        # the default budget is left out, so a job says only what the officer changed
        params = {"max_hops": body.max_hops,
                  "since": incident.isoformat() if incident else None,
                  "previous_created_at": existing["created_at"] if finished else None}
        if body.max_wallets != DEFAULT_WALLETS:
            params["max_wallets"] = body.max_wallets
        if body.max_seconds is not None:
            params["max_seconds"] = body.max_seconds
        queue.enqueue(cid, params)
    except Exception:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(cid)
        raise
    if pool_size():             # the pool claims it and hands it to a worker process
        with _ACTIVE_LOCK:
            _ACTIVE.discard(cid)
        if _POOL is not None:
            _POOL.wake()
    else:
        background.add_task(work_one, cid)
    return summary


@app.get("/api/cases", response_model=S.CaseList)
def list_cases(response: Response, outcome: S.Outcome | None = None,
               status: S.CaseStatus | None = None,
               threat: S.Threat | Literal["any"] | None = Query(None, description=(
                   "Only cases that touch this threat; `any` = every case that touches one"))):
    def touches(c: dict) -> bool:
        found = c.get("threats") or []
        return threat is None or (bool(found) if threat == "any" else threat in found)

    store = _cases()
    refs = _complaints().refs_by_case()
    live = [{**c, **(R.summary(store.get(c["id"])) if c["status"] == "done" else {}),
             "sahyog_complaint_ref": refs.get(c["id"])}
            for c in store.list(outcome=outcome, status=status) if touches(c)]
    mock = [c for c in _demo_cases()
            if (outcome is None or c.get("outcome") == outcome)
            and (status is None or c["status"] == status) and touches(c)]
    _source(response, "live" if not demo_mode() else "mixed" if live else "mock")
    return {"total": len(live) + len(mock), "items": live + mock}


# ------------------------------------------------------------------ batch intake (G5)
SCALE_METRICS = ROOT / "artifacts" / "scale" / "metrics.json"    # `make bench-scale`
# What a finished case adds to a batch's result table, kept per (case, the time it was
# traced): a batch is polled while it runs, and a finished case does not change.
_ROW_RESULTS: dict[tuple[str, str], dict] = {}


def _batches():
    from ..store.batches import BatchStore
    return BatchStore(CASE_DB)


def _batch_view(head: dict, rows: list[dict]) -> dict:
    """A stored batch with what its cases say now (`S.BatchDetail`)."""
    from .. import batch as B
    store = _cases()
    heads = store.heads([r["case_id"] for r in rows if r.get("case_id")])
    key = {cid: (cid, h["created_at"]) for cid, h in heads.items() if h["status"] == "done"}
    need = [cid for cid, k in key.items() if k not in _ROW_RESULTS]
    if need:
        if len(_ROW_RESULTS) > 50_000:
            _ROW_RESULTS.clear()
        for cid, case in store.get_many(need).items():
            _ROW_RESULTS[key[cid]] = B.case_result(case, R.summary(case))
    table = [B.result_row(r, heads.get(r.get("case_id")),
                          _ROW_RESULTS.get(key.get(r.get("case_id")))) for r in rows]
    return {**head, "progress": B.progress(table), "workers": pool_size(),
            "results_csv": f"/api/batches/{head['id']}/results.csv", "rows": table}


def _batch_or_404(batch_id: str) -> dict:
    found = _batches().get(batch_id) if _SAFE.match(batch_id) else None
    if found is None:
        raise HTTPException(404, f"No batch has the id {batch_id[:64]}. Open the batch list "
                                 "to find it.")
    return _batch_view(*found)


@app.post("/api/cases/batch", response_model=S.BatchDetail, status_code=202)
def create_batch(body: S.BatchCreate, request: Request, response: Response,
                 background: BackgroundTasks):
    """Many wallets at once. Every row is checked on its own: a row that cannot be
    traced is reported with its reason and the others are queued. A wallet that already
    has a finished case is linked to it, not traced again."""
    import secrets

    from pydantic import ValidationError

    from .. import batch as B
    if (body.rows is None) == (body.csv is None):
        raise HTTPException(422, "Send the wallets as `rows` or as the text of a CSV file "
                                 "in `csv`, not both and not neither.")
    try:
        given = B.parse_csv(body.csv) if body.csv is not None else [
            {"row": i, "address": w.address.strip(), "chain": w.chain, "case_ref": w.case_ref}
            for i, w in enumerate(body.rows, 1)]
        B.check_size(given)
    except B.BatchError as e:
        raise HTTPException(422, str(e)) from None
    if not Path(LABEL_DB).exists():
        raise HTTPException(503, LABELS_MISSING)
    _source(response, "live")
    seen: dict[tuple[str, str], tuple[int, str]] = {}
    rows = []
    # One connection to the case store and one to the labels stay open for the whole
    # upload: opening the store for every row was most of what a row cost (measured).
    from ..store.connect import connect
    with connect(_queue().path), LabelStore(LABEL_DB) as labels:
        for g in given:
            row = {"row": g["row"], "address": g["address"][:128], "chain": g["chain"],
                   "case_ref": (g["case_ref"] or "")[:120] or None}
            rows.append(row)
            if not g["address"]:
                row["error"] = "This row has no address."
                continue
            try:
                spec = S.CaseCreate(address=g["address"],
                                    chain=(g["chain"] or "").strip().lower() or None,
                                    case_ref=row["case_ref"], max_hops=body.max_hops,
                                    max_wallets=body.max_wallets, max_seconds=body.max_seconds)
                chain, address = _resolve(spec)
            except ValidationError:
                row["error"] = (f"{str(g['chain'])[:32]} is not a chain this tool traces. "
                                f"Supported chains: {', '.join(TRACEABLE)}.")
                continue
            except HTTPException as e:
                row["error"] = e.detail
                continue
            row.update(address=address, chain=chain)
            if (chain, address) in seen:
                row["duplicate_of"], row["case_id"] = seen[(chain, address)]
                continue
            try:
                summary = _start_case(chain, address, spec, background, labels=labels)
            except HTTPException as e:
                row["error"] = e.detail
                continue
            row["case_id"] = summary["id"]
            seen[(chain, address)] = (g["row"], summary["id"])
    head = {"id": "b-" + secrets.token_hex(5), "name": (body.name or "").strip() or None,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "created_by": _by(request), "max_hops": body.max_hops,
            "max_wallets": body.max_wallets, "max_seconds": body.max_seconds}
    _batches().save(head, rows)
    _note(request, target=head["id"], rows=len(rows), accepted=len(seen))
    return _batch_view(head, rows)


@app.get("/api/batches", response_model=S.BatchList)
def list_batches(response: Response):
    _source(response, "live")
    store = _batches()
    items = []
    for head in store.list():
        view = _batch_view(*store.get(head["id"]))
        items.append({k: v for k, v in view.items() if k != "rows"})
    return {"total": len(items), "items": items}


@app.get("/api/batches/{batch_id}/results.csv", response_class=Response,
         responses={200: {"content": {"text/csv": {}}, "description": "The result table"}})
def get_batch_csv(batch_id: str, request: Request):
    """The result table as a CSV file: one line per uploaded row, in upload order."""
    from .. import batch as B
    view = _batch_or_404(batch_id)
    text = B.to_csv(view["rows"], base_url=str(request.base_url).rstrip("/"))
    return Response(text, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="batch-{view["id"]}.csv"'})


@app.get("/api/batches/{batch_id}", response_model=S.BatchDetail)
def get_batch(batch_id: str, response: Response):
    _source(response, "live")
    return _batch_or_404(batch_id)


@app.get("/api/scale", response_model=S.ScaleMetrics)
def get_scale(response: Response):
    """Measured throughput, read from the file `make bench-scale` writes. Not measured
    on this installation = it says so; no figure is made up."""
    _source(response, "live")
    if not Path(SCALE_METRICS).exists():
        return {"status": "not_measured",
                "notes": ["Throughput has not been measured on this installation. "
                          "`make bench-scale` measures it."]}
    return {"status": "measured", **json.loads(Path(SCALE_METRICS).read_text())}


# ------------------------------------------------------------------ case file, receipt, verify (B9)
MOCK_WATERMARK = "Demo fixture - not evidence"


def make_verify_fetcher() -> chains.Fetcher:
    """Cache only, whatever OFFLINE says: a verification must read the responses the
    case was computed from, not the chain as it is now."""
    return chains.cache_only_fetcher()


def _case_or_mock(case_id: str) -> tuple[dict, bool]:
    """(case, is it a mock fixture)."""
    live = _cases().get(case_id)
    if live is not None:
        return live, False
    fixture = demo_fixture(f"cases/{case_id}", _no_case(case_id))
    return S.CaseDetail.model_validate(fixture).model_dump(mode="json"), True


def _case_pdf(case_id: str) -> Response:
    from ..explain.case_file import NotReady
    from ..explain.case_pdf import case_pdf
    case, mock = _case_or_mock(case_id)
    try:
        pdf = case_pdf(case, watermark=MOCK_WATERMARK if mock else None)
    except NotReady as e:
        raise HTTPException(409, str(e)) from None
    name = f"case-{case_id}" + ("-demo" if mock else "")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"',
                             "X-Data-Source": "mock" if mock else "live"})


_CASE_PDF = {200: {"content": {"application/pdf": {}}, "description": "The case file, A4"}}


# declared before /api/cases/{case_id}, which would otherwise take "x.pdf" as an id
@app.get("/api/cases/{case_id}.pdf", include_in_schema=False)
def get_case_pdf_file(case_id: str):
    return _case_pdf(case_id)


@app.get("/api/cases/{case_id}", response_model=S.CaseDetail)
def get_case(case_id: str, response: Response):
    live = _cases().get(case_id)
    if live is not None:
        _source(response, "live")
        if live["status"] in ("queued", "running"):
            with _ACTIVE_LOCK:
                snapshot = _PROGRESS.get(case_id)
            if snapshot is not None:
                live["progress"] = {**snapshot,
                                    "message": progress_sentence(live["chain"], snapshot)}
        return _enrich(live)
    fixture = demo_fixture(f"cases/{case_id}", _no_case(case_id))
    _source(response, "mock")
    return fixture


@app.get("/api/cases/{case_id}/pdf", response_class=Response, responses=_CASE_PDF)
def get_case_pdf(case_id: str):
    """The case file as an A4 PDF: result, summary, where the funds went, flow diagram,
    exchanges reached with their evidence and transaction hashes, flags, how the
    confidence was worked out, limitations, and the provenance receipt. The same case
    always gives the same bytes. 409 until the case has a result. Also served at
    /api/cases/{id}.pdf."""
    return _case_pdf(case_id)


@app.get("/api/cases/{case_id}/receipt", response_model=S.Receipt)
def get_case_receipt(case_id: str, response: Response):
    """What the case was computed from, as SHA-256 digests: input, chain responses,
    label database, model, code, and the findings fingerprint."""
    from ..provenance import receipt
    live = _cases().get(case_id)
    if live is None:
        fixture = demo_fixture(f"cases/{case_id}/receipt", _no_case(case_id))
        _source(response, "mock")
        return fixture
    doc = receipt(live)
    if doc is None:
        raise HTTPException(409, "This case carries no receipt: it has not finished, or it "
                                 "was stored before receipts existed. Trace it again.")
    _source(response, "live")
    return doc


@app.post("/api/cases/{case_id}/verify", response_model=S.VerifyResult)
def verify_case(case_id: str, response: Response):
    """Trace the wallet again from the cached chain responses only (never the network)
    and compare the findings fingerprint with the receipt's."""
    from ..cases import verify_stored
    live = _cases().get(case_id)
    if live is None:
        demo_fixture(f"cases/{case_id}", _no_case(case_id))      # 404 for an unknown id
        raise HTTPException(422, "A demo fixture has no trace to verify.")
    if not Path(LABEL_DB).exists():
        raise HTTPException(503, "The label database is missing. Run `make labels` first.")
    _source(response, "live")
    with LabelStore(LABEL_DB) as labels:
        return verify_stored(live, make_verify_fetcher(), labels,
                             label_db_sha256=label_db_sha256())


# A case's trace run again, kept for the next question about the same case (opening one
# wallet after another): content digest -> trace. A handful of cases at most.
_CONTEXT_TRACES: dict[str, object] = {}
_CONTEXT_KEPT = 8


@app.get("/api/cases/{case_id}/context", response_model=S.CaseContext)
def get_case_context(case_id: str, request: Request, response: Response,
                     wallet: str | None = Query(None, max_length=200, description=(
                         "One wallet's other transfers (an id from `graph.nodes`, or of a "
                         "wallet already shown as context). Without it: the whole context")),
                     limit: int = Query(3000, ge=1, le=3000)):
    """The transfers this case's trace read and did not follow, to draw greyed as
    context. Worked out by tracing the wallet again from the cached chain responses
    only; the case is not changed. A wallet the trace did not read is fetched now when
    the server is online; offline the answer says it was not recorded (`recorded`
    false). 409 until the case has a result, or when its responses are no longer in
    the cache; 404 for a wallet that is not part of the case."""
    from ..cases import replay_trace
    from ..chains.base import CacheMiss
    from ..context import case_context
    live = _cases().get(case_id)
    if live is None:
        fixture = demo_fixture(f"cases/{case_id}/context", _no_case(case_id))
        _source(response, "mock")
        return fixture
    case_in = (live.get("provenance") or {}).get("input")
    if live["status"] != "done" or not case_in:
        raise HTTPException(409, "This case has no trace to read context from: it has not "
                                 "finished, or it was stored before receipts existed.")
    if not Path(LABEL_DB).exists():
        raise HTTPException(503, "The label database is missing. Run `make labels` first.")
    _source(response, "live")
    if wallet:
        _note(request, wallet=wallet)
    key = live["provenance"].get("content_sha256") or case_id
    with LabelStore(LABEL_DB) as labels:
        try:
            tr = _CONTEXT_TRACES.get(key)
            if tr is None:
                tr = replay_trace(case_in, make_verify_fetcher(), labels)
                while len(_CONTEXT_TRACES) >= _CONTEXT_KEPT:
                    _CONTEXT_TRACES.pop(next(iter(_CONTEXT_TRACES)))
                _CONTEXT_TRACES[key] = tr
            return case_context(live, None, labels, wallet=wallet, fetcher=make_fetcher(),
                                limit=limit, tr=tr)
        except CacheMiss:
            raise HTTPException(409, "The chain responses this case was traced from are no "
                                     "longer in the cache, so its context cannot be read. "
                                     "Trace the wallet again.") from None
        except KeyError:
            raise HTTPException(404, "That wallet is not part of this case.") from None


# ------------------------------------------------------------------ wallets + labels
@app.get("/api/wallets/{chain}/{address}", response_model=S.WalletDetail)
def get_wallet(chain: S.TraceChain, address: str, response: Response):
    """Everything on record about one address: its label, the cases it appears in, the
    transfers those cases read of it, and what is on record against it (wallets.py)."""
    from ..store.watch import watch_id
    from ..wallets import wallet_view
    if chain in chains.EVM_FAMILY or address.lower().startswith("bc1"):
        address = address.lower()
    try:
        wallet = demo_fixture(f"wallets/{chain}/{address}", "")
        kind = "mock"
    except HTTPException:
        wallet = {"address": address, "chain": chain, "labels": [],
                  "risk": R.wallet_risk(address, None, []), "cases": []}
        kind = "live"
    store = _labels()
    if store:
        with store:
            hit = store.lookup(address, chain)
        wallet["labels"] = [hit.as_dict()] if hit else []
        kind = "mixed" if kind == "mock" else kind
    cases = _cases()
    refs = cases.wallet_cases(address, chain)
    if kind == "live" or refs:      # a demo wallet's mock figures stand until a real case reads it
        details = [d for d in (cases.get(r["case_id"]) for r in refs)
                   if d and d.get("status") == "done"]
        wallet.update(wallet_view(address, chain, details,
                                  wallet["labels"][0] if wallet["labels"] else None))
    seen = {c["case_id"] for c in wallet["cases"]}
    wallet["cases"] = wallet["cases"] + [c for c in refs if c["case_id"] not in seen]
    wallet["watched"] = _watch().get(watch_id(chain, address)) is not None
    _source(response, kind)
    return wallet


def _coverage(store: LabelStore) -> dict:
    """The label counts, with the figure a headline may show: labels on the chains a
    trace can run on. The store also holds labels on chains the tool cannot trace."""
    with store:
        st = store.stats()
    out = {k: st[k] for k in ("total", "by_category", "by_tier", "by_chain", "by_source",
                              "by_threat")}
    out["traceable_chains"] = list(TRACEABLE)
    out["traceable_total"] = sum(n for c, n in st["by_chain"].items() if c in TRACEABLE)
    return out


@app.get("/api/labels/coverage", response_model=S.LabelCoverage)
def label_coverage(response: Response):
    """How many labels the store holds, by chain, category, tier and source (with the
    licence on record for each source)."""
    store = _labels()
    if store is None:
        if not demo_mode():
            raise HTTPException(503, LABELS_MISSING)
        _source(response, "mock")
        return load_mock("labels/coverage")
    _source(response, "live")
    return _coverage(store)


@app.get("/api/labels/search", response_model=S.LabelSearch)
def search_labels(response: Response, q: str = "", chain: str | None = None,
                  category: S.Category | None = None, tier: S.Tier | None = None,
                  threat: S.Threat | Literal["any"] | None = Query(None, description=(
                      "Only labels with this threat tag; `any` = every tagged label")),
                  limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    store = _labels()
    if store is None:
        if not demo_mode():
            raise HTTPException(503, LABELS_MISSING)
        _source(response, "mock")
        return load_mock("labels/search")
    with store:
        total, items = store.search(q, chain=chain, category=category, tier=tier,
                                    limit=limit, offset=offset, threat=threat)
    _source(response, "live")
    return {"query": q, "total": total, "limit": limit, "offset": offset,
            "items": [i.as_dict() for i in items]}


# ------------------------------------------------------------------ desk + requests (B8)
def make_gateway():
    """Where an approved request goes. Only the mock exists: it writes to an outbox
    folder and sends nothing (docs/sahyog_contract.md)."""
    from ..desk.gateway import MockSahyogGateway
    return MockSahyogGateway(OUTBOX)


def _desk():
    from ..desk.directory import Directory
    from ..desk.service import DeskService
    from ..store.requests import RequestStore
    return DeskService(_cases(), RequestStore(DESK_DB), Directory.load(DIRECTORY),
                       make_gateway())


def _refused(e) -> HTTPException:
    return HTTPException(e.status, str(e))


@app.get("/api/desk", response_model=S.Desk)
def get_desk(response: Response):
    desk = _desk().desk()
    if not desk["rows"] and demo_mode():     # no finished case names an exchange yet
        _source(response, "mock")
        return load_mock("desk")
    _source(response, "live")
    return desk


@app.get("/api/vasps/{name}", response_model=S.VaspDetail)
def get_vasp(name: str, response: Response):
    if not _SAFE.match(name):
        raise HTTPException(404, "not found")
    svc = _desk()
    vasp = svc.directory.canonical(name)
    store = _labels()
    counts: dict[str, int] = {}
    if store:
        with store:
            counts = store.entity_counts(vasp)
    page = svc.vasp(vasp, counts)
    if not (page["wallets"] or page["requests"]):
        try:                             # a demo exchange keeps its demo page
            mock = demo_fixture(f"vasps/{name}", f'Nothing is on file for "{name[:80]}": no label, '
                                                 "no directory entry and no case names it.")
            _source(response, "mock")
            return mock
        except HTTPException:
            if not (counts or vasp in svc.directory.names()):
                raise
    _source(response, "live")
    return page


def _demo_request_for(vasp: str) -> dict:
    for path in sorted((MOCKS / "requests").glob("*.json")):
        req = load_mock(f"requests/{path.stem}")
        if req["vasp"] == vasp:
            return req
    raise HTTPException(404, f"No demo request for {vasp}.")


@app.post("/api/requests", response_model=S.RequestDetail, status_code=201)
def create_request(body: S.RequestCreate, request: Request, response: Response):
    from ..desk.service import DeskError
    demo = {c["id"]: c for c in _demo_cases()}
    if demo and all(c in demo for c in body.case_ids):   # the fixture cases have no trace
        _source(response, "mock")
        for cid in body.case_ids:                 # ...but they too must name the exchange
            if demo[cid].get("top_vasp") != body.vasp:
                raise HTTPException(422, f"Demo case {cid} does not support a request to "
                                         f"{body.vasp}: it does not name that exchange.")
        mock = _demo_request_for(body.vasp)
        _note(request, target=mock["id"], vasp=mock["vasp"], cases=mock["case_ids"])
        return mock
    _source(response, "live")
    _note(request, vasp=body.vasp[:100], cases=body.case_ids[:50])
    try:
        made = _desk().create(body.vasp, body.case_ids, list(body.asks), body.officer,
                              body.wallets, by=_by(request))
    except DeskError as e:
        raise _refused(e) from None
    _note(request, target=made["id"], vasp=made["vasp"], cases=made["case_ids"])
    return made


@app.get("/api/requests", response_model=S.RequestList)
def list_requests(response: Response, vasp: str | None = None,
                  status: S.RequestStatus | None = None):
    """The requests register: every request, newest first, withdrawn ones included.
    The demo request is listed only while the desk itself is the mock."""
    svc = _desk()
    live = svc.list()
    if demo_mode() and not live and not svc.desk()["rows"]:
        _source(response, "mock")
        items = load_mock("requests")["items"]
    else:
        _source(response, "live")
        items = live
    if vasp:
        name = svc.directory.canonical(vasp)
        items = [q for q in items if q["vasp"] == name]
    if status:
        items = [q for q in items if q["status"] == status]
    return {"items": items}


def _request_pdf(request_id: str) -> Response:
    from ..desk.pdf import letter_pdf
    from ..desk.service import DeskError
    try:
        svc = _desk()
        req = svc.get(request_id)
        if req is not None:
            pdf, kind = svc.pdf(request_id), "live"
            name = request_id + ("-draft" if req["letter"]["watermark"] else "")
        else:
            req = demo_fixture(f"requests/{request_id}", _no_request(request_id))
            req["letter"]["watermark"] = "Demo fixture - not evidence"
            pdf, name, kind = letter_pdf(req), f"{request_id}-demo", "mock"
    except DeskError as e:
        raise _refused(e) from None
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"',
                             "X-Data-Source": kind})


_PDF = {200: {"content": {"application/pdf": {}}, "description": "The request letter, A4"}}


# declared before /api/requests/{request_id}, which would otherwise take "x.pdf" as an id
@app.get("/api/requests/{request_id}.pdf", include_in_schema=False)
def get_request_pdf_file(request_id: str):
    return _request_pdf(request_id)


@app.get("/api/requests/{request_id}", response_model=S.RequestDetail)
def get_request(request_id: str, response: Response):
    live = _desk().get(request_id)
    if live is not None:
        _source(response, "live")
        return live
    fixture = demo_fixture(f"requests/{request_id}", _no_request(request_id))
    _source(response, "mock")
    return fixture


@app.patch("/api/requests/{request_id}", response_model=S.RequestDetail)
def patch_request(request_id: str, body: S.RequestPatch, request: Request,
                  response: Response):
    """Move a request along: drafted -> approved -> sent -> acknowledged -> answered |
    freeze_confirmed | refused. 409 for a step that is not allowed from where it is.
    Sending hands the payload and the letter to the gateway (a local outbox)."""
    from ..desk.service import DeskError
    svc = _desk()
    _note(request, status=body.status)
    if svc.get(request_id) is not None:
        _source(response, "live")
        try:
            return svc.patch(request_id, body.status, body.note, by=_by(request))
        except DeskError as e:
            raise _refused(e) from None
    # a mock demo request: the new status is applied to the reply, nothing persists
    from ..desk.service import TRANSITIONS
    req = demo_fixture(f"requests/{request_id}", _no_request(request_id))
    _source(response, "mock")
    if body.status not in TRANSITIONS[req["status"]]:
        raise HTTPException(409, f"A request that is {req['status']} cannot become "
                                 f"{body.status}.")
    req["status"] = body.status
    req["allowed_next"] = list(TRANSITIONS[body.status])
    req["status_history"].append({"status": body.status, "note": body.note,
                                  "at": datetime.now(timezone.utc).isoformat()})
    if body.status != "drafted":
        req["letter"]["watermark"] = None
    return req


@app.get("/api/requests/{request_id}/pdf", response_class=Response, responses=_PDF)
def get_request_pdf(request_id: str):
    """The letter as an A4 PDF. A draft carries the watermark; the same request always
    gives the same bytes. Also served at /api/requests/{id}.pdf."""
    return _request_pdf(request_id)


# ------------------------------------------------------------------ dashboard + model
@app.get("/api/dashboard", response_model=S.Dashboard)
def get_dashboard(response: Response):
    """Counted from the stored cases, the desk and the watchlist (dashboard.py). With no
    stored case it answers the demo fixture, as the desk does."""
    from ..dashboard import build_dashboard
    from ..watch import alerts_of
    cases = _cases()
    details = [d for d in (cases.get(c["id"]) for c in cases.list()) if d]
    store = _labels()
    if details or not demo_mode():
        svc = _desk()
        watched = _watch_items()
        dash = build_dashboard(details, svc.desk(), svc.list(),
                               [a for w in watched for a in alerts_of(w)], len(watched))
        dash["label_coverage"] = (load_mock("dashboard")["label_coverage"] if demo_mode()
                                  else {"total": 0, "by_category": {}, "by_tier": {},
                                        "by_chain": {}, "by_source": [], "traceable_total": 0,
                                        "traceable_chains": list(TRACEABLE)})
        _source(response, "live" if store or not demo_mode() else "mixed")
    else:
        dash = load_mock("dashboard")
        _source(response, "mixed" if store else "mock")
    if store:
        dash["label_coverage"] = _coverage(store)
    return dash


# ------------------------------------------------------------------ watchlist (U4)
_SAFE_WATCH = re.compile(r"^[a-z]+-[A-Za-z0-9]{20,128}$")


def _watch():
    from ..store.watch import WatchStore
    return WatchStore(WATCH_DB)


def _finished(case: dict | None) -> bool:
    return case is not None and case.get("status") == "done" and "candidates" in case


def _watch_item(entry: dict, labels: LabelStore | None = None) -> dict:
    """A stored entry with what its wallet's case says now. The first finished trace of
    a wallet added before it had one becomes its baseline: it is not news."""
    from ..watch import snapshot, watch_item
    case = _cases().find(entry["chain"], entry["address"])
    tracing = case is not None and case.get("status") in ("queued", "running") \
        and _tracing(case["id"])
    if entry.get("baseline") is None and _finished(case) and not tracing:
        entry = {**entry, "baseline": snapshot(case)}
        _watch().save(entry)
    hit = labels.lookup(entry["address"], entry["chain"]) if labels else None
    return watch_item(entry, case, tracing, hit.as_dict() if hit else None)


def _watch_items(entries: list[dict] | None = None) -> list[dict]:
    entries = _watch().list() if entries is None else entries
    store = _labels() if entries else None
    if store is None:
        return [_watch_item(e) for e in entries]
    with store:
        return [_watch_item(e, store) for e in entries]


def _watched(watch_id: str) -> dict:
    entry = _watch().get(watch_id) if _SAFE_WATCH.match(watch_id) else None
    if entry is None:
        raise HTTPException(404, "This wallet is not on the watchlist.")
    return entry


@app.get("/api/watchlist", response_model=S.WatchList)
def get_watchlist(response: Response):
    """Watched wallets, newest first, each compared with its baseline (watch.py)."""
    _source(response, "live")
    return {"items": _watch_items()}


@app.post("/api/watchlist", response_model=S.WatchItem, status_code=201)
def add_watch(body: S.WatchCreate, request: Request, response: Response):
    from ..store.watch import watch_id
    from ..watch import snapshot
    chain, address = _resolve(S.CaseCreate(address=body.address, chain=body.chain))
    wid = watch_id(chain, address)
    _note(request, target=wid)
    store = _watch()
    if store.get(wid) is not None:
        raise HTTPException(409, "This wallet is already on the watchlist.")
    case = _cases().find(chain, address)
    entry = {"id": wid, "chain": chain, "address": address,
             "note": (body.note or "").strip() or None,
             "added_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
             "added_by": _by(request),
             "baseline": snapshot(case) if _finished(case) else None}
    store.save(entry)
    _source(response, "live")
    return _watch_items([entry])[0]


@app.post("/api/watchlist/{watch_id}/check", response_model=S.WatchItem, status_code=202)
def check_watch(watch_id: str, request: Request, response: Response,
                background: BackgroundTasks):
    """Trace the watched wallet again (as `POST /api/cases?refresh=true` does). Poll the
    watchlist: the item is `checking` until the trace is done, then says what is new."""
    entry = _watched(watch_id)
    case = _cases().find(entry["chain"], entry["address"])
    hops = (((case or {}).get("provenance") or {}).get("input") or {}).get("max_hops") or 3
    create_case(S.CaseCreate(address=entry["address"], chain=entry["chain"], max_hops=hops),
                request, response, background, refresh=True)
    _note(request, target=watch_id)
    return _watch_items([entry])[0]


@app.post("/api/watchlist/{watch_id}/seen", response_model=S.WatchItem)
def seen_watch(watch_id: str, response: Response):
    """The officer has read the changes: the wallet's trace as it is now is the baseline."""
    from ..watch import snapshot
    entry = _watched(watch_id)
    case = _cases().find(entry["chain"], entry["address"])
    if not _finished(case):
        raise HTTPException(409, "This wallet has no finished trace to mark as seen.")
    entry = {**entry, "baseline": snapshot(case)}
    _watch().save(entry)
    _source(response, "live")
    return _watch_items([entry])[0]


@app.delete("/api/watchlist/{watch_id}", response_model=S.Ok)
def remove_watch(watch_id: str):
    _watched(watch_id)
    _watch().remove(watch_id)
    return {"ok": True}


@app.get("/api/model", response_model=S.ModelInfo)
def get_model(response: Response, chain: str = "tron"):
    """The deposit-address model's measurements (`make model`). Tron is the model whose
    scores the labels carry; `?chain=ethereum` is the explorer-tagged benchmark."""
    from ..classify.report import model_info, read_metrics
    if not _SAFE.match(chain):
        raise HTTPException(404, "not found")
    metrics = read_metrics(MODEL_DIR, chain)
    if metrics is None and demo_mode():
        _source(response, "mock")
        return load_mock("model")
    if metrics is None:
        _source(response, "live")
        return {"status": "not_measured", "metrics": {}, "chain": chain,
                "notes": [f"No model has been measured for {chain} on this machine."]}
    _source(response, "live")
    from ..eval.abstain import abstain_info, read_validation
    validation = read_validation(ABSTAIN_DIR, chain)
    return {**model_info(metrics),
            "abstain": abstain_info(validation) if validation else None}


# ------------------------------------------------------------------ problem-statement coverage (G2)
@app.get("/api/coverage", response_model=S.PsCoverage)
def get_coverage(response: Response):
    """Every line of the problem statement with what the tool does about it
    (data/ps_coverage.yaml). The chain rows are worked out from the chains that trace."""
    from ..coverage import build
    _source(response, "live")
    return build(TRACEABLE)


# ------------------------------------------------------------------ SAHYOG, both directions (G2)
# SAHYOG's interface is not public. These routes are our side of a contract
# (docs/sahyog_contract.md) and are exercised by the simulator screen. They carry their
# own API key (X-SAHYOG-Key) instead of an officer's login.
def _complaints():
    from ..store.complaints import ComplaintStore
    return ComplaintStore(DESK_DB)


def _enrich(case: dict) -> dict:
    """What a served case carries that a stored one does not: its risk (risk.py reads the
    stored flags, labels and slices) and the complaint that reported it, if one did."""
    risk = R.case_risk(case)
    case["risk"] = risk
    case["risk_class"] = risk["risk_class"] if risk else None
    case["risk_score"] = risk["score"] if risk else None
    case["sahyog_complaint_ref"] = _complaints().refs_by_case().get(case["id"])
    return case


def _sahyog_key(request: Request) -> None:
    from ..desk.intake import KEY_HEADER, IntakeError, check_key
    try:
        check_key(request.headers.get(KEY_HEADER), SAHYOG_KEY)
    except IntakeError as e:
        raise HTTPException(e.status, str(e)) from None


def _complaint_view(complaint: dict) -> dict:
    from ..desk.intake import complaint_view, wallet_view
    from ..store.requests import RequestStore
    cases, requests = _cases(), RequestStore(DESK_DB).list()
    wallets = []
    for entry in complaint["wallets"]:
        case = cases.get(entry["case_id"]) if entry.get("case_id") else None
        wallets.append(wallet_view(entry, case, requests, R.summary(case)))
    return complaint_view(complaint, wallets)


def _notify_sahyog(case_id: str) -> None:
    """A trace has finished: hand its result to the gateway for every complaint that
    reported the wallet. A failure here is recorded nowhere but must not fail the case;
    the portal can always read the result from the status route."""
    from ..cases import CODE_VERSION
    from ..desk.intake import iso, result_payload
    try:
        store = _complaints()
        for complaint in store.list():
            mine = [w for w in complaint["wallets"]
                    if w.get("case_id") == case_id and not w.get("result_sent_at")]
            if not mine:
                continue
            view = {w["case_id"]: w for w in _complaint_view(complaint)["wallets"]
                    if w.get("case_id")}
            if view[case_id]["status"] != "result":
                continue
            now = datetime.now(timezone.utc)
            receipt = make_gateway().notify_result(
                result_payload(complaint, view[case_id], code_version=CODE_VERSION, now=now),
                now=now)
            for w in mine:
                w["result_sent_at"], w["result_receipt"] = iso(now), receipt
            store.save(complaint)
    except Exception:  # noqa: BLE001
        pass


def _file_complaint(body: S.ComplaintCreate, background: BackgroundTasks) -> dict:
    """Validate every address, open one case per wallet and queue its trace. Idempotent
    on complaint_ref + address. A bad address is refused by name; the others go through."""
    from ..desk.intake import MAX_HOPS, iso
    store = _complaints()
    now = datetime.now(timezone.utc)
    complaint = store.get(body.complaint_ref) or {
        "complaint_ref": body.complaint_ref, "agency": body.agency.strip(),
        "officer": body.officer.strip(), "category": body.category,
        "note": (body.note or "").strip() or None, "amount_lost_inr": body.amount_lost_inr,
        "incident_date": body.incident_date.isoformat() if body.incident_date else None,
        "callback_url": body.callback_url, "received_at": iso(now), "wallets": []}
    known = {(w.get("chain"), w["address"]) for w in complaint["wallets"] if w["accepted"]}
    refused = {w["address"] for w in complaint["wallets"] if not w["accepted"]}
    for w in body.wallets:
        given = w.address.strip()
        spec = S.CaseCreate(address=given, chain=w.chain, complaint_no=body.complaint_ref,
                            amount_lost_inr=body.amount_lost_inr,
                            incident_date=body.incident_date, max_hops=MAX_HOPS)
        try:
            chain, address = _resolve(spec)
        except HTTPException as e:
            if given not in refused:
                refused.add(given)
                why = e.detail if given[:64] in e.detail else f"{given[:64]}: {e.detail}"
                complaint["wallets"].append({"address": given, "chain": w.chain,
                                             "accepted": False, "error": why})
            continue
        if (chain, address) in known:
            continue
        known.add((chain, address))
        summary = _start_case(chain, address, spec, background)
        complaint["wallets"].append({"address": address, "chain": chain, "accepted": True,
                                     "case_id": summary["id"], "result_sent_at": None})
    if not known:
        raise HTTPException(422, "No wallet in this complaint could be accepted. "
                            + " ".join(w["error"] for w in complaint["wallets"]))
    store.save(complaint)
    for w in complaint["wallets"]:      # a wallet that already had a finished case
        if w["accepted"] and not w.get("result_sent_at"):
            _notify_sahyog(w["case_id"])
    return _complaint_view(store.get(body.complaint_ref))


def _record_reply(request_id: str, body: S.ReplyIn) -> dict:
    from ..desk.service import DeskError
    try:
        req, receipt = _desk().reply(request_id, body.status, body.note, body.reply_ref)
    except DeskError as e:
        raise _refused(e) from None
    return {"request_id": req["id"], "status": req["status"],
            "recorded_at": req["status_history"][-1]["at"],
            "location": receipt["location"] if receipt else None}


@app.post("/api/sahyog/complaints", response_model=S.ComplaintStatus, status_code=202)
def sahyog_complaint(body: S.ComplaintCreate, request: Request, response: Response,
                     background: BackgroundTasks):
    """SAHYOG -> VASP-FUSION. A complaint with its wallets: one case is opened per wallet
    and its trace starts at once. 202 with the case ids; poll the status route. Sending
    the same complaint again returns the same cases. 401 without the API key, 503 when
    no key is configured, 422 when no wallet can be accepted."""
    _sahyog_key(request)
    _note(request, target=body.complaint_ref, wallets=len(body.wallets))
    _source(response, "live")
    return _file_complaint(body, background)


@app.get("/api/sahyog/complaints/{complaint_ref}", response_model=S.ComplaintStatus)
def sahyog_status(complaint_ref: str, request: Request, response: Response):
    """The state of each wallet of a complaint and, once traced: the outcome, every
    exchange reached with proximity and confidence apart, the risk class, the case file
    and the requests drafted from it."""
    _sahyog_key(request)
    complaint = _complaints().get(complaint_ref) if re.match(S.COMPLAINT_REF, complaint_ref) \
        else None
    if complaint is None:
        raise HTTPException(404, f"No complaint {complaint_ref[:64]} has been received.")
    _source(response, "live")
    return _complaint_view(complaint)


@app.post("/api/sahyog/requests/{request_id}/replies", response_model=S.ReplyAck)
def sahyog_reply(request_id: str, body: S.ReplyIn, request: Request, response: Response):
    """SAHYOG -> VASP-FUSION. An exchange's reply to a request that was sent: acknowledged,
    answered, freeze_confirmed or refused. The request desk shows it at once. 404 unknown
    request, 409 a reply that cannot follow the request's present status."""
    _sahyog_key(request)
    _note(request, status=body.status)
    _source(response, "live")
    return _record_reply(request_id, body)


# ---- the simulator: the signed-in officer plays the portal's side. The server calls the
# same functions the routes above do, so the browser never holds the API key.
def _sim_enabled() -> bool:
    from ..desk.intake import configured_key
    return configured_key(SAHYOG_KEY) is not None


def _sim_or_503() -> None:
    if not _sim_enabled():
        raise HTTPException(503, "The simulator is off: no SAHYOG API key is configured. "
                                 "The demo set-up (`make demo`) creates one.")


@app.get("/api/sahyog-sim", response_model=S.SahyogSim)
def get_sahyog_sim(response: Response):
    """What the simulator screen shows: complaints filed, and the sent requests as the
    portal would see them. A simulator for demonstration, not the SAHYOG portal."""
    from typing import get_args

    from ..desk.intake import NOTICE, REPLIES
    from ..desk.service import TRANSITIONS
    _source(response, "live")
    out = {"enabled": _sim_enabled(), "notice": NOTICE, "why_disabled": None,
           "categories": list(get_args(S.FraudCategory)), "complaints": [], "requests": []}
    if not out["enabled"]:
        out["why_disabled"] = ("No SAHYOG API key is configured on this installation. The "
                               "demo set-up (`make demo`) creates one.")
        return out
    out["complaints"] = [_complaint_view(c) for c in _complaints().list()]
    for req in _desk().list():
        if not req.get("receipt"):
            continue
        out["requests"].append({
            "id": req["id"], "reference": req["reference"], "vasp": req["vasp"],
            "status": req["status"], "asks": req["letter"]["asks"],
            "wallets": len(req["letter"]["wallets"]),
            "sent_at": req["receipt"]["submitted_at"],
            "allowed_replies": [s for s in TRANSITIONS[req["status"]] if s in REPLIES],
            "last_note": req["status_history"][-1].get("note")})
    return out


@app.post("/api/sahyog-sim/complaints", response_model=S.ComplaintStatus, status_code=202)
def sim_complaint(body: S.ComplaintCreate, request: Request, response: Response,
                  background: BackgroundTasks):
    """The simulator files a complaint: the same intake as POST /api/sahyog/complaints."""
    _sim_or_503()
    _note(request, target=body.complaint_ref, wallets=len(body.wallets))
    _source(response, "live")
    return _file_complaint(body, background)


@app.post("/api/sahyog-sim/requests/{request_id}/reply", response_model=S.ReplyAck)
def sim_reply(request_id: str, body: S.ReplyIn, request: Request, response: Response):
    """The simulator plays the exchange: the same reply leg as
    POST /api/sahyog/requests/{id}/replies."""
    _sim_or_503()
    _note(request, status=body.status)
    _source(response, "live")
    return _record_reply(request_id, body)


# ------------------------------------------------------------------ the interface (B9)
UI_DIST = ROOT / "ui" / "dist"                       # `npm run build` in ui/ writes it
CONSOLE = Path(__file__).with_name("console.html")   # stands in when there is no build


# Declared last: every /api route, /docs and /openapi.json match before it.
@app.get("/{path:path}", include_in_schema=False)
def interface(path: str):
    """The built interface (a single-page app: unknown paths get index.html), or, when
    this checkout or image has no build, a plain console page over the same API."""
    from fastapi.responses import FileResponse
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "not found")
    dist = UI_DIST.resolve()
    if (dist / "index.html").is_file():
        file = (dist / path).resolve()
        if path and file.is_file() and dist in file.parents:
            # Vite names every file under assets/ after its content: it never changes.
            keep = {"Cache-Control": "public, max-age=31536000, immutable"}
            return FileResponse(file, headers=keep if path.startswith("assets/") else None)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
    if path in ("", "index.html"):
        return FileResponse(CONSOLE, media_type="text/html",
                            headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "not found")
