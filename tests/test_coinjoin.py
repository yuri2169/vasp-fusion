import polars as pl

from vaspfusion.graph.coinjoin import coinjoin_txids
from vaspfusion.graph.resolve import resolve_entities


def _txs() -> pl.DataFrame:
    return pl.DataFrame({
        "txid": ["cj", "pay"],
        "timestamp": [1, 2],
        "input_addresses": [["i1", "i2", "i3", "i4", "i5"], ["p1", "p2"]],
        "output_addresses": [["o1", "o2", "o3", "o4", "o5", "c1"], ["q1", "q2"]],
        "input_amounts": [[1_200_000] * 5, [300_000, 300_000]],
        "output_amounts": [[1_000_000] * 5 + [150_000], [400_000, 190_000]],
        "script_type": ["p2wpkh", "p2wpkh"],
    })


def _entity(mapping: pl.DataFrame, addr: str) -> str:
    return mapping.filter(pl.col("address") == addr).get_column("entity_id").item()


def test_only_the_equal_output_multi_input_transaction_is_flagged():
    assert coinjoin_txids(_txs()) == {"cj"}


def test_guard_keeps_coinjoin_inputs_apart_but_still_merges_ordinary_cospends():
    m, stats = resolve_entities(_txs(), coinjoin_guard=True)
    assert len({_entity(m, a) for a in ("i1", "i2", "i3", "i4", "i5")}) == 5
    assert _entity(m, "p1") == _entity(m, "p2")
    assert stats["coinjoin_txs_skipped"] == 1


def test_without_the_guard_common_input_ownership_merges_the_coinjoin():
    m, _ = resolve_entities(_txs(), coinjoin_guard=False)
    assert len({_entity(m, a) for a in ("i1", "i2", "i3", "i4", "i5")}) == 1


def test_no_amount_column_means_no_coinjoin_can_be_claimed():
    assert coinjoin_txids(_txs().drop("output_amounts")) == set()


def test_single_owner_fan_out_with_equal_outputs_is_not_a_coinjoin():
    """A laundering fan-out pays many equal legs from a few inputs; a CoinJoin gives
    roughly one equal output per participant input. Merging the fan-out's inputs
    is correct, so it must not be flagged."""
    fan = pl.DataFrame({
        "txid": ["fan"], "timestamp": [1],
        "input_addresses": [["s1", "s2"]],
        "output_addresses": [[f"leg{i}" for i in range(8)]],
        "input_amounts": [[5_000_000, 5_000_000]],
        "output_amounts": [[1_200_000] * 8],
        "script_type": ["p2wpkh"],
    })
    assert coinjoin_txids(fan) == set()


def test_custodial_payout_batch_with_one_change_output_is_not_a_coinjoin():
    """One owner consolidating many small deposits to pay equal chunks: enough
    inputs, enough equal outputs, but one change output and inputs smaller than
    the payout. That is one owner - its inputs should merge."""
    batch = pl.DataFrame({
        "txid": ["batch"], "timestamp": [1],
        "input_addresses": [[f"d{i}" for i in range(15)]],
        "output_addresses": [[f"c{i}" for i in range(11)] + ["change"]],
        "input_amounts": [[400_000] * 13 + [900_000, 900_000]],
        "output_amounts": [[489_000] * 11 + [70_000]],
        "script_type": ["p2wpkh"],
    })
    assert coinjoin_txids(batch) == set()


def test_whirlpool_and_change_taking_rounds_are_coinjoins():
    """Whirlpool: 5 inputs, 5 equal outputs, no change. A JoinMarket-style round:
    each participant takes change, some bring two small inputs."""
    rounds = pl.DataFrame({
        "txid": ["whirl", "jm"], "timestamp": [1, 2],
        "input_addresses": [[f"w{i}" for i in range(5)], [f"j{i}" for i in range(6)]],
        "output_addresses": [[f"x{i}" for i in range(5)], [f"y{i}" for i in range(8)]],
        "input_amounts": [[1_000_500] * 5, [700_000, 700_000, 1_600_000, 1_300_000, 900_000, 900_000]],
        "output_amounts": [[1_000_000] * 5, [1_000_000] * 4 + [390_000, 290_000, 590_000, 280_000]],
        "script_type": ["p2wpkh", "p2wpkh"],
    })
    assert coinjoin_txids(rounds) == {"whirl", "jm"}
