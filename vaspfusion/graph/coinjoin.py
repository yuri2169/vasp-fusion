"""Which transactions look like a collaborative CoinJoin?

Common-input-ownership (resolve.py H1) assumes one party signed every input. A
CoinJoin breaks that by design: many owners each contribute an input and each
receive an identical output, so merging its inputs fuses unrelated people into
one "actor" - the best-known failure of address clustering. Stutz et al. (AFT
2022) detect Wasabi and Samourai rounds with 99-100% accuracy using these
shapes: a block of equal-value outputs making up at least half the outputs,
and at least as many inputs as equal outputs.

Those shapes alone also match a single owner paying many equal amounts from a
consolidated wallet - a custodial mixer's payout batch, for one. Merging those
inputs is CORRECT (one owner), and refusing to cost 0.119 PR-AUC on the b2
capture, where 220 of the 340 transactions the shape rule flagged were such
payouts; skipping only the 120 true CoinJoins cost nothing (+0.009). So a
transaction must also show evidence of several owners, either of:

  * two or more non-equal outputs - several participants took change, where one
    owner needs at most one change output;
  * every equal output individually funded - at least as many inputs worth the
    denomination or more as there are equal outputs, the one-input-per-participant
    pattern of Whirlpool (no change at all) and of rounds whose only non-equal
    output is a coordinator fee. A consolidating payer's inputs are mostly
    smaller than the amount it pays out.

Measured on synthetic data only (b2: 120 of 120 CoinJoins, 0 false flags). The
generator gives every participant one input; real rounds where participants
bring several small inputs AND take no change would be missed.
"""
from __future__ import annotations

import polars as pl


def coinjoin_txids(txs: pl.DataFrame, min_equal: int = 3) -> set[str]:
    if "output_amounts" not in txs.columns or txs.height == 0:
        return set()
    eq = (txs.select(["txid", "output_amounts"]).explode("output_amounts").drop_nulls()
          .group_by(["txid", "output_amounts"]).len()
          .sort(["txid", "len", "output_amounts"], descending=[False, True, True])
          .group_by("txid", maintain_order=True).first()
          .rename({"output_amounts": "denom", "len": "max_equal"}))
    shape = txs.select(["txid",
                        pl.col("input_addresses").list.len().alias("n_in"),
                        pl.col("output_amounts").list.len().alias("n_out")])
    hit = shape.join(eq, on="txid", how="inner")
    if "input_amounts" in txs.columns:
        funded = (txs.select(["txid", "input_amounts"]).explode("input_amounts")
                  .join(eq.select(["txid", "denom"]), on="txid", how="inner")
                  .group_by("txid")
                  .agg((pl.col("input_amounts") >= pl.col("denom")).sum().alias("n_funded")))
        hit = hit.join(funded, on="txid", how="left")
    else:
        hit = hit.with_columns(pl.lit(0).alias("n_funded"))
    hit = hit.filter((pl.col("max_equal") >= min_equal)
                     & (pl.col("n_in") >= pl.col("max_equal"))
                     & (pl.col("max_equal") * 2 >= pl.col("n_out"))
                     & ((pl.col("n_out") - pl.col("max_equal") >= 2)
                        | (pl.col("n_funded").fill_null(0) >= pl.col("max_equal"))))
    return set(hit.get_column("txid").to_list())
