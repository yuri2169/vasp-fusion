"""Login and the audit log in front of the API. Real pipeline, recorded demo wallets."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion.api import main, security  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.auth import tokens  # noqa: E402
from vaspfusion.auth.officers import Officers  # noqa: E402
from vaspfusion.store.audit import AuditLog  # noqa: E402

COINDCX = SPECS["tron-coindcx"]["address"]
PASSWORD = "a long demo password"
OPEN = ("/api/health", "/api/auth/me")
GUARDED = ("/api/cases", "/api/cases/demo-tron-okx", "/api/cases/demo-tron-okx/pdf",
           "/api/cases/demo-tron-okx.pdf", "/api/labels/search?q=okx", "/api/desk",
           "/api/vasps/OKX", "/api/dashboard", "/api/model", "/api/audit",
           "/api/requests/demo-req-okx-001", "/api/wallets/tron/" + COINDCX)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "make_fetcher", lambda: demo_fetcher(tmp_path / "cache.duckdb"))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    return TestClient(main.app)


@pytest.fixture
def officer(client):
    """One officer exists, so login is required."""
    return Officers(main.OFFICERS).add("a.rao", "Insp. A. Rao", PASSWORD, post="Cyber Crime PS")


def sign_in(client, username="a.rao", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def audit():
    return AuditLog(main.AUDIT_DB).list(limit=500)[1][::-1]          # oldest first


# ------------------------------------------------------------------ no officer: as before
def test_with_no_officer_nothing_asks_for_a_login(client):
    for path in OPEN + GUARDED:
        assert client.get(path).status_code == 200, path
    me = client.get("/api/auth/me").json()
    assert me == {"auth_required": False, "officer": None}
    assert client.get("/api/health").json()["auth_required"] is False


def test_with_no_login_the_log_still_says_what_was_looked_at(client):
    client.get("/api/cases/demo-tron-okx")
    client.get("/api/labels/search?q=okx")
    rows = audit()
    assert [(r["officer"], r["action"], r["target"]) for r in rows] == \
        [(None, "case.view", "demo-tron-okx"), (None, "label.search", "okx")]


# ------------------------------------------------------------------ an officer exists
def test_every_route_answers_401_until_signed_in(client, officer):
    for path in GUARDED:
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json() == {"detail": "Sign in to continue."}
        assert r.headers["www-authenticate"] == "Bearer"
    assert client.post("/api/cases", json={"address": COINDCX}).status_code == 401
    assert client.post("/api/cases/x/verify").status_code == 401
    assert client.patch("/api/requests/x", json={"status": "approved"}).status_code == 401
    for path in OPEN:
        assert client.get(path).status_code == 200, path
    assert client.get("/api/auth/me").json() == {"auth_required": True, "officer": None}
    assert client.get("/api/health").json()["auth_required"] is True


def test_signing_in_gives_a_token_and_a_session_cookie(client, officer):
    r = sign_in(client)
    assert r.status_code == 200
    body = r.json()
    S.LoginResult.model_validate(body)
    assert body["officer"] == {"username": "a.rao", "name": "Insp. A. Rao",
                               "post": "Cyber Crime PS"}
    assert body["token_type"] == "bearer"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{security.SESSION_COOKIE}=") and "HttpOnly" in cookie
    assert "SameSite=strict" in cookie and "Path=/api" in cookie
    # the cookie alone is enough (a PDF opened in a new tab cannot send a header)
    assert client.get("/api/cases").status_code == 200
    assert client.get("/api/auth/me").json()["officer"]["username"] == "a.rao"


def test_a_bearer_token_alone_is_enough(client, officer):
    token = sign_in(client).json()["token"]
    client.cookies.clear()
    assert client.get("/api/cases").status_code == 401
    r = client.get("/api/cases", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


@pytest.mark.parametrize("header", ["Bearer nonsense", "Bearer a.b.c", "Basic YTpi", "Bearer "])
def test_a_bad_token_is_a_401_not_an_error(client, officer, header):
    assert client.get("/api/cases", headers={"Authorization": header}).status_code == 401


def test_a_token_signed_elsewhere_is_refused(client, officer):
    forged = tokens.issue({"sub": "a.rao"}, b"z" * 32)
    assert client.get("/api/cases",
                      headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_a_token_stops_working_when_the_officer_is_disabled(client, officer, monkeypatch):
    token = sign_in(client).json()["token"]
    Officers(main.OFFICERS).disable("a.rao")
    client.cookies.clear()
    # nobody is left who could sign in, but the mode stays "required" once set
    monkeypatch.setattr(main, "AUTH", "required")
    assert client.get("/api/cases",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_wrong_password_is_401_and_logged_without_the_password(client, officer):
    r = sign_in(client, password="not the password")
    assert r.status_code == 401 and r.json() == {"detail": "Wrong user name or password."}
    assert "set-cookie" not in r.headers
    assert sign_in(client, username="nobody").json() == r.json()       # same words either way
    rows = audit()
    assert [(r["action"], r["target"], r["status"]) for r in rows] == \
        [("auth.login", "a.rao", 401), ("auth.login", "(unknown user name)", 401)]
    assert "not the password" not in json.dumps(rows) and PASSWORD not in json.dumps(rows)


def test_too_many_wrong_passwords_is_429(client, officer):
    for _ in range(5):
        sign_in(client, password="not the password")
    r = sign_in(client)
    assert r.status_code == 429 and "Try again in 5 minutes" in r.json()["detail"]


def test_signing_out_clears_the_cookie(client, officer):
    sign_in(client)
    r = client.post("/api/auth/logout")
    assert r.status_code == 200 and security.SESSION_COOKIE in r.headers["set-cookie"]
    client.cookies.clear()
    assert client.get("/api/cases").status_code == 401


def test_forcing_login_off_and_on(client, officer, monkeypatch):
    monkeypatch.setenv("VASPFUSION_AUTH", "off")
    assert client.get("/api/cases").status_code == 200
    monkeypatch.setenv("VASPFUSION_AUTH", "required")
    assert client.get("/api/cases").status_code == 401


# ------------------------------------------------------------------ the audit trail
def test_opening_a_case_logs_who_which_wallet_and_when(client, officer):
    sign_in(client)
    cid = client.post("/api/cases", json={"address": COINDCX, "case_ref": "FIR 12/2026"}).json()["id"]
    client.get(f"/api/cases/{cid}")
    client.get(f"/api/cases/{cid}/pdf")
    client.get(f"/api/cases/{cid}/receipt")
    client.post(f"/api/cases/{cid}/verify")
    client.get(f"/api/wallets/tron/{COINDCX}")
    rows = audit()
    assert [(r["officer"], r["action"], r["target"], r["status"]) for r in rows] == [
        (None, "auth.login", "a.rao", 200),
        ("a.rao", "case.open", cid, 202),
        ("a.rao", "case.view", cid, 200),
        ("a.rao", "case.export", cid, 200),
        ("a.rao", "case.receipt", cid, 200),
        ("a.rao", "case.verify", cid, 200),
        ("a.rao", "wallet.view", f"tron:{COINDCX}", 200)]
    opened = rows[1]
    assert opened["detail"] == {"address": COINDCX, "chain": "tron"}
    assert opened["at"].endswith("Z") and opened["method"] == "POST"
    assert "FIR 12/2026" not in json.dumps(rows)              # no request body in the log
    assert AuditLog(main.AUDIT_DB).verify_chain()["ok"] is True


def test_a_refused_request_is_logged_too(client, officer):
    client.get("/api/cases/demo-tron-okx")
    row = audit()[-1]
    assert (row["officer"], row["action"], row["target"], row["status"]) == \
        (None, "case.view", "demo-tron-okx", 401)


def test_the_same_view_twice_within_30_seconds_is_one_row(client, officer, monkeypatch):
    sign_in(client)
    clock = {"t": 1000.0}
    monkeypatch.setattr(security, "_now", lambda: clock["t"])
    for _ in range(4):                                   # the page polls while a trace runs
        client.get("/api/cases/demo-tron-okx")
    assert [r["action"] for r in audit()].count("case.view") == 1
    clock["t"] += 31
    client.get("/api/cases/demo-tron-okx")
    assert [r["action"] for r in audit()].count("case.view") == 2


def test_writes_are_never_folded(client, officer):
    sign_in(client)
    for _ in range(2):
        client.post("/api/cases", json={"address": COINDCX})
    assert [r["action"] for r in audit()].count("case.open") == 2


def test_health_and_whoami_are_not_logged(client, officer):
    client.get("/api/health")
    client.get("/api/auth/me")
    assert audit() == []


def test_a_request_records_who_drafted_and_who_approved_it(client, officer):
    sign_in(client)
    cid = client.post("/api/cases", json={"address": COINDCX}).json()["id"]
    r = client.post("/api/requests", json={"vasp": "CoinDCX", "case_ids": [cid],
                                           "asks": ["kyc"], "officer": "Insp. A. Rao"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["status_history"][0]["by"] == "a.rao"
    r = client.patch(f"/api/requests/{rid}", json={"status": "approved", "note": "ok"})
    assert r.json()["status_history"][-1]["by"] == "a.rao"
    rows = [r for r in audit() if r["action"].startswith("request.")]
    assert [(r["action"], r["target"], r["status"]) for r in rows] == \
        [("request.draft", rid, 201), ("request.status", rid, 200)]
    assert rows[0]["detail"] == {"vasp": "CoinDCX", "cases": [cid]}
    assert rows[1]["detail"] == {"status": "approved"}


def test_without_a_login_a_request_has_no_by(client):
    cid = client.post("/api/cases", json={"address": COINDCX}).json()["id"]
    r = client.post("/api/requests", json={"vasp": "CoinDCX", "case_ids": [cid],
                                           "asks": ["kyc"], "officer": "Insp. A. Rao"})
    assert r.json()["status_history"][0].get("by") is None


def test_the_log_is_served_newest_first_with_its_chain_check(client, officer):
    sign_in(client)
    client.get("/api/cases/demo-tron-okx")
    client.get("/api/labels/search?q=okx")
    r = client.get("/api/audit?verify=true")
    assert r.status_code == 200
    page = r.json()
    S.AuditPage.model_validate(page)
    assert [i["action"] for i in page["items"]] == ["label.search", "case.view", "auth.login"]
    assert page["total"] == 3 and page["chain"]["ok"] is True and page["chain"]["rows"] == 3
    only = client.get("/api/audit?target=demo-tron-okx").json()
    assert [i["action"] for i in only["items"]] == ["case.view"] and only["chain"] is None
    assert client.get("/api/audit?action=case").json()["total"] == 1


def test_a_failed_audit_write_refuses_the_reply(client, officer, monkeypatch):
    sign_in(client)

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(security, "write_row", broken)
    r = client.get("/api/cases/demo-tron-okx")
    assert r.status_code == 503 and "audit log" in r.json()["detail"]


# ------------------------------------------------------------------ headers, cross-origin
def test_api_replies_are_not_cached_or_sniffed(client):
    r = client.get("/api/cases")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_a_cross_origin_write_is_still_refused_and_logged(client, officer):
    sign_in(client)
    r = client.post("/api/cases", json={"address": COINDCX},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert audit()[-1]["status"] == 403 and audit()[-1]["action"] == "case.open"


def test_a_cross_origin_login_is_refused(client, officer):
    r = client.post("/api/auth/login", json={"username": "a.rao", "password": PASSWORD},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and "set-cookie" not in r.headers


# ------------------------------------------------------------------ from the code review
def test_a_password_typed_into_the_user_name_box_is_not_logged(client, officer):
    sign_in(client, username=PASSWORD.replace(" ", "-"), password="x")
    sign_in(client, username="vasp-fusion-demo-2026", password="x")     # looks like a user name
    assert [r["target"] for r in audit()] == ["(unknown user name)"] * 2


def test_disabling_the_only_officer_does_not_open_the_tool(client, officer):
    Officers(main.OFFICERS).disable("a.rao")
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/auth/me").json()["auth_required"] is True
    assert sign_in(client).status_code == 401


def test_a_request_is_logged_once_the_log_can_be_written_again(client, officer, monkeypatch):
    """The failed row must not be remembered as written: the next read is logged."""
    sign_in(client)
    real, calls = security.write_row, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk full")
        return real(*a, **k)
    monkeypatch.setattr(security, "write_row", flaky)
    assert client.get("/api/cases/demo-tron-okx").status_code == 503
    assert client.get("/api/cases/demo-tron-okx").status_code == 200
    assert [r["action"] for r in audit()].count("case.view") == 1 and len(calls) == 2


def test_a_request_that_breaks_the_server_is_logged_as_a_500(client, officer, monkeypatch):
    sign_in(client)

    def broken():
        raise RuntimeError("the case store is gone")
    monkeypatch.setattr(main, "_cases", broken)
    r = client.get("/api/cases")
    assert r.status_code == 500 and "logged" in r.json()["detail"]
    assert "case store is gone" not in r.text                       # no internals in the reply
    row = audit()[-1]
    assert (row["officer"], row["action"], row["status"]) == ("a.rao", "case.list", 500)


@pytest.mark.parametrize("token", [b"a.b.\xe9", b"a.b." + b"c" * 9000, b"\xe9.\xe9.\xe9"])
def test_a_hostile_token_is_a_401_and_a_log_row_not_a_500(client, officer, token):
    r = client.get("/api/cases", headers={"Authorization": b"Bearer " + token})
    assert r.status_code == 401
    assert (audit()[-1]["action"], audit()[-1]["status"]) == ("case.list", 401)


def test_reads_from_two_addresses_are_two_rows_when_nobody_is_signed_in(client, monkeypatch):
    seen = iter(["10.0.0.1", "10.0.0.2", "10.0.0.2"])

    class Client:
        @property
        def host(self):
            return next(seen)
    monkeypatch.setattr("starlette.requests.HTTPConnection.client", Client())
    for _ in range(3):
        client.get("/api/cases/demo-tron-okx")
    assert [r["client"] for r in audit()] == ["10.0.0.1", "10.0.0.2"]
