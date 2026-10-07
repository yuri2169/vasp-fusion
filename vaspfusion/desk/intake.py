"""The SAHYOG intake: complaints in, results back.

SAHYOG's interface is not public, so this is our side of a contract
(docs/sahyog_contract.md): the portal posts a complaint with its wallets, one case is
opened and traced per wallet, and each result is handed to the gateway. The routes are
in api/main.py; this module holds what does not need the web framework: the API key,
the result payload, and how a complaint's state is read from its cases.
"""
from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from ..api.schemas import RISK_BASIS

ROOT = Path(__file__).resolve().parents[2]
KEY_HEADER = "X-SAHYOG-Key"
DEFAULT_KEY_FILE = ROOT / "data" / "sahyog_api_key"
RESULT_SCHEMA = "vaspfusion-sahyog-result/1"
REPLY_SCHEMA = "vaspfusion-sahyog-reply/1"
REPLIES = ("acknowledged", "answered", "freeze_confirmed", "refused")
MAX_HOPS = 3
NOTICE = "A simulator for demonstration. Not the SAHYOG portal."
_CASE_STATE = {"queued": "received", "running": "tracing", "done": "result", "failed": "failed"}


class IntakeError(Exception):
    """A call the intake refuses. `status` is the HTTP status it maps to."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _key_file(path: Path | str | None) -> Path:
    return Path(path or os.environ.get("VASPFUSION_SAHYOG_KEY_FILE") or DEFAULT_KEY_FILE)


def configured_key(path: Path | str | None = None) -> str | None:
    """The key the portal must present: SAHYOG_API_KEY, else the key file the demo set-up
    wrote. None = the intake is not configured and answers 503."""
    env = os.environ.get("SAHYOG_API_KEY", "").strip()
    if env:
        return env
    file = _key_file(path)
    if file.is_file():
        return file.read_text().strip() or None
    return None


def check_key(given: str | None, path: Path | str | None = None) -> None:
    want = configured_key(path)
    if want is None:
        raise IntakeError(503, "The SAHYOG intake is not configured on this installation: "
                               "no API key is set (SAHYOG_API_KEY).")
    if not given or not hmac.compare_digest(given.encode(), want.encode()):
        raise IntakeError(401, f"The {KEY_HEADER} header is missing or wrong.")


def ensure_demo_key(path: Path | str | None = None) -> tuple[Path, bool]:
    """The demo set-up's key file: a random key, written once. (file, was it created)."""
    file = _key_file(path)
    if file.is_file() and file.read_text().strip():
        return file, False
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(secrets.token_urlsafe(32) + "\n")
    file.chmod(0o600)
    return file, True


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exchanges(case: dict) -> list[dict]:
    ranked = sorted(case.get("candidates") or [], key=lambda c: c["proximity_rank"])
    return [{"vasp": c["vasp"], "direction": c.get("direction", "outbound"),
             "proximity_rank": c["proximity_rank"], "hops": c["hops"],
             "confidence": c["confidence"]} for c in ranked]


def wallet_view(entry: dict, case: dict | None, requests: list[dict], risk: dict) -> dict:
    """`ComplaintWallet`: a stored wallet entry with what its case says now."""
    if not entry.get("accepted"):
        return {"address": entry["address"], "chain": entry.get("chain"), "accepted": False,
                "error": entry.get("error"), "status": "refused"}
    state = _CASE_STATE.get((case or {}).get("status"), "received")
    done = state == "result" and case.get("outcome") is not None
    return {
        "address": entry["address"], "chain": entry["chain"], "accepted": True,
        "case_id": entry["case_id"], "status": state,
        "outcome": case.get("outcome") if done else None,
        "top_vasp": case.get("top_vasp") if done else None,
        "confidence": case.get("confidence") if done else None,
        "exchanges": _exchanges(case) if done else [],
        "risk_class": risk.get("risk_class") if done else None,
        "risk_score": risk.get("risk_score") if done else None,
        "report_pdf": f"/api/cases/{entry['case_id']}/pdf" if done else None,
        "request_ids": sorted(r["id"] for r in requests if r["status"] != "withdrawn"
                              and entry["case_id"] in r["case_ids"]),
        "result_sent_at": entry.get("result_sent_at"),
        "case_error": (case or {}).get("error"),
    }


def complaint_view(complaint: dict, wallets: list[dict]) -> dict:
    """`ComplaintStatus` from the stored complaint and its wallets' views."""
    states = [w["status"] for w in wallets if w["accepted"]]
    if states and all(s in ("result", "failed") for s in states):
        status = "result"
    elif any(s != "received" for s in states):
        status = "tracing"
    else:
        status = "received"
    keep = ("complaint_ref", "agency", "officer", "category", "note", "amount_lost_inr",
            "incident_date", "callback_url", "received_at")
    return {**{k: complaint.get(k) for k in keep}, "status": status, "wallets": wallets,
            "status_url": f"/api/sahyog/complaints/{complaint['complaint_ref']}"}


def result_payload(complaint: dict, wallet: dict, *, code_version: str, now: datetime) -> dict:
    """What the gateway is handed when a wallet's trace is done (`wallet` is its
    `wallet_view`). The portal reads the same from GET /api/sahyog/complaints/{ref}."""
    return {
        "schema": RESULT_SCHEMA,
        "complaint_ref": complaint["complaint_ref"],
        "callback_url": complaint.get("callback_url"),
        "sent_at": iso(now),
        "wallet": {k: wallet.get(k) for k in (
            "address", "chain", "case_id", "status", "outcome", "top_vasp", "confidence",
            "exchanges", "risk_class", "risk_score", "report_pdf")},
        "risk_basis": RISK_BASIS,
        "generated_by": {"tool": "VASP-FUSION", "code_version": code_version},
    }
