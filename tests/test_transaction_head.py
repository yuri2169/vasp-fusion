"""The PS asks why a wallet OR A TRANSACTION was flagged. Both need a model."""
import polars as pl

from vaspfusion.features.extract import transaction_feature_matrix


def _txs() -> pl.DataFrame:
    return pl.DataFrame({
        "txid": ["a", "b"],
        "timestamp": ["2026-06-01T00:00:00Z", "2026-06-02T03:00:00Z"],
        "sender_entity": ["ENT-1", "ENT-2"],
        "input_addresses": [["x"], ["y", "z"]],
        "output_addresses": [["p", "q"], ["r"]],
        "output_amounts": [[100_000, 900_000], [500_000]],
        "fee": [1000, 2000],
        "script_type": ["p2wpkh", "p2pkh"],
    }).with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))


def test_matrix_is_indexed_by_txid_and_has_no_nulls():
    fm = pl.DataFrame({"entity": ["ENT-1", "ENT-2"], "n_tx_sent": [4.0, 9.0]})
    m, names = transaction_feature_matrix(_txs(), fm, {"ENT-1": 0.9, "ENT-2": 0.1})
    assert m.height == 2
    assert m.columns[0] == "txid"
    assert set(names).issubset(set(m.columns))
    assert m.select(names).null_count().sum_horizontal()[0] == 0


def test_parent_entity_score_is_a_feature():
    """Roadmap 16.4-G: the parent entity's score is an input to the tx head."""
    fm = pl.DataFrame({"entity": ["ENT-1", "ENT-2"], "n_tx_sent": [4.0, 9.0]})
    m, names = transaction_feature_matrix(_txs(), fm, {"ENT-1": 0.9, "ENT-2": 0.1})
    assert "parent_entity_score" in names
    row = m.filter(pl.col("txid") == "a")
    assert row.get_column("parent_entity_score")[0] == 0.9


def test_unknown_parent_scores_zero_rather_than_null():
    fm = pl.DataFrame({"entity": ["ENT-1"], "n_tx_sent": [4.0]})
    m, names = transaction_feature_matrix(_txs(), fm, {"ENT-1": 0.9})
    row = m.filter(pl.col("txid") == "b")
    assert row.get_column("parent_entity_score")[0] == 0.0
