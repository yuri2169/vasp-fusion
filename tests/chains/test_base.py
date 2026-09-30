import json
from datetime import datetime, timezone
from decimal import Decimal

from vaspfusion.chains.base import Transfer, sort_transfers, utc_from_ms
from vaspfusion.chains.http import api_key, load_env


def _t(tx, ms, amount="1"):
    return Transfer("tron", tx, utc_from_ms(ms), "Ta", "Tb", "USDT", Decimal(amount),
                    Decimal(amount), None, "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")


def test_to_dict_is_exact_and_json_safe():
    # a real TronGrid row: value 135590494742670 with 6 decimals
    t = _t("793bff", 1790772078000, Decimal(135590494742670).scaleb(-6))
    d = t.to_dict()
    assert d["amount"] == "135590494.74267"
    assert d["block_time"] == "2026-09-30T12:41:18Z"
    assert json.loads(json.dumps(d)) == d


def test_to_dict_no_exponent():
    assert _t("a", 0, Decimal("1.500E+3")).to_dict()["amount"] == "1500"
    assert _t("a", 0, Decimal("0.000001")).to_dict()["amount"] == "0.000001"


def test_sort_is_deterministic():
    rows = [_t("b", 2000), _t("a", 2000), _t("c", 1000)]
    assert [r.tx_hash for r in sort_transfers(rows)] == ["c", "a", "b"]
    assert sort_transfers(rows) == sort_transfers(list(reversed(rows)))


def test_utc_from_ms_is_aware():
    assert utc_from_ms(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_load_env_process_env_wins(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\n\nFOO_KEY="from-file"\nBAR_KEY=bar\nEMPTY_KEY=\n')
    monkeypatch.setenv("FOO_KEY", "from-process")
    monkeypatch.delenv("BAR_KEY", raising=False)
    monkeypatch.delenv("EMPTY_KEY", raising=False)
    vals = load_env(env)
    assert vals["FOO_KEY"] == "from-process"
    assert vals["BAR_KEY"] == "bar"
    assert api_key("EMPTY_KEY", env) is None
    assert api_key("BAR_KEY", env) == "bar"
    assert api_key("MISSING_KEY", env) is None


def test_load_env_missing_file(tmp_path):
    assert load_env(tmp_path / "nope.env") == {}
