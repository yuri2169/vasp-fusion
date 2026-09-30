"""`python -m vaspfusion.cli fetch` on the recorded BTC fixture."""
import json

import pytest

from vaspfusion import cli

ADDR = "1NBX1UZE3EFPTnYNkDfVhRADvVc8v6pRYu"


@pytest.fixture
def patched(fixture_fetcher, monkeypatch):
    holder = {}

    def make(offline=False):
        f = fixture_fetcher("btc_pages", offline=offline)
        holder["f"] = f
        monkeypatch.setattr("vaspfusion.chains.default_fetcher", lambda: f)
        return f
    return make


def test_fetch_json_lines(patched, capsys):
    patched()
    cli.main(["fetch", ADDR, "--limit", "5", "--json", "--labels", "none"])
    lines = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines()]
    assert len(lines) == 5
    assert {x["chain"] for x in lines} == {"bitcoin"}
    assert lines == sorted(lines, key=lambda x: x["block_time"])


def test_fetch_table_and_replay_identical(patched, capsys, monkeypatch):
    patched()
    cli.main(["fetch", ADDR, "--limit", "5", "--labels", "none"])
    first = capsys.readouterr().out
    assert "bitcoin (auto-detected)" in first and "5 transfers" in first and "live" in first
    patched(offline=True)
    monkeypatch.setenv("OFFLINE", "1")
    cli.main(["fetch", ADDR, "--limit", "5", "--labels", "none"])
    second = capsys.readouterr().out
    body = lambda s: [ln for ln in s.splitlines() if ln.startswith("  20")]  # noqa: E731
    assert body(first) == body(second) and len(body(first)) == 5
    assert "0 live, 1 cached" in second and "OFFLINE=1" in second


def test_fetch_offline_miss_fails_loudly(patched, capsys):
    patched(offline=True)
    with pytest.raises(SystemExit) as e:
        cli.main(["fetch", "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h", "--labels", "none"])
    assert e.value.code == 1
    assert "not cached" in capsys.readouterr().err


def test_fetch_invalid_address(patched, capsys):
    patched()
    with pytest.raises(SystemExit) as e:
        cli.main(["fetch", "nope", "--labels", "none"])
    assert e.value.code == 1
    assert "not a valid" in capsys.readouterr().err


def test_fetch_never_prints_keys(patched, capsys, monkeypatch):
    monkeypatch.setenv("TRONGRID_API_KEY", "SECRET-VALUE-123")
    patched()
    cli.main(["fetch", ADDR, "--limit", "2", "--labels", "none"])
    out = capsys.readouterr()
    assert "SECRET-VALUE-123" not in out.out + out.err
    assert "TRONGRID_API_KEY set" in out.out
