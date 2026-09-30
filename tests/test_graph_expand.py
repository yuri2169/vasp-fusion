"""The PS says the graph links IPs, WALLETS and TRANSACTIONS - not clusters only."""
import polars as pl

from vaspfusion.graph.build import expand_entity


def _addr_map() -> pl.DataFrame:
    return pl.DataFrame({
        "address": ["a1", "a2", "a3", "b1"],
        "entity_id": ["ENT-1", "ENT-1", "ENT-1", "ENT-2"],
    })


def _txs() -> pl.DataFrame:
    return pl.DataFrame({
        "txid": ["t1", "t2"],
        "sender_entity": ["ENT-1", "ENT-2"],
        "input_addresses": [["a1", "a2"], ["b1"]],
        "output_addresses": [["b1"], ["a3"]],
        "output_amounts": [[500], [700]],
        "timestamp": ["2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"],
    }).with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))


def test_expand_returns_the_constituent_addresses():
    got = expand_entity(_addr_map(), _txs(), "ENT-1")
    assert {a["address"] for a in got["addresses"]} == {"a1", "a2", "a3"}


def test_expand_returns_transactions_touching_the_entity():
    got = expand_entity(_addr_map(), _txs(), "ENT-1")
    assert {t["txid"] for t in got["transactions"]} == {"t1", "t2"}


def test_edges_connect_addresses_to_transactions():
    got = expand_entity(_addr_map(), _txs(), "ENT-1")
    pairs = {(e["source"], e["target"], e["kind"]) for e in got["edges"]}
    assert ("a1", "t1", "spends") in pairs
    assert ("t2", "a3", "pays") in pairs


def test_truncation_is_reported_not_silent():
    got = expand_entity(_addr_map(), _txs(), "ENT-1", max_addresses=1)
    assert got["truncated"] is True
    assert len(got["addresses"]) == 1
