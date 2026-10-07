"""The reference portal by itself: it is a separate program with its own store and its
own signing code, and it never passes for the real portal. The two programs talking is
tests/conformance/."""
import base64
import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from refportal import NOTICE, signing
from refportal.app import canonical, create_app

ROOT = Path(__file__).resolve().parents[2]
KEY, SECRET = "portal-test-key", "portal-test-secret"


@pytest.fixture
def portal(tmp_path):
    # the tool is not running: port 9 answers nobody
    app = create_app(tool_url="http://127.0.0.1:9", db=tmp_path / "portal.sqlite", key=KEY,
                     secret=SECRET, ui_dist=tmp_path / "no-ui")
    return TestClient(app)


def post(portal, path, payload):
    raw = canonical(payload)
    return portal.post(path, content=raw, headers={
        **signing.signed_headers(KEY, SECRET, "POST", path, raw),
        "Content-Type": "application/json"})


def request(rid="req-2026-0001"):
    letter = b"%PDF-1.4 letter"
    return {"payload": {"request_id": rid, "draft": False, "reference": "VF/REQ/2026/0001",
                        "recipient": {"vasp": "CoinDCX"}, "asks": ["kyc", "freeze"],
                        "wallets": [{}, {}],
                        "documents": [{"sha256": hashlib.sha256(letter).hexdigest()}]},
            "letter_pdf_b64": base64.b64encode(letter).decode()}


def test_it_shares_no_code_with_the_tool():
    import re
    for file in (ROOT / "refportal").glob("*.py"):
        imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", file.read_text(), re.M)
        assert not [m for m in imports if m.split(".")[0] == "vaspfusion"], file.name


def test_it_says_everywhere_that_it_is_a_simulator(portal):
    assert NOTICE == "A simulator for demonstration. Not the SAHYOG portal."
    assert portal.get("/api/health").json() == {"service": "reference-portal", "notice": NOTICE}
    assert portal.get("/api/sahyog-sim").json()["notice"] == NOTICE
    assert NOTICE in portal.get("/").text          # no interface build: a plain page says so


def test_a_received_request_is_shown_with_the_replies_that_can_follow(portal):
    assert post(portal, "/v1/requests", request()).status_code == 200
    held, = portal.get("/api/sahyog-sim").json()["requests"]
    assert held == {"id": "req-2026-0001", "reference": "VF/REQ/2026/0001", "vasp": "CoinDCX",
                    "status": "sent", "asks": ["kyc", "freeze"], "wallets": 2,
                    "sent_at": held["sent_at"], "last_note": None,
                    "allowed_replies": ["acknowledged", "answered", "freeze_confirmed",
                                        "refused"]}
    assert portal.get("/api/sahyog-sim/requests/req-2026-0001/letter").content \
        == b"%PDF-1.4 letter"


def test_when_the_tool_does_not_answer_a_complaint_is_not_kept_and_the_screen_says_why(portal):
    r = portal.post("/api/sahyog-sim/complaints", json={
        "complaint_ref": "NCRP-1", "agency": "a", "officer": "o",
        "wallets": [{"address": "TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c"}]})
    assert r.status_code == 502 and "did not answer" in r.json()["detail"]
    assert portal.get("/api/sahyog-sim").json()["complaints"] == []
    r = portal.post("/api/sahyog-sim/requests/req-2026-0404/reply", json={"status": "answered"})
    assert r.status_code == 404


def test_a_write_from_another_site_is_refused(portal):
    r = portal.post("/api/sahyog-sim/complaints", json={"complaint_ref": "NCRP-2"},
                    headers={"Origin": "https://elsewhere.example"})
    assert r.status_code == 403


def test_without_credentials_it_takes_nothing(tmp_path, monkeypatch):
    for name in ("SAHYOG_API_KEY", "SAHYOG_SIGNING_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PORTAL_KEY_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("PORTAL_SECRET_FILE", str(tmp_path / "none"))
    bare = TestClient(create_app(tool_url="http://127.0.0.1:9", db=tmp_path / "p.sqlite",
                                 ui_dist=tmp_path / "no-ui"))
    assert bare.get("/v1/health").status_code == 503
    screen = bare.get("/api/sahyog-sim").json()
    assert screen["enabled"] is False and "no credentials" in screen["why_disabled"]


def test_the_interface_it_serves_is_marked_so_only_the_simulator_is_shown(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html><head><title>t</title></head>"
                                     "<body><div id=\"root\"></div></body></html>")
    app = create_app(tool_url="http://127.0.0.1:9", db=tmp_path / "p.sqlite", key=KEY,
                     secret=SECRET, ui_dist=dist)
    page = TestClient(app).get("/sahyog-sim").text
    assert '<meta name="vf-portal"' in page and 'id="root"' in page


def test_an_old_nonce_is_forgotten_and_a_fresh_one_is_good_once(tmp_path):
    from refportal.store import Store
    store = Store(tmp_path / "p.sqlite")
    assert store.claim_nonce("a" * 20) and not store.claim_nonce("a" * 20)
    time.sleep(0.01)
    assert store.claim_nonce("b" * 20, keep_s=0) and store.claim_nonce("a" * 20)
