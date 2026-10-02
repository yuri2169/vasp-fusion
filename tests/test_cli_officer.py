"""`cli officer` and `cli audit`."""
import io
import json
from pathlib import Path

import pytest

from vaspfusion import cli
from vaspfusion.auth.officers import Officers
from vaspfusion.store.audit import AuditLog

DEMO = json.loads((Path(__file__).resolve().parents[1] / "demo" / "officer.json").read_text())


@pytest.fixture(autouse=True)
def own_files(tmp_path, monkeypatch):
    monkeypatch.setenv("VASPFUSION_OFFICERS", str(tmp_path / "officers.json"))
    monkeypatch.setenv("VASPFUSION_AUDIT_DB", str(tmp_path / "audit.duckdb"))


def test_add_reads_the_password_from_stdin_and_never_prints_it(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a long demo password\n"))
    cli.main(["officer", "add", "a.rao", "--name", "Insp. A. Rao", "--password-stdin"])
    out = capsys.readouterr().out
    assert "added a.rao" in out and "a long demo password" not in out
    assert Officers().verify("a.rao", "a long demo password")["name"] == "Insp. A. Rao"
    cli.main(["officer", "list"])
    out = capsys.readouterr().out
    assert "a.rao" in out and "active" in out and "login required" in out


def test_a_refused_account_exits_with_the_reason(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    with pytest.raises(SystemExit) as e:
        cli.main(["officer", "add", "a.rao", "--name", "Insp. A. Rao", "--password-stdin"])
    assert e.value.code == 1 and "at least 10" in capsys.readouterr().err


def test_disable(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a long demo password\n"))
    cli.main(["officer", "add", "a.rao", "--name", "Insp. A. Rao", "--password-stdin"])
    cli.main(["officer", "disable", "a.rao"])
    cli.main(["officer", "list"])
    assert "not required" in capsys.readouterr().out
    assert Officers().verify("a.rao", "a long demo password") is None


def test_the_demo_officer_is_made_once_and_its_password_is_not_printed(capsys):
    cli.main(["officer", "demo"])
    cli.main(["officer", "demo"])                       # again: no error, no second account
    out = capsys.readouterr().out
    assert DEMO["username"] in out and DEMO["password"] not in out
    assert "demonstrations only" in out
    assert [o["username"] for o in Officers().list()] == [DEMO["username"]]
    assert Officers().verify(DEMO["username"], DEMO["password"]) is not None


def test_audit_lists_and_verifies(capsys):
    log = AuditLog()
    log.append(officer="a.rao", action="case.view", target="c-1", method="GET",
               path="/api/cases/c-1", status=200)
    log.append(action="auth.login", target="a.rao", method="POST", path="/api/auth/login",
               status=401)
    cli.main(["audit"])
    out = capsys.readouterr().out
    assert "a.rao" in out and "case.view" in out and "(not signed in)" in out and "2 of 2" in out
    cli.main(["audit", "--verify"])
    out = capsys.readouterr().out
    assert out.startswith("OK: 2 rows") and log.head()["hash"] in out


def test_audit_verify_exits_1_on_a_broken_chain(capsys):
    import duckdb
    log = AuditLog()
    for i in range(3):
        log.append(action="case.view", target=f"c-{i}", method="GET", path="/x", status=200)
    con = duckdb.connect(str(log.path))
    con.execute("UPDATE audit SET target = 'c-9' WHERE seq = 2")
    con.close()
    with pytest.raises(SystemExit) as e:
        cli.main(["audit", "--verify"])
    assert e.value.code == 1 and "BROKEN at row 2" in capsys.readouterr().out
