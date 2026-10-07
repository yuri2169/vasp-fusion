"""The reference portal's HTTP interface.

Signed, system to system (the portal's half of docs/sahyog_contract.md):
    GET  /v1/health      who answers
    POST /v1/requests    an approved request from the tool, with its letter
    POST /v1/results     the result of one wallet of a complaint

Its own screen (the simulator), for a person playing the reporting officer and the
exchange. These carry no login: the program is a demonstration and binds to this machine.
    GET  /api/sahyog-sim
    POST /api/sahyog-sim/complaints
    POST /api/sahyog-sim/requests/{id}/reply
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from . import NOTICE
from .client import ToolClient
from .signing import Refused, check
from .store import Store

ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = re.compile(r"^req-\d{4}-\d{4,}$")
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
CATEGORIES = ["investment_fraud", "job_fraud", "impersonation", "phishing", "ransomware",
              "extortion", "loan_app", "other"]
# The status machine of a sent request, from the contract (section 6).
NEXT = {"sent": ["acknowledged", "answered", "freeze_confirmed", "refused"],
        "acknowledged": ["answered", "freeze_confirmed", "refused"],
        "answered": ["freeze_confirmed"], "freeze_confirmed": [], "refused": []}
MARK = '<meta name="vf-portal" content="reference-portal">'


def _secret(env: str, file_env: str, default: Path) -> str | None:
    value = os.environ.get(env, "").strip()
    if value:
        return value
    file = Path(os.environ.get(file_env) or default)
    return (file.read_text().strip() or None) if file.is_file() else None


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(*, tool_url: str | None = None, db: Path | str | None = None,
               key: str | None = None, secret: str | None = None,
               tool_public_url: str | None = None, ui_dist: Path | str | None = None) -> FastAPI:
    """`tool_url` is where this program reaches the tool; `tool_public_url` is where a
    person's browser reaches it (they differ inside docker compose)."""
    tool_url = (tool_url or os.environ.get("PORTAL_TOOL_URL") or "http://127.0.0.1:8000").rstrip("/")
    public = (tool_public_url or os.environ.get("PORTAL_TOOL_PUBLIC_URL") or tool_url).rstrip("/")
    store = Store(db or os.environ.get("PORTAL_DB") or ROOT / "data" / "refportal.sqlite")
    dist = Path(ui_dist or os.environ.get("PORTAL_UI_DIST") or ROOT / "ui" / "dist")

    def creds() -> tuple[str, str]:
        k = key or _secret("SAHYOG_API_KEY", "PORTAL_KEY_FILE", ROOT / "data" / "sahyog_api_key")
        s = secret or _secret("SAHYOG_SIGNING_SECRET", "PORTAL_SECRET_FILE",
                              ROOT / "data" / "sahyog_signing_secret")
        if not (k and s):
            raise HTTPException(503, "The reference portal has no credentials: set "
                                     "SAHYOG_API_KEY and SAHYOG_SIGNING_SECRET, or run the "
                                     "tool's demo set-up, which writes both files.")
        return k, s

    def tool() -> ToolClient:
        return ToolClient(tool_url, *creds())

    app = FastAPI(title="SAHYOG reference portal (a simulator, not the SAHYOG portal)",
                  docs_url=None, redoc_url=None)

    async def signed(request: Request) -> bytes:
        """The body of a call the tool signed; anything else is refused."""
        k, s = creds()
        body = await request.body()
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        try:
            nonce = check(k, s, request.headers, request.method, path, body)
        except Refused as e:
            raise HTTPException(e.status, str(e)) from None
        if not store.claim_nonce(nonce):
            raise HTTPException(409, "This signed call was received before and is refused "
                                     "as a replay.")
        return body

    def _json(body: bytes) -> dict:
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            raise HTTPException(422, "The body is not a JSON object.")
        return parsed

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if (request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD")
                and origin and urlsplit(origin).netloc != request.headers.get("host")):
            return Response(json.dumps({"detail": "A write from another site is refused."}),
                            status_code=403, media_type="application/json")
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    # ------------------------------------------------------------ signed: the tool calls
    @app.get("/v1/health")
    async def health(request: Request):
        await signed(request)
        return {"service": "reference-portal", "notice": NOTICE, "contract": "sahyog_contract/2"}

    @app.post("/v1/requests")
    async def take_request(request: Request):
        sent = _json(await signed(request))
        payload = sent.get("payload")
        if not isinstance(payload, dict) or not isinstance(sent.get("letter_pdf_b64"), str):
            raise HTTPException(422, "A request is {payload, letter_pdf_b64}.")
        rid = str(payload.get("request_id"))
        if not REQUEST_ID.match(rid):
            raise HTTPException(422, f"{rid[:40]!r} is not a request id.")
        if payload.get("draft") is not False:
            raise HTTPException(422, "A draft is refused: the request must be approved.")
        try:
            letter = base64.b64decode(sent["letter_pdf_b64"], validate=True)
        except ValueError:
            raise HTTPException(422, "letter_pdf_b64 is not base64.") from None
        named = (payload.get("documents") or [{}])[0].get("sha256")
        if named != hashlib.sha256(letter).hexdigest():
            raise HTTPException(422, "The letter is not the document the payload names "
                                     "(documents[0].sha256).")
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        held = store.request(rid)
        if held is None:
            store.add_request(rid, digest, {"payload": payload, "status": "sent",
                                            "last_note": None,
                                            "sent_at": _iso(time.time())}, letter)
            held = store.request(rid)
        elif held["digest"] != digest:
            raise HTTPException(409, f"{rid} is already held with different contents.")
        return {"receipt_id": f"rp-{digest[:12]}", "received_at": _iso(held["received_at"]),
                "payload_sha256": digest}

    @app.post("/v1/results")
    async def take_result(request: Request):
        body = await signed(request)
        payload = _json(body)
        wallet = payload.get("wallet") or {}
        if payload.get("schema") != "vaspfusion-sahyog-result/1" \
                or not payload.get("complaint_ref") or not wallet.get("case_id"):
            raise HTTPException(422, "A result is a vaspfusion-sahyog-result/1 with a "
                                     "complaint_ref and a wallet.case_id.")
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        store.save_result(f"{payload['complaint_ref']}__{wallet['case_id']}", payload)
        return {"receipt_id": f"rp-{digest[:12]}", "received_at": _iso(time.time()),
                "payload_sha256": digest}

    # ------------------------------------------------------------ its own screen
    def _request_view(r: dict) -> dict:
        p = r["payload"]
        return {"id": p["request_id"], "reference": p.get("reference") or p["request_id"],
                "vasp": (p.get("recipient") or {}).get("vasp") or "", "status": r["status"],
                "asks": p.get("asks") or [], "wallets": len(p.get("wallets") or []),
                "sent_at": r.get("sent_at"), "allowed_replies": NEXT.get(r["status"], []),
                "last_note": r.get("last_note")}

    def _refresh(complaint: dict) -> dict:
        """Ask the tool where a complaint stands, unless it already has its result."""
        if complaint.get("status") == "result":
            return complaint
        ref = complaint["complaint_ref"]
        status, answer = tool().call("GET", f"/api/sahyog/complaints/{ref}")
        if status == 200:
            store.save_complaint(ref, answer)
            return answer
        return complaint

    @app.get("/api/health")
    def api_health():
        return {"service": "reference-portal", "notice": NOTICE}

    @app.get("/api/sahyog-sim")
    def screen():
        out = {"enabled": True, "notice": NOTICE, "why_disabled": None,
               "categories": CATEGORIES, "complaints": [], "requests": [],
               "tool_url": public, "results_received": 0}
        try:
            creds()
        except HTTPException as e:
            return {**out, "enabled": False, "why_disabled": e.detail}
        out["complaints"] = [_refresh(c) for c in store.complaints()]
        out["requests"] = [_request_view(r) for r in store.requests()]
        out["results_received"] = len(store.results())
        return out

    @app.post("/api/sahyog-sim/complaints", status_code=202)
    def file_complaint(body: dict = Body(...)):
        # not async: the tool may call back (a result for a wallet it has already traced)
        # before it answers, and this program must be free to take that call
        ref = str(body.get("complaint_ref") or "")
        if not REF.match(ref):
            raise HTTPException(422, "complaint_ref: 3 to 64 letters, digits, '.', '_' or '-'.")
        status, answer = tool().call("POST", "/api/sahyog/complaints", body,
                                     idempotency=f"complaint:{ref}")
        if status != 202:
            raise HTTPException(502 if status == 599 else status,
                                answer.get("detail") or "The tool refused the complaint.")
        store.save_complaint(ref, answer)
        return answer

    @app.post("/api/sahyog-sim/requests/{request_id}/reply")
    def reply(request_id: str, body: dict = Body(...)):
        held = store.request(request_id) if REQUEST_ID.match(request_id) else None
        if held is None:
            raise HTTPException(404, f"No request {request_id[:40]} has been received.")
        status, answer = tool().call("POST", f"/api/sahyog/requests/{request_id}/replies",
                                     {k: body.get(k) for k in ("status", "note", "reply_ref")},
                                     idempotency=f"reply:{request_id}:{body.get('status')}")
        if status != 200:
            raise HTTPException(502 if status == 599 else status,
                                answer.get("detail") or "The tool refused the reply.")
        store.update_request(request_id, {
            "payload": held["payload"], "sent_at": held.get("sent_at"),
            "status": answer["status"],
            "last_note": (body.get("note") or None)})
        return answer

    @app.get("/api/sahyog-sim/requests/{request_id}/letter")
    def letter(request_id: str):
        pdf = store.letter(request_id) if REQUEST_ID.match(request_id) else None
        if pdf is None:
            raise HTTPException(404, "No such request.")
        return Response(pdf, media_type="application/pdf")

    # ------------------------------------------------------------ the interface
    @app.get("/{path:path}", include_in_schema=False)
    def interface(path: str):
        if path.startswith(("api/", "v1/")):
            raise HTTPException(404, "not found")
        root = dist.resolve()
        index = root / "index.html"
        if not index.is_file():
            return HTMLResponse(f"<!doctype html><title>Reference portal</title><p><strong>"
                                f"{NOTICE}</strong></p><p>The interface is not built "
                                "(<code>make ui-build</code>). The API is at "
                                "<code>/api/sahyog-sim</code>.</p>")
        file = (root / path).resolve()
        if path and file.is_file() and root in file.parents:
            return FileResponse(file)
        # the same build as the tool's, told that the portal is serving it
        html = re.sub(r"<title>.*?</title>", f"<title>Reference portal · {NOTICE}</title>",
                      index.read_text(), count=1, flags=re.S)
        html = html.replace("<head>", f"<head>{MARK}", 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    return app
