"""Signed SAHYOG calls: what is signed, and what a receiver refuses. The reference
portal has its own implementation of the same scheme (refportal/signing.py); the fixed
vector below is in docs/sahyog_contract.md and both must produce it."""
from datetime import datetime, timedelta, timezone

import pytest

from vaspfusion.desk import signing
from vaspfusion.store.nonces import NonceStore

NOW = datetime(2026, 10, 8, 6, 0, 0, tzinfo=timezone.utc)
SECRET = "a-secret-for-this-test-only"
BODY = b'{"complaint_ref":"NCRP-2026-0001"}'


def _lower(h: dict) -> dict:
    return {k.lower(): v for k, v in h.items()}


def signed(**over):
    h = signing.headers("key", SECRET, "POST", "/api/sahyog/complaints", BODY, now=NOW,
                        nonce="n" * 24)
    return _lower({**h, **over})


def test_the_signature_is_the_documented_hmac():
    import hashlib
    import hmac
    text = "v1\n1791439200\n" + "n" * 24 + "\nPOST\n/api/sahyog/complaints\n" \
        + hashlib.sha256(BODY).hexdigest()
    want = hmac.new(SECRET.encode(), text.encode(), hashlib.sha256).hexdigest()
    assert int(NOW.timestamp()) == 1791439200
    assert signing.sign(SECRET, "1791439200", "n" * 24, "post", "/api/sahyog/complaints",
                        BODY) == want
    assert signed()["x-sahyog-signature"] == f"v1={want}"


def test_the_reference_portal_signs_the_same_way():
    from refportal import signing as theirs
    args = (SECRET, "1791439200", "n" * 24, "POST", "/v1/requests", BODY)
    assert theirs.sign(*args) == signing.sign(*args)


def test_a_signed_call_verifies_and_gives_its_nonce():
    assert signing.verify(SECRET, signed(), "POST", "/api/sahyog/complaints", BODY,
                          now=NOW + timedelta(seconds=200)) == "n" * 24


@pytest.mark.parametrize("change, said", [
    (dict(method="GET"), "does not match"),
    (dict(path="/api/sahyog/complaints/other"), "does not match"),
    (dict(body=BODY + b" "), "does not match"),
    (dict(secret="another secret"), "does not match"),
    (dict(now=NOW + timedelta(seconds=301)), "more than 300 seconds"),
    (dict(now=NOW - timedelta(seconds=301)), "more than 300 seconds"),
])
def test_a_call_that_is_not_what_was_signed_is_refused(change, said):
    args = dict(secret=SECRET, method="POST", path="/api/sahyog/complaints", body=BODY, now=NOW)
    args.update(change)
    with pytest.raises(signing.SignatureError, match=said) as e:
        signing.verify(args["secret"], signed(), args["method"], args["path"], args["body"],
                       now=args["now"])
    assert e.value.status == 401


@pytest.mark.parametrize("missing", ["x-sahyog-timestamp", "x-sahyog-nonce",
                                     "x-sahyog-signature"])
def test_an_unsigned_call_is_refused(missing):
    h = signed()
    del h[missing]
    with pytest.raises(signing.SignatureError, match="not signed"):
        signing.verify(SECRET, h, "POST", "/api/sahyog/complaints", BODY, now=NOW)


def test_a_nonce_is_good_once_and_forgotten_after_its_time(tmp_path):
    store = NonceStore(tmp_path / "desk.duckdb")
    assert store.claim("a" * 24, NOW) is True
    assert store.claim("a" * 24, NOW + timedelta(seconds=5)) is False
    assert store.claim("b" * 24, NOW) is True
    assert store.claim("a" * 24, NOW + timedelta(seconds=2000)) is True
