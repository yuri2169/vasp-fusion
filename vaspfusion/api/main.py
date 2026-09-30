"""FastAPI surface. Every route in docs/api_contract.md is declared here with its
response model, so the OpenAPI schema (and ui/src/api/types.ts) is complete from
day one.

Until the backend phases land, routes answer from mocks/*.json (validated
against the same models) and say so in the `X-Data-Source` header. The label
store is live from B1: label search and wallet labels read data/labels.duckdb.
Phases replace mock handlers route by route (B3 cases, B8 desk/requests,
B6/B7 model), keeping the models unchanged.

No authentication: a single-officer workstation, as in BTC-FUSION. Login and the
audit trail arrive in B9.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..labels.lookup import DEFAULT_DB, LabelStore
from . import schemas as S

ROOT = Path(__file__).resolve().parents[2]
MOCKS = ROOT / "mocks"
LABEL_DB = DEFAULT_DB
VERSION = "0.1.0"

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


# ------------------------------------------------------------------ chain guess
_PATTERNS = [
    ("tron", re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")),
    ("ethereum", re.compile(r"^0x[0-9a-fA-F]{40}$")),
    ("bitcoin", re.compile(r"^(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$")),
    ("solana", re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")),
]


def guess_chain(address: str) -> str | None:
    """Format-only guess, enough to label a case. B2's validators (base58check,
    EIP-55, bech32) replace it. An EVM address is reported as ethereum; the
    officer picks bsc/polygon explicitly."""
    return next((c for c, p in _PATTERNS if p.match(address.strip())), None)


# ------------------------------------------------------------------ health
@app.get("/api/health", response_model=S.Health)
def health():
    return S.Health(status="ok", version=VERSION, label_db=Path(LABEL_DB).exists(),
                    data_mode="mixed")


# ------------------------------------------------------------------ cases (B3)
def _demo_cases() -> list[dict]:
    return load_mock("cases")["items"]


@app.post("/api/cases", response_model=S.CaseSummary, status_code=202)
def create_case(body: S.CaseCreate, response: Response):
    chain = body.chain or guess_chain(body.address)
    if chain is None:
        raise HTTPException(422, "Could not tell which chain this address is on. "
                                 "Pick the chain and try again.")
    _source(response, "mock")
    for c in _demo_cases():
        if c["address"] == body.address.strip():
            return c
    cid = "c-" + hashlib.sha256(f"{chain}:{body.address.strip()}".encode()).hexdigest()[:10]
    return S.CaseSummary(id=cid, address=body.address.strip(), chain=chain, status="queued",
                         case_ref=body.case_ref, complaint_no=body.complaint_no,
                         amount_lost_inr=body.amount_lost_inr,
                         created_at=datetime.now(timezone.utc))


@app.get("/api/cases", response_model=S.CaseList)
def list_cases(response: Response, outcome: S.Outcome | None = None,
               status: S.CaseStatus | None = None):
    _source(response, "mock")
    items = [c for c in _demo_cases()
             if (outcome is None or c.get("outcome") == outcome)
             and (status is None or c["status"] == status)]
    return {"total": len(items), "items": items}


@app.get("/api/cases/{case_id}", response_model=S.CaseDetail)
def get_case(case_id: str, response: Response):
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
@app.get("/api/desk", response_model=S.Desk)
def get_desk(response: Response):
    _source(response, "mock")
    return load_mock("desk")


@app.get("/api/vasps/{name}", response_model=S.VaspDetail)
def get_vasp(name: str, response: Response):
    _source(response, "mock")
    return load_mock(f"vasps/{name}")


def _demo_request_for(vasp: str) -> dict:
    for path in sorted((MOCKS / "requests").glob("*.json")):
        req = load_mock(f"requests/{path.stem}")
        if req["vasp"] == vasp:
            return req
    raise HTTPException(404, f"No demo request for {vasp}. Drafting arrives with B8.")


@app.post("/api/requests", response_model=S.RequestDetail, status_code=201)
def create_request(body: S.RequestCreate, response: Response):
    _source(response, "mock")
    return _demo_request_for(body.vasp)


@app.get("/api/requests/{request_id}", response_model=S.RequestDetail)
def get_request(request_id: str, response: Response):
    _source(response, "mock")
    return load_mock(f"requests/{request_id}")


@app.patch("/api/requests/{request_id}", response_model=S.RequestDetail)
def patch_request(request_id: str, body: S.RequestPatch, response: Response):
    """Mock: returns the request with the new status applied; nothing persists."""
    _source(response, "mock")
    req = load_mock(f"requests/{request_id}")
    req["status"] = body.status
    req["status_history"].append({"status": body.status, "note": body.note,
                                  "at": datetime.now(timezone.utc).isoformat()})
    if body.status != "drafted":
        req["letter"]["watermark"] = None
    return req


@app.get("/api/requests/{request_id}/pdf", responses={501: {"description": "Until B8"}})
def get_request_pdf(request_id: str):
    raise HTTPException(501, "Letter PDFs are generated from B8. Use the print view.")


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
def get_model(response: Response):
    _source(response, "mock")
    return load_mock("model")
