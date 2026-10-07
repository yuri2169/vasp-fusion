"""The conformance suite, run against the tool and the reference portal as two HTTP
servers on two ports of this machine: every call below crosses a real socket, signed.

With CONFORMANCE_TOOL_URL and CONFORMANCE_PORTAL_URL set (and SAHYOG_API_KEY,
SAHYOG_SIGNING_SECRET, CONFORMANCE_WALLET, CONFORMANCE_VASP) the same checks run against
programs that are already up, for example the docker compose pair or another portal.
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conformance import checks  # noqa: E402
from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402

KEY, SECRET = "conformance-key-for-this-run", "conformance-secret-for-this-run"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Served:
    """An ASGI app on a port of this machine, in a thread, until stopped."""

    def __init__(self, app, port: int):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                                    log_level="error", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.url = f"http://127.0.0.1:{port}"

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            assert time.monotonic() < deadline, "the server did not start"
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    if os.environ.get("CONFORMANCE_TOOL_URL"):
        yield checks.Pair(tool=os.environ["CONFORMANCE_TOOL_URL"].rstrip("/"),
                          portal=os.environ["CONFORMANCE_PORTAL_URL"].rstrip("/"),
                          key=os.environ["SAHYOG_API_KEY"],
                          secret=os.environ["SAHYOG_SIGNING_SECRET"],
                          wallet=os.environ.get("CONFORMANCE_WALLET",
                                                SPECS["tron-coindcx"]["address"]),
                          vasp=os.environ.get("CONFORMANCE_VASP", "CoinDCX"))
        return
    from refportal.app import create_app
    from vaspfusion.api import main, security
    tmp = tmp_path_factory.mktemp("conformance")
    tool_port, portal_port = _free_port(), _free_port()
    mp = pytest.MonkeyPatch()
    for name, value in (("LABEL_DB", demo_label_db(tmp / "labels.duckdb")),
                        ("CASE_DB", tmp / "case.duckdb"), ("DESK_DB", tmp / "desk.duckdb"),
                        ("OUTBOX", tmp / "outbox"), ("WATCH_DB", tmp / "watch.duckdb"),
                        ("OFFICERS", tmp / "officers.json"), ("AUDIT_DB", tmp / "audit.duckdb"),
                        ("AUTH_SECRET", tmp / "auth_secret"), ("AUTH", None),
                        ("SAHYOG_KEY", tmp / "no-key"), ("SAHYOG_SECRET", tmp / "no-secret"),
                        ("make_fetcher", lambda: demo_fetcher(tmp / "cache.duckdb"))):
        mp.setattr(main, name, value)
    mp.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp / "no.env")
    for name, value in (("ETHERSCAN_API_KEY", "test-key"), ("TRONGRID_API_KEY", ""),
                        ("SAHYOG_API_KEY", KEY), ("SAHYOG_SIGNING_SECRET", SECRET),
                        ("SAHYOG_URL", f"http://127.0.0.1:{portal_port}"),
                        ("VASPFUSION_AUTH", "off")):
        mp.setenv(name, value)
    for name in ("OFFLINE", "VASPFUSION_DEMO_MODE", "VASPFUSION_WORKERS",
                 "VASPFUSION_WATCH_INTERVAL"):
        mp.delenv(name, raising=False)
    security.forget()
    portal = create_app(tool_url=f"http://127.0.0.1:{tool_port}", db=tmp / "portal.sqlite",
                        key=KEY, secret=SECRET, ui_dist=tmp / "no-ui")
    try:
        with Served(main.app, tool_port) as tool, Served(portal, portal_port) as prt:
            yield checks.Pair(tool=tool.url, portal=prt.url, key=KEY, secret=SECRET,
                              wallet=SPECS["tron-coindcx"]["address"], vasp="CoinDCX")
    finally:
        mp.undo()
        security.forget()


def test_the_portal_keeps_its_half_of_the_contract(pair):
    done = checks.portal_checks(pair)
    assert len(done) == 14, done


def test_the_tool_keeps_its_half_of_the_contract(pair):
    done = checks.tool_checks(pair)
    assert len(done) == 11, done


def test_complaint_in_trace_result_back_request_out_reply_in(pair):
    done = checks.round_trip(pair)
    assert len(done) == 11, done


def test_with_the_portal_down_a_request_stays_approved_and_says_why(pair, monkeypatch):
    """The tool's side of an outage: nothing is marked sent, and the sentence names the
    host that did not answer."""
    if os.environ.get("CONFORMANCE_TOOL_URL"):
        pytest.skip("needs to take the portal away")
    monkeypatch.setenv("SAHYOG_URL", f"http://127.0.0.1:{_free_port()}")
    monkeypatch.setenv("SAHYOG_TRIES", "2")
    monkeypatch.setattr("vaspfusion.desk.gateway.time.sleep", lambda s: None)
    t, wallet = pair.tool, SPECS["tron-htx-coindcx"]["address"]
    s, case = checks.http("POST", t + "/api/cases", checks.canonical({"address": wallet}))
    assert s == 202, case
    deadline = time.monotonic() + 60
    while checks.http("GET", f"{t}/api/cases/{case['id']}")[1].get("status") != "done":
        assert time.monotonic() < deadline
        time.sleep(0.2)
    s, req = checks.http("POST", t + "/api/requests", checks.canonical({
        "vasp": "CoinDCX", "case_ids": [case["id"]], "asks": ["kyc"], "officer": "A. Tester"}))
    assert s == 201, req
    checks.http("PATCH", f"{t}/api/requests/{req['id']}", checks.canonical({"status": "approved"}))
    s, body = checks.http("PATCH", f"{t}/api/requests/{req['id']}",
                          checks.canonical({"status": "sent"}))
    assert s == 502 and "could not be reached after 2 tries" in body["detail"], (s, body)
    s, after = checks.http("GET", f"{t}/api/requests/{req['id']}")
    assert after["status"] == "approved" and after.get("receipt") is None
