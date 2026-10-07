"""The HTTP gateway against a scripted portal: what it sends, how it retries, and what
it says when the portal cannot be reached. No socket is opened here; the two programs
talking over real sockets is tests/conformance/."""
import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest

from vaspfusion.desk import signing
from vaspfusion.desk.gateway import (GatewayError, HttpSahyogGateway, MockSahyogGateway,
                                     canonical, gateway_from_env)

NOW = datetime(2026, 10, 8, 6, 0, 0, tzinfo=timezone.utc)
KEY, SECRET = "key-for-this-test", "secret-for-this-test"
PAYLOAD = {"schema": "vaspfusion-sahyog-request/1", "request_id": "req-2026-0001",
           "draft": False, "recipient": {"vasp": "CoinDCX"}, "asks": ["kyc", "freeze"],
           "wallets": []}
PDF = b"%PDF-1.4 the letter"
DIGEST = hashlib.sha256(canonical(PAYLOAD)).hexdigest()


class Portal:
    """Answers from a script; remembers every call."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def send(self, method, url, body, headers, timeout=None):
        self.calls.append({"method": method, "url": url, "body": body or b"",
                           "headers": headers, "timeout": timeout})
        status, answer = self.answers.pop(0) if self.answers else (200, None)
        if answer is None:
            answer = {"receipt_id": "rp-1", "payload_sha256": DIGEST}
        return status, answer if isinstance(answer, bytes) else json.dumps(answer).encode()


def gateway(tmp_path, portal, url="https://portal.example/sahyog", **over):
    waits = []
    args = dict(journal=MockSahyogGateway(tmp_path / "outbox"), transport=portal,
                sleep=waits.append, clock=lambda: NOW)
    args.update(over)
    g = HttpSahyogGateway(url, KEY, SECRET, **args)
    g.waits = waits
    return g


def test_a_request_is_posted_signed_with_its_letter_and_an_idempotency_key(tmp_path):
    portal = Portal()
    g = gateway(tmp_path, portal)
    receipt = g.submit(PAYLOAD, PDF, now=NOW)
    call, = portal.calls
    assert (call["method"], call["url"]) == ("POST", "https://portal.example/sahyog/v1/requests")
    sent = json.loads(call["body"])
    assert sent["payload"] == PAYLOAD and base64.b64decode(sent["letter_pdf_b64"]) == PDF
    h = {k.lower(): v for k, v in call["headers"].items()}
    assert h["x-sahyog-key"] == KEY and SECRET not in json.dumps(call["headers"])
    # the portal can verify it: the signature covers the path under the base URL and the body
    assert signing.verify(SECRET, h, "POST", "/sahyog/v1/requests", call["body"], now=NOW)
    assert h["idempotency-key"] == f"request:req-2026-0001:{DIGEST[:16]}"
    assert receipt == {"gateway": "sahyog-http", "receipt_id": "rp-1",
                       "submitted_at": "2026-10-08T06:00:00Z", "payload_sha256": DIGEST,
                       "location": "portal.example/sahyog/v1/requests/req-2026-0001"}
    assert g.sent_pdf("req-2026-0001") == PDF            # the local copy of what was sent


def test_a_portal_that_does_not_answer_is_tried_again_with_a_pause_and_a_fresh_signature(
        tmp_path):
    portal = Portal((599, b"connection refused"), (503, b""), (200, None))
    g = gateway(tmp_path, portal)
    assert g.submit(PAYLOAD, PDF, now=NOW)["receipt_id"] == "rp-1"
    assert g.waits == [0.5, 1.0]
    nonces = {c["headers"]["X-SAHYOG-Nonce"] for c in portal.calls}
    keys = {c["headers"]["Idempotency-Key"] for c in portal.calls}
    assert len(nonces) == 3 and len(keys) == 1


def test_when_the_tries_run_out_the_error_names_the_host_and_nothing_is_kept(tmp_path):
    portal = Portal((599, b"connection refused"), (599, b"connection refused"),
                    (599, b"timed out"))
    g = gateway(tmp_path, portal)
    with pytest.raises(GatewayError, match=r"portal\.example could not be reached after 3 "
                                           r"tries: no answer \(timed out\)"):
        g.submit(PAYLOAD, PDF, now=NOW)
    assert len(portal.calls) == 3 and g.sent_pdf("req-2026-0001") is None
    assert all(c["timeout"] == 10.0 for c in portal.calls)


def test_a_refusal_is_not_retried_and_says_what_the_portal_said(tmp_path):
    portal = Portal((409, {"detail": "req-2026-0001 is already held with different contents"}))
    g = gateway(tmp_path, portal)
    with pytest.raises(GatewayError, match=r"refused the call \(HTTP 409\): req-2026-0001 is "
                                           "already held"):
        g.submit(PAYLOAD, PDF, now=NOW)
    assert len(portal.calls) == 1


def test_a_receipt_for_another_payload_is_not_accepted(tmp_path):
    g = gateway(tmp_path, Portal((200, {"receipt_id": "rp-9", "payload_sha256": "0" * 64})))
    with pytest.raises(GatewayError, match="acknowledged a different payload"):
        g.submit(PAYLOAD, PDF, now=NOW)
    assert g.sent_pdf("req-2026-0001") is None


def test_a_draft_never_leaves(tmp_path):
    portal = Portal()
    with pytest.raises(GatewayError, match="draft"):
        gateway(tmp_path, portal).submit({**PAYLOAD, "draft": True}, PDF, now=NOW)
    assert portal.calls == []


@pytest.mark.parametrize("url, over, said", [
    ("http://portal.example", {}, "is not https"),
    ("ftp://portal.example", {}, "not an http"),
    ("https://portal.example", {"key": None}, "no API key"),
    ("https://portal.example", {"secret": None}, "no signing secret"),
])
def test_a_gateway_that_is_not_configured_sends_nothing_and_says_why(tmp_path, url, over, said):
    portal = Portal()
    g = HttpSahyogGateway(url, over.get("key", KEY), over.get("secret", SECRET),
                          journal=MockSahyogGateway(tmp_path / "o"), transport=portal)
    with pytest.raises(GatewayError, match=said):
        g.submit(PAYLOAD, PDF, now=NOW)
    assert portal.calls == []


def test_plain_http_is_accepted_on_this_machine_or_when_asked_for(tmp_path):
    for url, allow in (("http://127.0.0.1:8100", False), ("http://portal:8100", True)):
        g = gateway(tmp_path, Portal(), url=url, allow_http=allow)
        assert g.submit(PAYLOAD, PDF, now=NOW)["gateway"] == "sahyog-http"


def test_a_result_is_posted_signed_and_a_reply_is_kept_as_it_arrived(tmp_path):
    result = {"schema": "vaspfusion-sahyog-result/1", "complaint_ref": "NCRP-1",
              "wallet": {"case_id": "c-1", "status": "result"}}
    digest = hashlib.sha256(canonical(result)).hexdigest()
    portal = Portal((200, None), (200, {"receipt_id": "rp-2", "payload_sha256": digest}))
    g = gateway(tmp_path, portal)
    g.submit(PAYLOAD, PDF, now=NOW)
    receipt = g.notify_result(result, now=NOW)
    assert portal.calls[1]["url"].endswith("/v1/results")
    assert portal.calls[1]["body"] == canonical(result)
    assert receipt["receipt_id"] == "rp-2"
    kept = g.record_reply("req-2026-0001", {"status": "freeze_confirmed"}, now=NOW)
    assert kept["gateway"] == "sahyog-http" and len(portal.calls) == 2
    assert (tmp_path / "outbox" / "replies" / "req-2026-0001.freeze_confirmed.json").exists()


def test_the_gateway_is_chosen_by_configuration(tmp_path, monkeypatch):
    for name in ("SAHYOG_URL", "SAHYOG_API_KEY", "SAHYOG_SIGNING_SECRET", "SAHYOG_ALLOW_HTTP"):
        monkeypatch.delenv(name, raising=False)
    files = (tmp_path / "o", tmp_path / "k", tmp_path / "s")
    assert gateway_from_env(*files).name == "mock-outbox"
    monkeypatch.setenv("SAHYOG_URL", "https://portal.example")
    g = gateway_from_env(*files)
    assert g.name == "sahyog-http" and "no API key" in g.problem
    monkeypatch.setenv("SAHYOG_API_KEY", KEY)
    monkeypatch.setenv("SAHYOG_SIGNING_SECRET", SECRET)
    assert gateway_from_env(*files).problem is None
