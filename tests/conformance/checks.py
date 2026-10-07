"""The SAHYOG contract as checks that run over HTTP against two running programs
(docs/sahyog_contract.md). Nothing here imports the tool or the reference portal: a
check knows only base addresses and credentials, so the same checks can be pointed at
another portal implementation, or at a test environment of the real one.

    portal_checks(pair)   the portal's half, called as the tool would call it
    tool_checks(pair)     the tool's half, called as a portal would call it
    round_trip(pair)      both, through the reference portal's own screen API

Each returns the list of checks it made, as sentences; a check that fails raises
AssertionError with what was expected and what came back.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class Pair:
    tool: str                       # base address of the tool
    portal: str                     # base address of the portal
    key: str
    secret: str
    wallet: str                     # a wallet the tool can trace to an exchange
    vasp: str                       # the exchange that trace names
    tool_headers: dict = field(default_factory=dict)   # an officer's session, if required
    wait_s: float = 60.0


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode()


def sign(secret: str, timestamp: str, nonce: str, method: str, path: str, body: bytes) -> str:
    text = f"v1\n{timestamp}\n{nonce}\n{method}\n{path}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def signed(pair: Pair, method: str, path: str, body: bytes, *, secret: str | None = None,
           at: float | None = None, nonce: str | None = None) -> dict:
    timestamp = str(int(at if at is not None else time.time()))
    nonce = nonce or secrets.token_urlsafe(18)
    return {"X-SAHYOG-Key": pair.key, "X-SAHYOG-Timestamp": timestamp, "X-SAHYOG-Nonce": nonce,
            "X-SAHYOG-Signature": "v1=" + sign(secret or pair.secret, timestamp, nonce, method,
                                               path, body)}


def http(method: str, url: str, body: bytes | None = None, headers: dict | None = None):
    """(status, parsed JSON or text)."""
    req = urllib.request.Request(url, data=body, method=method, headers={
        **({"Content-Type": "application/json"} if body else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def call(pair: Pair, base: str, method: str, path: str, payload: dict | None = None, **how):
    body = canonical(payload) if payload is not None else b""
    extra = how.pop("headers", {})
    return http(method, base + path, body or None, {**signed(pair, method, path, body, **how),
                                                    **extra})


def expect(done: list, what: str, ok: bool, got=None) -> None:
    assert ok, f"{what}: got {got!r}"
    done.append(what)


def _until(read, ready, wait_s: float):
    deadline = time.monotonic() + wait_s
    while True:
        value = read()
        if ready(value) or time.monotonic() > deadline:
            return value
        time.sleep(0.2)


def _request_payload(rid: str) -> tuple[dict, bytes]:
    letter = b"%PDF-1.4\n% a conformance letter, " + rid.encode()
    return {"schema": "vaspfusion-sahyog-request/1", "request_id": rid,
            "reference": f"VF/REQ/{rid[4:8]}/{rid[9:]}", "draft": False,
            "recipient": {"vasp": "Conformance Exchange"}, "asks": ["kyc"], "wallets": [],
            "documents": [{"name": f"{rid}.pdf", "media_type": "application/pdf",
                           "sha256": hashlib.sha256(letter).hexdigest()}]}, letter


# --------------------------------------------------------------------------- the portal
def portal_checks(pair: Pair) -> list[str]:
    done: list[str] = []
    p = pair.portal
    s, body = call(pair, p, "GET", "/v1/health")
    expect(done, "the portal answers a signed health call", s == 200, (s, body))

    s, body = http("GET", p + "/v1/health")
    expect(done, "the portal refuses an unsigned call (401)", s == 401, (s, body))
    s, body = call(pair, p, "GET", "/v1/health", secret="not-the-secret")
    expect(done, "the portal refuses a bad signature (401)", s == 401, (s, body))
    s, body = call(pair, p, "GET", "/v1/health", at=time.time() - 3600)
    expect(done, "the portal refuses a timestamp an hour old (401)", s == 401, (s, body))
    wrong_key = Pair(**{**pair.__dict__, "key": "not-the-key"})
    s, body = call(wrong_key, p, "GET", "/v1/health")
    expect(done, "the portal refuses a wrong API key (401)", s == 401, (s, body))

    rid = f"req-2099-{secrets.randbelow(10**8):08d}"
    payload, letter = _request_payload(rid)
    digest = hashlib.sha256(canonical(payload)).hexdigest()
    sent = {"payload": payload, "letter_pdf_b64": base64.b64encode(letter).decode()}
    raw = canonical(sent)
    headers = signed(pair, "POST", "/v1/requests", raw)
    s, first = http("POST", p + "/v1/requests", raw, headers)
    expect(done, "the portal accepts an approved request with its letter and answers a "
                 "receipt for that payload",
           s in (200, 201) and first.get("payload_sha256") == digest and first.get("receipt_id"),
           (s, first))
    s, body = http("POST", p + "/v1/requests", raw, headers)
    expect(done, "the portal refuses the same signed call a second time as a replay (409)",
           s == 409, (s, body))
    s, again = call(pair, p, "POST", "/v1/requests", sent)
    expect(done, "a duplicate delivery, signed afresh, gets the same receipt and is not held "
                 "twice", s in (200, 201) and again.get("receipt_id") == first["receipt_id"],
           (s, again))
    other = {**sent, "payload": {**payload, "asks": ["kyc", "freeze"]}}
    s, body = call(pair, p, "POST", "/v1/requests", other)
    expect(done, "a different payload under an id already held is refused (409)", s == 409,
           (s, body))
    tampered = raw.replace(b"Conformance Exchange", b"Another Exchange....")
    s, body = http("POST", p + "/v1/requests", tampered,
                   signed(pair, "POST", "/v1/requests", raw))
    expect(done, "a body changed after signing is refused (401)", s == 401, (s, body))
    draft_id = f"req-2099-{secrets.randbelow(10**8):08d}"
    draft, dl = _request_payload(draft_id)
    s, body = call(pair, p, "POST", "/v1/requests", {
        "payload": {**draft, "draft": True}, "letter_pdf_b64": base64.b64encode(dl).decode()})
    expect(done, "a draft is refused (422)", s == 422, (s, body))
    s, body = call(pair, p, "POST", "/v1/requests", {
        "payload": draft, "letter_pdf_b64": base64.b64encode(dl + b" changed").decode()})
    expect(done, "a letter that is not the document the payload names is refused (422)",
           s == 422, (s, body))

    result = {"schema": "vaspfusion-sahyog-result/1", "complaint_ref": f"CONF-{rid[9:]}",
              "wallet": {"address": pair.wallet, "case_id": "c-conformance", "status": "result",
                         "outcome": "INSUFFICIENT_EVIDENCE", "exchanges": []}}
    s, body = call(pair, p, "POST", "/v1/results", result)
    expect(done, "the portal accepts a result and answers a receipt for it",
           s in (200, 201)
           and body.get("payload_sha256") == hashlib.sha256(canonical(result)).hexdigest(),
           (s, body))
    s, body = call(pair, p, "POST", "/v1/results", result)
    expect(done, "the same result delivered again is accepted (it replaces the first)",
           s in (200, 201), (s, body))
    return done


# --------------------------------------------------------------------------- the tool
def tool_checks(pair: Pair) -> list[str]:
    done: list[str] = []
    t = pair.tool
    ref = f"CONF-T-{secrets.randbelow(10**8):08d}"
    complaint = {"complaint_ref": ref, "agency": "Conformance suite", "officer": "A. Tester",
                 "category": "other", "wallets": [{"address": pair.wallet},
                                                  {"address": "not-an-address"}]}
    raw = canonical(complaint)
    path = "/api/sahyog/complaints"

    s, body = http("POST", t + path, raw, {"X-SAHYOG-Key": pair.key})
    expect(done, "the tool refuses an unsigned complaint (401)", s == 401, (s, body))
    s, body = http("POST", t + path, raw, signed(pair, "POST", path, raw, secret="wrong"))
    expect(done, "the tool refuses a bad signature (401)", s == 401, (s, body))
    s, body = http("POST", t + path, raw, signed(pair, "POST", path, raw,
                                                 at=time.time() - 3600))
    expect(done, "the tool refuses a timestamp an hour old (401)", s == 401, (s, body))
    s, body = call(pair, t, "GET", f"/api/sahyog/complaints/{ref}")
    expect(done, "nothing was opened by the refused calls (404)", s == 404, (s, body))

    headers = signed(pair, "POST", path, raw)
    s, filed = http("POST", t + path, raw, headers)
    wallets = filed.get("wallets", []) if isinstance(filed, dict) else []
    good = [w for w in wallets if w.get("accepted")]
    bad = [w for w in wallets if not w.get("accepted")]
    expect(done, "a signed complaint is accepted (202) with one case for the valid wallet",
           s == 202 and len(good) == 1 and good[0].get("case_id"), (s, filed))
    expect(done, "the bad address is refused by name; the valid one still goes through",
           len(bad) == 1 and "not-an-address" in (bad[0].get("error") or ""), bad)
    s, body = http("POST", t + path, raw, headers)
    expect(done, "the tool refuses the same signed call a second time as a replay (409)",
           s == 409, (s, body))
    s, again = call(pair, t, "POST", path, complaint)
    expect(done, "a duplicate delivery, signed afresh, returns the same case and opens "
                 "nothing new",
           s == 202 and [w.get("case_id") for w in again["wallets"] if w.get("accepted")]
           == [good[0]["case_id"]], (s, again))

    status = _until(lambda: call(pair, t, "GET", f"/api/sahyog/complaints/{ref}")[1],
                    lambda b: isinstance(b, dict) and b.get("status") == "result", pair.wait_s)
    wallet = next(w for w in status["wallets"] if w.get("accepted"))
    expect(done, "the wallet is traced with nobody touching the tool, and the status route "
                 "gives the result", status.get("status") == "result"
           and wallet.get("status") == "result" and wallet.get("outcome"), status)
    expect(done, "the result keeps proximity and confidence apart for every exchange",
           all({"vasp", "proximity_rank", "hops", "confidence"} <= set(e)
               for e in wallet["exchanges"]), wallet["exchanges"])

    s, body = call(pair, t, "POST", "/api/sahyog/requests/req-2099-00000000/replies",
                   {"status": "acknowledged"})
    expect(done, "a reply to a request the tool never sent is refused (404)", s == 404,
           (s, body))
    return done


# --------------------------------------------------------------------------- both
def round_trip(pair: Pair) -> list[str]:
    """Through the reference portal's screen API and the tool's officer API: complaint
    in, automatic trace, result back, request out, reply in."""
    done: list[str] = []
    t, p, officer = pair.tool, pair.portal, pair.tool_headers
    ref = f"CONF-R-{secrets.randbelow(10**8):08d}"
    s, filed = http("POST", p + "/api/sahyog-sim/complaints", canonical({
        "complaint_ref": ref, "agency": "Conformance suite", "officer": "A. Tester",
        "category": "investment_fraud", "wallets": [{"address": pair.wallet}]}))
    expect(done, "a complaint filed at the portal reaches the tool, which opens a case",
           s == 202 and filed["wallets"][0].get("case_id"), (s, filed))
    case_id = filed["wallets"][0]["case_id"]

    def mine(screen):
        return next((c for c in screen.get("complaints", [])
                     if c["complaint_ref"] == ref), {}) if isinstance(screen, dict) else {}

    screen = _until(lambda: http("GET", p + "/api/sahyog-sim")[1],
                    lambda b: mine(b).get("status") == "result", pair.wait_s)
    wallet = (mine(screen).get("wallets") or [{}])[0]
    expect(done, "the portal sees the result: the exchange named, with its confidence",
           wallet.get("status") == "result" and wallet.get("top_vasp") == pair.vasp
           and wallet.get("confidence") is not None, mine(screen))
    status = _until(lambda: call(pair, t, "GET", f"/api/sahyog/complaints/{ref}")[1],
                    lambda b: (b.get("wallets") or [{}])[0].get("result_sent_at"), pair.wait_s)
    expect(done, "the tool pushed the result to the portal over HTTP and holds its receipt",
           status["wallets"][0].get("result_sent_at") and screen is not None
           and http("GET", p + "/api/sahyog-sim")[1].get("results_received", 0) >= 1, status)

    s, case = http("GET", f"{t}/api/cases/{case_id}", headers=officer)
    # the reference is that of the first complaint that reported this wallet
    expect(done, "the case says it was reported through SAHYOG, with a complaint reference",
           s == 200 and case.get("sahyog_complaint_ref"), (s, case.get("sahyog_complaint_ref")))

    s, req = http("POST", t + "/api/requests", canonical({
        "vasp": pair.vasp, "case_ids": [case_id], "asks": ["kyc", "freeze"],
        "officer": "A. Tester, Conformance suite"}), officer)
    if s == 409:        # the same wallet already has a request from an earlier run
        s, listing = http("GET", t + "/api/requests", headers=officer)
        rows = [r for r in listing["items"] if case_id in r.get("case_ids", [])
                and r["status"] != "withdrawn"]
        s, req = http("GET", f"{t}/api/requests/{rows[0]['id']}", headers=officer)
    expect(done, "an officer drafts a request to the named exchange", s in (200, 201)
           and req.get("id"), (s, req))
    rid = req["id"]
    if req["status"] == "drafted":
        s, req = http("PATCH", f"{t}/api/requests/{rid}", canonical({"status": "approved"}),
                      officer)
    if req["status"] == "approved":
        s, req = http("PATCH", f"{t}/api/requests/{rid}", canonical({"status": "sent"}),
                      officer)
    receipt = req.get("receipt") or {}
    expect(done, "the approved request is submitted to the portal over HTTP and the tool "
                 "holds the portal's receipt", receipt.get("gateway") == "sahyog-http"
           and receipt.get("receipt_id"), (s, req.get("status"), receipt))

    screen = http("GET", p + "/api/sahyog-sim")[1]
    held = next((r for r in screen["requests"] if r["id"] == rid), None)
    expect(done, "the portal holds the request, with the exchange and what is asked",
           held is not None and held["vasp"] == pair.vasp and "freeze" in held["asks"], held)
    s, pdf = 0, None
    try:
        with urllib.request.urlopen(f"{p}/api/sahyog-sim/requests/{rid}/letter", timeout=30) as r:
            s, pdf = r.status, r.read()
    except urllib.error.HTTPError as e:
        s = e.code
    expect(done, "the portal holds the letter, and it is the document the payload names",
           s == 200 and pdf is not None
           and hashlib.sha256(pdf).hexdigest() == receipt_sha(t, rid, officer), s)

    if "freeze_confirmed" in held["allowed_replies"]:
        s, ack = http("POST", f"{p}/api/sahyog-sim/requests/{rid}/reply", canonical({
            "status": "freeze_confirmed", "note": "Frozen pending the order.",
            "reply_ref": "CX-CONF-1"}))
        expect(done, "the exchange's reply goes from the portal to the tool", s == 200
               and ack.get("status") == "freeze_confirmed", (s, ack))
    s, after = http("GET", f"{t}/api/requests/{rid}", headers=officer)
    last = after["status_history"][-1]
    expect(done, 'the request desk reads "freeze confirmed", received through SAHYOG',
           after["status"] == "freeze_confirmed" and last.get("via") == "sahyog", last)
    s, again = http("POST", f"{p}/api/sahyog-sim/requests/{rid}/reply", canonical({
        "status": "freeze_confirmed"}))
    s2, same = http("GET", f"{t}/api/requests/{rid}", headers=officer)
    expect(done, "the same reply delivered again changes nothing",
           s == 200 and len(same["status_history"]) == len(after["status_history"]), (s, again))
    return done


def receipt_sha(tool: str, rid: str, officer: dict) -> str:
    _, req = http("GET", f"{tool}/api/requests/{rid}", headers=officer)
    return req["payload"]["documents"][0]["sha256"]
