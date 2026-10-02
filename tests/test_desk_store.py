"""Requests in DuckDB: a request is stored whole, numbered once, listed newest first."""
from vaspfusion.store.requests import RequestStore


def _req(store, vasp="CoinDCX", created="2026-10-02T09:30:00Z"):
    rid, ref = store.next_id(2026)
    req = {"id": rid, "reference": ref, "vasp": vasp, "status": "drafted",
           "case_ids": ["tron-coindcx"], "created_at": created, "due": None,
           "status_history": [], "letter": {"wallets": []}, "payload": {}}
    store.save(req)
    return req


def test_a_request_round_trips_and_is_listed_newest_first(tmp_path):
    store = RequestStore(tmp_path / "desk.duckdb")
    a = _req(store)
    b = _req(store, vasp="HTX", created="2026-10-02T10:00:00Z")
    assert (a["id"], a["reference"]) == ("req-2026-0001", "VF/REQ/2026/0001")
    assert b["id"] == "req-2026-0002"
    assert store.get(a["id"]) == a and store.get("nope") is None
    assert [r["id"] for r in store.list()] == [b["id"], a["id"]]
    assert [r["id"] for r in store.list(vasp="CoinDCX")] == [a["id"]]


def test_saving_again_replaces_the_request(tmp_path):
    store = RequestStore(tmp_path / "desk.duckdb")
    a = _req(store)
    store.save({**a, "status": "approved"})
    assert store.get(a["id"])["status"] == "approved" and len(store.list()) == 1


def test_numbers_restart_each_year_and_are_never_reused(tmp_path):
    path = tmp_path / "desk.duckdb"
    store = RequestStore(path)
    _req(store)
    assert RequestStore(path).next_id(2026) == ("req-2026-0002", "VF/REQ/2026/0002")
    assert store.next_id(2026) == ("req-2026-0003", "VF/REQ/2026/0003")   # a number is spent
    assert store.next_id(2027) == ("req-2027-0001", "VF/REQ/2027/0001")
