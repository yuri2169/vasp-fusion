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

No authentication: a single-officer workstation, as in BTC-FUSION. Login and the
audit trail arrive in B9.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import chains
from ..cases import case_id_for, file_sha256, run_case, skeleton, trace_provider
from ..labels.lookup import DEFAULT_DB, LabelStore
from ..store.cases import SUMMARY_KEYS, CaseStore
from ..trace import TraceConfig
from . import schemas as S

ROOT = Path(__file__).resolve().parents[2]
MOCKS = ROOT / "mocks"
LABEL_DB = DEFAULT_DB
MODEL_DIR = ROOT / "artifacts" / "model_v1"   # metrics.json per chain (`make model`)
ABSTAIN_DIR = ROOT / "artifacts" / "abstain_v1"   # validation.json per chain (`make abstain-eval`)
CASE_DB: Path | None = None      # None = data/case.duckdb (or VASPFUSION_CASE_DB)
DESK_DB: Path | None = None      # None = data/desk.duckdb (or VASPFUSION_DESK_DB)
OUTBOX: Path | None = None       # None = data/sahyog_outbox (or VASPFUSION_SAHYOG_OUTBOX)
DIRECTORY = ROOT / "data" / "vasp_directory.yaml"   # cited facts only (B8)
VERSION = "0.1.0"
# Chains a trace can run on today. BSC has no free data source; Solana and Avalanche
# have no adapter yet (PROGRESS.md, B2); Bitcoin waits for B5 (a UTXO transaction is
# not a wallet-to-wallet transfer, and the basic adapter would overstate what was sent).
TRACEABLE = ("tron", "ethereum", "polygon", "arbitrum", "base", "optimism")

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


# ------------------------------------------------------------------ mocks
# Which model each mock file validates against. Paths mirror the API's URLs.
MOCK_MODELS: list[tuple[str, type[BaseModel]]] = [
    (r"cases", S.CaseList),
    (r"cases/[^/]+", S.CaseDetail),
    (r"wallets/[^/]+/[^/]+", S.WalletDetail),
    (r"labels/search", S.LabelSearch),
    (r"desk", S.Desk),
    (r"vasps/[^/]+", S.VaspDetail),
    (r"requests/[^/]+", S.RequestDetail),
    (r"dashboard", S.Dashboard),
    (r"model", S.ModelInfo),
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
    return S.Health(status="ok", version=VERSION, label_db=Path(LABEL_DB).exists(),
                    data_mode="mixed")


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


def _run_case(case_id: str, max_hops: int, incident: datetime | None,
              previous: dict | None = None) -> None:
    """Trace the wallet and store the result. Runs after the POST has answered.
    `previous` is the finished case being refreshed: it is kept if the new run fails."""
    try:
        store = _cases()
        queued = store.get(case_id)
        store.set_status(case_id, "running")
        fetcher = make_fetcher()
        cfg = TraceConfig(max_hops=max_hops, since=incident)
        provider = trace_provider(queued["chain"], fetcher, cfg)
        with LabelStore(LABEL_DB) as labels:
            detail = run_case(
                queued["address"], queued["chain"], provider, labels, case_id=case_id,
                meta=queued, cfg=cfg, fetcher=fetcher, label_db_sha256=label_db_sha256(),
                now=datetime.fromisoformat(queued["created_at"].replace("Z", "+00:00")))
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


@app.post("/api/cases", response_model=S.CaseSummary, status_code=202)
def create_case(body: S.CaseCreate, response: Response, background: BackgroundTasks,
                refresh: bool = Query(False, description="Trace again even if this wallet "
                                                         "already has a finished case")):
    for c in _demo_cases():          # the mock demo wallets are not on any chain
        if c["address"] == body.address.strip():
            _source(response, "mock")
            return c
    chain, address = _resolve(body)
    if not Path(LABEL_DB).exists():
        raise HTTPException(503, "The label database is missing. Run `make labels` first.")
    store = _cases()
    _source(response, "live")
    existing = store.find(chain, address)
    cid = existing["id"] if existing else case_id_for(chain, address)
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


@app.get("/api/cases/{case_id}", response_model=S.CaseDetail)
def get_case(case_id: str, response: Response):
    live = _cases().get(case_id)
    if live is not None:
        _source(response, "live")
        return live
    _source(response, "mock")
    return load_mock(f"cases/{case_id}")


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
def create_request(body: S.RequestCreate, response: Response):
    from ..desk.service import DeskError
    demo_ids = {c["id"] for c in _demo_cases()}
    if all(c in demo_ids for c in body.case_ids):     # the mock demo cases have no trace
        _source(response, "mock")
        return _demo_request_for(body.vasp)
    _source(response, "live")
    try:
        return _desk().create(body.vasp, body.case_ids, list(body.asks), body.officer,
                              body.wallets)
    except DeskError as e:
        raise _refused(e) from None


def _request_pdf(request_id: str) -> Response:
    from ..desk.pdf import letter_pdf
    from ..desk.service import DeskError
    try:
        svc = _desk()
        req = svc.get(request_id)
        if req is not None:
            pdf = svc.pdf(request_id)
            name = request_id + ("-draft" if req["letter"]["watermark"] else "")
        else:
            req = load_mock(f"requests/{request_id}")
            req["letter"]["watermark"] = "Demo fixture - not evidence"
            pdf, name = letter_pdf(req), f"{request_id}-demo"
    except DeskError as e:
        raise _refused(e) from None
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


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
def patch_request(request_id: str, body: S.RequestPatch, response: Response):
    """Move a request along: drafted -> approved -> sent -> acknowledged -> answered |
    freeze_confirmed | refused. 409 for a step that is not allowed from where it is.
    Sending hands the payload and the letter to the gateway (a local outbox)."""
    from ..desk.service import DeskError
    svc = _desk()
    if svc.get(request_id) is not None:
        _source(response, "live")
        try:
            return svc.patch(request_id, body.status, body.note)
        except DeskError as e:
            raise _refused(e) from None
    # a mock demo request: the new status is applied to the reply, nothing persists
    _source(response, "mock")
    req = load_mock(f"requests/{request_id}")
    req["status"] = body.status
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
