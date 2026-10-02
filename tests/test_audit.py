"""The audit log: append-only, hash-chained."""
import threading
from datetime import datetime, timezone

import duckdb
import pytest

from vaspfusion.store.audit import GENESIS, AuditLog, row_hash

T0 = datetime(2026, 10, 2, 9, 0, 0, 123000, tzinfo=timezone.utc)


def view(log, officer="a.rao", action="case.view", target="c-1", **kw):
    return log.append(officer=officer, action=action, target=target, method="GET",
                      path=f"/api/cases/{target}", status=200, **kw)


@pytest.fixture
def log(tmp_path):
    log = AuditLog(tmp_path / "audit.duckdb")
    view(log, at=T0)
    view(log, officer="b.sen", action="case.open", target="tron:TXYZ", client="10.0.0.7",
         detail={"case_id": "c-2"})
    view(log, action="label.search", target="okx")
    return log


def sql(log, statement, *params):
    con = duckdb.connect(str(log.path))
    con.execute(statement, list(params))
    con.close()


def test_rows_come_back_newest_first_with_who_what_and_when(log):
    total, rows = log.list()
    assert total == 3 and [r["seq"] for r in rows] == [3, 2, 1]
    first = rows[-1]
    assert (first["officer"], first["action"], first["target"], first["status"]) == \
        ("a.rao", "case.view", "c-1", 200)
    assert first["at"] == "2026-10-02T09:00:00.123Z"
    assert rows[1]["detail"] == {"case_id": "c-2"} and rows[1]["client"] == "10.0.0.7"


def test_each_row_is_chained_to_the_one_before(log):
    _, rows = log.list()
    rows.reverse()
    assert rows[0]["prev_hash"] == GENESIS
    assert rows[1]["prev_hash"] == rows[0]["hash"] and rows[2]["prev_hash"] == rows[1]["hash"]
    assert len({r["hash"] for r in rows}) == 3
    check = log.verify_chain()
    assert check["ok"] is True and check["rows"] == 3
    assert check["head"] == {"seq": 3, "hash": rows[2]["hash"], "at": rows[2]["at"]}


def test_an_empty_log_verifies(tmp_path):
    log = AuditLog(tmp_path / "a.duckdb")
    assert log.verify_chain()["ok"] is True and log.head()["seq"] == 0
    assert log.list() == (0, [])


def test_an_edited_row_is_found(log):
    sql(log, "UPDATE audit SET officer = 'someone.else' WHERE seq = 2")
    check = log.verify_chain()
    assert (check["ok"], check["broken_at"]) == (False, 2)
    assert "contents were changed" in check["reason"]


def test_an_edit_with_a_recomputed_hash_breaks_the_next_row(log):
    _, rows = log.list()
    row = {**next(r for r in rows if r["seq"] == 2), "officer": "someone.else"}
    row["detail"] = '{"case_id": "c-2"}'
    sql(log, "UPDATE audit SET officer = ?, hash = ? WHERE seq = 2", row["officer"], row_hash(row))
    check = log.verify_chain()
    assert (check["ok"], check["broken_at"]) == (False, 3)
    assert "does not follow" in check["reason"]


def test_a_removed_row_is_found(log):
    sql(log, "DELETE FROM audit WHERE seq = 2")
    check = log.verify_chain()
    assert (check["ok"], check["broken_at"]) == (False, 3) and "row 2 is missing" in check["reason"]


def test_rows_cut_off_the_end_are_caught_by_a_noted_head(log):
    noted = log.head()
    sql(log, "DELETE FROM audit WHERE seq = 3")
    assert log.verify_chain()["ok"] is True          # the chain alone cannot see it
    assert log.head() != noted                       # the head noted elsewhere can


def test_filters(log):
    assert log.list(officer="b.sen")[0] == 1
    assert [r["action"] for r in log.list(action="case")[1]] == ["case.open", "case.view"]
    assert log.list(action="case.view")[0] == 1
    assert log.list(target="okx")[1][0]["action"] == "label.search"
    assert log.list(limit=1, offset=1)[1][0]["seq"] == 2
    assert log.list(officer="nobody") == (0, [])


def test_many_writers_make_one_chain(tmp_path):
    log = AuditLog(tmp_path / "a.duckdb")

    def work(i):
        for j in range(10):
            AuditLog(log.path).append(officer=f"o{i}", action="case.view", target=f"c-{j}",
                                      method="GET", path="/api/cases/x", status=200)
    threads = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check = log.verify_chain()
    assert check["ok"] is True and check["rows"] == 60
    assert sorted(r["seq"] for r in log.list(limit=100)[1]) == list(range(1, 61))


def test_a_long_path_is_cut_not_refused(log):
    row = view(log, target="x")
    assert log.append(action="label.search", method="GET", path="/api/labels/search?q=" + "a" * 900,
                      status=200)["path"].__len__() == 500
    assert log.verify_chain()["ok"] is True and row["seq"] == 4
