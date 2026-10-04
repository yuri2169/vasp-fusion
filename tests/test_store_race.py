"""A read at the same moment as other connections open and close (U2 found
`GET /api/cases/{id}` answering 500 about once in 12 during a refresh).

The cause, reproduced here: while one connection to a DuckDB file is being closed in a
thread, `duckdb.connect()` to the same file in another thread can raise
`BinderException: Unique file handle conflict ... already attached`. The stores only
waited on a file lock (`IOException`), so the read failed instead of waiting."""
import threading

import duckdb
import pytest

from vaspfusion.store import connect as connect_mod
from vaspfusion.store.cases import CaseStore
from vaspfusion.store.connect import connect


def _case(i: int) -> dict:
    return {"id": f"c-{i}", "address": f"a{i}", "chain": "tron", "status": "done",
            "outcome": None, "created_at": "2026-10-01T00:00:00Z", "pad": "x" * 20000,
            "graph": {"nodes": [{"id": f"w{k}", "chain": "tron", "role": "hop", "hop": 1}
                                for k in range(40)]}}


def test_reads_beside_a_writer_never_fail(tmp_path):
    path = tmp_path / "case.duckdb"
    store = CaseStore(path)
    for i in range(4):
        store.save(_case(i))
    errors: list[str] = []
    done = threading.Event()

    def writer():
        while not done.is_set():
            for i in range(4):
                try:
                    store.save(_case(i))
                except Exception as e:      # noqa: BLE001 - the test reports every failure
                    errors.append(f"write {type(e).__name__}: {e}")

    def reader():
        for _ in range(120):
            try:
                assert CaseStore(path).get("c-1")["id"] == "c-1"
                assert len(store.list()) == 4
                assert store.find("tron", "a2")["id"] == "c-2"
                assert store.wallet_cases("w3", "tron")
            except Exception as e:          # noqa: BLE001
                errors.append(f"read {type(e).__name__}: {e}")

    w = threading.Thread(target=writer)
    readers = [threading.Thread(target=reader) for _ in range(6)]
    w.start()
    for t in readers:
        t.start()
    for t in readers:
        t.join()
    done.set()
    w.join()
    assert errors == [], errors[:3]


def test_connect_waits_out_a_handle_conflict_and_gives_up_after_the_deadline(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = duckdb.connect

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 4:
            raise duckdb.BinderException('Binder Error: Unique file handle conflict: Cannot '
                                         'attach "case" - the database file is already attached')
        return real(*a, **k)

    monkeypatch.setattr(connect_mod.duckdb, "connect", flaky)
    connect(tmp_path / "x.duckdb").close()
    assert calls["n"] == 4

    def never(*a, **k):
        raise duckdb.BinderException("Binder Error: Unique file handle conflict")

    monkeypatch.setattr(connect_mod.duckdb, "connect", never)
    with pytest.raises(duckdb.BinderException):
        connect(tmp_path / "x.duckdb", wait_s=0.2)


def test_connect_does_not_swallow_other_errors(tmp_path, monkeypatch):
    def broken(*a, **k):
        raise duckdb.BinderException("Binder Error: something else entirely")

    monkeypatch.setattr(connect_mod.duckdb, "connect", broken)
    with pytest.raises(duckdb.BinderException, match="something else"):
        connect(tmp_path / "x.duckdb")
