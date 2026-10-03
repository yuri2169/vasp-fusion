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
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
from ..store.audit import AuditLog
from ..store.cases import SUMMARY_KEYS, CaseStore
from ..trace import TraceConfig
from . import schemas as S
from . import security

ROOT = Path(__file__).resolve().parents[2]
MOCKS = ROOT / "mocks"
LABEL_DB = DEFAULT_DB
MODEL_DIR = ROOT / "artifacts" / "model_v1"   # metrics.json per chain (`make model`)
ABSTAIN_DIR = ROOT / "artifacts" / "abstain_v1"   # validation.json per chain (`make abstain-eval`)
CASE_DB: Path | None = None      # None = data/case.duckdb (or VASPFUSION_CASE_DB)
DESK_DB: Path | None = None      # None = data/desk.duckdb (or VASPFUSION_DESK_DB)
OUTBOX: Path | None = None       # None = data/sahyog_outbox (or VASPFUSION_SAHYOG_OUTBOX)
DIRECTORY = ROOT / "data" / "vasp_directory.yaml"   # cited facts only (B8)
OFFICERS: Path | None = None     # None = data/officers.json (or VASPFUSION_OFFICERS)
AUDIT_DB: Path | None = None     # None = data/audit.duckdb (or VASPFUSION_AUDIT_DB)
AUTH_SECRET: Path | None = None  # None = data/auth_secret (or VASPFUSION_JWT_SECRET)
AUTH: str | None = None          # None = VASPFUSION_AUTH, else "auto"; "off" | "required"
VERSION = "0.1.0"
# Chains a trace can run on today. BSC has no free data source; Solana and Avalanche
# have no adapter yet (PROGRESS.md, B2). Bitcoin is traced since B5 (chains/btc.py: an
# address's pro-rata share of each transaction; cluster.py: labels by co-spending).
TRACEABLE = ("tron", "ethereum", "polygon", "arbitrum", "base", "optimism", "bitcoin")

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
    if auth_required() and officer is None and path not in security.OPEN_PATHS:
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
    (r"wallets/[^/]+/[^/]+", S.WalletDetail),
    (r"labels/search", S.LabelSearch),
    (r"desk", S.Desk),
    (r"vasps/[^/]+", S.VaspDetail),
    (r"requests", S.RequestList),
    (r"requests/[^/]+", S.RequestDetail),
    (r"dashboard", S.Dashboard),
    (r"model", S.ModelInfo),
    (r"audit", S.AuditPage),
    (r"auth/me", S.Me),
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
                    data_mode="mixed", auth_required=auth_required(),
                    offline=chains.cache.offline_mode(), git_commit=git_state()[0])


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
    return load_mock("cases")["items"]


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


def _run_case(case_id: str, max_hops: int, incident: datetime | None,
              previous: dict | None = None) -> None:
    """Trace the wallet and store the result. Runs after the POST has answered.
    `previous` is the finished case being refreshed: it is kept if the new run fails."""
    try:
        store = _cases()
        queued = store.get(case_id)
        store.set_status(case_id, "running")
        _note_progress(case_id, dict(_NOTHING_READ))
        fetcher = make_fetcher()
        cfg = TraceConfig(max_hops=max_hops, since=incident)
        provider = trace_provider(queued["chain"], fetcher, cfg)
        with LabelStore(LABEL_DB) as labels:
            detail = run_case(
                queued["address"], queued["chain"], provider, labels, case_id=case_id,
                meta=queued, cfg=cfg, fetcher=fetcher, label_db_sha256=label_db_sha256(),
                now=datetime.fromisoformat(queued["created_at"].replace("Z", "+00:00")),
                demo=bool(queued.get("demo")),      # a demo wallet traced again is still one
                on_progress=lambda snapshot: _note_progress(case_id, snapshot))
        store.save(detail)
    except Exception as e:  # noqa: BLE001 - whatever went wrong, the case must say so
        why = f"{type(e).__name__}: {e}"[:500]
        try:
            if previous is not None:
                _cases().save({**previous, "status": "done", "error":
                               f"Refresh failed ({why}). Showing the result of "
                               f"{previous['created_at']}."})
            else:
                _cases().set_status(case_id, "failed", error=why)
        except Exception:  # noqa: BLE001 - the store itself is down; nothing more to record
            pass
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(case_id)
            _PROGRESS.pop(case_id, None)


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
    if not Path(LABEL_DB).exists():
        raise HTTPException(503, "The label database is missing. Run `make labels` first.")
    store = _cases()
    _source(response, "live")
    existing = store.find(chain, address)
    cid = existing["id"] if existing else case_id_for(chain, address)
    _note(request, target=cid, address=address, chain=chain)
    with _ACTIVE_LOCK:
        tracing = cid in _ACTIVE
        finished = existing is not None and existing["status"] == "done"
        if existing and (tracing or (finished and not refresh)):
            return {k: existing.get(k) for k in SUMMARY_KEYS}
        _ACTIVE.add(cid)
    # a re-run keeps the details the officer entered unless new ones are given
    old = existing or {}
    summary = S.CaseSummary(
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
    except Exception:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(cid)
        raise
    incident = None
    if body.incident_date is not None:
        incident = datetime(body.incident_date.year, body.incident_date.month,
                            body.incident_date.day, tzinfo=timezone.utc)
    background.add_task(_run_case, cid, body.max_hops, incident, previous)
    return summary


@app.get("/api/cases", response_model=S.CaseList)
def list_cases(response: Response, outcome: S.Outcome | None = None,
               status: S.CaseStatus | None = None):
    live = _cases().list(outcome=outcome, status=status)
    mock = [c for c in _demo_cases()
            if (outcome is None or c.get("outcome") == outcome)
            and (status is None or c["status"] == status)]
    _source(response, "mixed" if live else "mock")
    return {"total": len(live) + len(mock), "items": live + mock}


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
    mock = S.CaseDetail.model_validate(load_mock(f"cases/{case_id}")).model_dump(mode="json")
    return mock, True


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
        return live
    _source(response, "mock")
    return load_mock(f"cases/{case_id}")


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
        _source(response, "mock")
        return load_mock(f"cases/{case_id}/receipt")
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
        load_mock(f"cases/{case_id}")          # 404 for an unknown id
        raise HTTPException(422, "A demo fixture has no trace to verify.")
    if not Path(LABEL_DB).exists():
        raise HTTPException(503, "The label database is missing. Run `make labels` first.")
    _source(response, "live")
    with LabelStore(LABEL_DB) as labels:
        return verify_stored(live, make_verify_fetcher(), labels,
                             label_db_sha256=label_db_sha256())


# ------------------------------------------------------------------ wallets + labels
@app.get("/api/wallets/{chain}/{address}", response_model=S.WalletDetail)
def get_wallet(chain: S.TraceChain, address: str, response: Response):
    try:
        wallet = load_mock(f"wallets/{chain}/{address}")
        kind = "mock"
    except HTTPException:
        wallet = {"address": address, "chain": chain, "labels": [],
                  "risk": {"score": None, "reasons": []}, "cases": []}
        kind = "live"
    store = _labels()
    if store:
        with store:
            hit = store.lookup(address, chain)
        wallet["labels"] = [hit.as_dict()] if hit else []
        kind = "mixed" if kind == "mock" else kind
    seen = {c["case_id"] for c in wallet["cases"]}
    wallet["cases"] = wallet["cases"] + [c for c in _cases().wallet_cases(address, chain)
                                         if c["case_id"] not in seen]
    _source(response, kind)
    return wallet


@app.get("/api/labels/search", response_model=S.LabelSearch)
def search_labels(response: Response, q: str = "", chain: str | None = None,
                  category: S.Category | None = None, tier: S.Tier | None = None,
                  limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    store = _labels()
    if store is None:
        _source(response, "mock")
        return load_mock("labels/search")
    with store:
        total, items = store.search(q, chain=chain, category=category, tier=tier,
                                    limit=limit, offset=offset)
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
    if not desk["rows"]:                 # no finished case names an exchange yet
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
            mock = load_mock(f"vasps/{name}")
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
    if all(c in demo for c in body.case_ids):     # the mock demo cases have no trace
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
    if not live and not svc.desk()["rows"]:
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
            req = load_mock(f"requests/{request_id}")
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
    _source(response, "mock")
    return load_mock(f"requests/{request_id}")


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
    _source(response, "mock")
    req = load_mock(f"requests/{request_id}")
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
    dash = load_mock("dashboard")
    store = _labels()
    if store:
        with store:
            st = store.stats()
        dash["label_coverage"] = {k: st[k] for k in ("total", "by_category", "by_tier",
                                                     "by_chain")}
    _source(response, "mixed" if store else "mock")
    return dash


@app.get("/api/model", response_model=S.ModelInfo)
def get_model(response: Response, chain: str = "tron"):
    """The deposit-address model's measurements (`make model`). Tron is the model whose
    scores the labels carry; `?chain=ethereum` is the explorer-tagged benchmark."""
    from ..classify.report import model_info, read_metrics
    if not _SAFE.match(chain):
        raise HTTPException(404, "not found")
    metrics = read_metrics(MODEL_DIR, chain)
    if metrics is None:
        _source(response, "mock")
        return load_mock("model")
    _source(response, "live")
    from ..eval.abstain import abstain_info, read_validation
    validation = read_validation(ABSTAIN_DIR, chain)
    return {**model_info(metrics),
            "abstain": abstain_info(validation) if validation else None}


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
            return FileResponse(file)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
    if path in ("", "index.html"):
        return FileResponse(CONSOLE, media_type="text/html",
                            headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "not found")
