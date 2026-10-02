"""Address clustering: which addresses belong to the same real-world actor.

Two heuristics, both from Meiklejohn et al. (IMC 2013):

  H1 COMMON-INPUT-OWNERSHIP. Addresses co-spent as inputs to one transaction are
     controlled by one party, because signing them all required all their keys.
     This is the strong one.

  H2 CHANGE ADDRESS. In a two-output payment where exactly one output address has
     never been seen before, that fresh address is very likely change returning
     to the sender. Weaker, and applied as a second pass so we can tag which
     heuristic fired for each merge and report the split.

IMPLEMENTATION. Union-Find over co-spends *is* a connected-components problem, so
we hand it to scipy.sparse.csgraph rather than writing a disjoint-set in Python:
same answer, C speed, and one less hand-rolled data structure to get wrong. Note
each transaction contributes a STAR (input[0] linked to the rest), not a clique -
n-1 edges instead of n(n-1)/2, identical components, far less memory at scale.

Analysis at address level is meaningless - 150k addresses are perhaps 4k actual
actors, and an alert on an address is an alert on a fragment of a person.
"""
from __future__ import annotations

import numpy as np
import polars as pl
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .coinjoin import coinjoin_txids


def script_of_address(col: pl.Expr) -> pl.Expr:
    """Infer the output script type from the address encoding itself.

    Bech32 witness-v0 programs are 20 bytes for p2wpkh and 32 for p2wsh, which
    shows up as address length; witness-v1 (Taproot) uses the `bc1p` prefix.
    Free signal - no extra column required - and it powers both the change
    heuristic and the wallet-software fingerprint features in §6.5.
    """
    return (
        pl.when(col.str.starts_with("bc1p")).then(pl.lit("p2tr"))
        .when(col.str.starts_with("bc1q") & (col.str.len_chars() <= 45)).then(pl.lit("p2wpkh"))
        .when(col.str.starts_with("bc1q")).then(pl.lit("p2wsh"))
        .when(col.str.starts_with("1")).then(pl.lit("p2pkh"))
        .when(col.str.starts_with("3")).then(pl.lit("p2sh"))
        .otherwise(pl.lit("unknown"))
    )


def to_transactions(df: pl.DataFrame) -> pl.DataFrame:
    """Collapse announcement rows to one row per transaction (the chain layer).

    A capture contains many announcements of the same transaction; the chain-side
    payload is identical across them, so carrying duplicates into feature
    extraction would multiply every per-transaction statistic by the observation
    count - a subtle bug that produces plausible, wrong numbers.
    """
    agg = [
        pl.col("timestamp").min().alias("timestamp"),
        pl.col("input_addresses").first(),
        pl.col("output_addresses").first(),
        pl.col("input_amounts").first(),
        pl.col("output_amounts").first(),
        pl.col("fee").first(),
        pl.col("script_type").first(),
        pl.len().alias("n_announcements"),
    ]
    for c, alias in (("src_ip", "n_src_ips"), ("src_asn", "n_src_asns")):
        if c in df.columns:
            agg.append(pl.col(c).n_unique().alias(alias))
    return df.group_by("txid").agg(agg).sort("timestamp")


def resolve_entities(txs: pl.DataFrame, coinjoin_guard: bool = True,
                     min_equal: int = 3, change: bool = True,
                     coinjoin: set[str] | None = None) -> tuple[pl.DataFrame, dict]:
    """Return (address -> entity_id mapping, stats).

    `change=False` leaves H2 out, so entities are common-input ownership alone. H2's
    "never seen before" is only true of the table it is given: on a slice of the chain
    (one address's page, as in vaspfusion/cluster.py) an old address can look fresh.

    `coinjoin`: the transactions to keep out of both heuristics, when the caller has
    decided that itself (Bitcoin uses its own measured settings, chains/btc.py)."""
    ins = txs.select(["txid", "input_addresses"]) \
             .explode("input_addresses", empty_as_null=True) \
             .rename({"input_addresses": "address"}).drop_nulls()
    outs = txs.select(["txid", "timestamp", "output_addresses"]) \
              .explode("output_addresses", empty_as_null=True) \
              .rename({"output_addresses": "address"}).drop_nulls()

    addresses = (pl.concat([ins.select("address"), outs.select("address")])
                 .unique().sort("address").get_column("address").to_list())
    if not addresses:
        return pl.DataFrame({"address": [], "entity_id": []}), {"n_addresses": 0, "n_entities": 0}
    index = {a: i for i, a in enumerate(addresses)}
    n = len(addresses)

    # CoinJoin-shaped transactions are excluded from BOTH heuristics: their
    # inputs belong to different people (graph/coinjoin.py).
    if coinjoin is not None:
        skip = set(coinjoin)
    else:
        skip = coinjoin_txids(txs, min_equal) if coinjoin_guard else set()
    if skip:
        ins = ins.filter(~pl.col("txid").is_in(list(skip)))

    # --- H1: co-spent inputs, as a star per transaction ---------------------
    ins = ins.with_columns(
        pl.col("address").replace_strict(index, return_dtype=pl.Int64).alias("idx"))
    grouped = ins.group_by("txid").agg(pl.col("idx"))
    rows: list[int] = []
    cols: list[int] = []
    for idxs in grouped.get_column("idx").to_list():
        if idxs is None or len(idxs) < 2:
            continue
        head = idxs[0]
        for other in idxs[1:]:
            rows.append(head)
            cols.append(other)
    n_cospend_edges = len(rows)

    # --- H2: change address, with the script-type refinement ----------------
    # Plain "the fresh output is the change" almost never fires in practice,
    # because recipients mint fresh addresses too - so a two-output payment
    # usually has TWO fresh outputs and the heuristic declines.
    #
    # The published refinement (§16.2-B) breaks that tie: a change output
    # normally matches the SCRIPT TYPE of the inputs, because the same wallet
    # made it, whereas the recipient's address type is whatever their wallet
    # uses. Script type is inferable from the address string itself, so this
    # costs nothing and converts a heuristic that fired on ~16% of two-output
    # payments into one that fires on most of them.
    #
    # It is a heuristic, not a proof: mixed-wallet users break it, and we tag
    # merges by which heuristic produced them so the error is attributable.
    # Sort by (timestamp, txid), NOT timestamp alone. Block timestamps have
    # one-second resolution so ties are routine, and with a tie `.first()` returns
    # whichever row happens to come first in the frame - which makes the whole
    # clustering depend on input row order. A property test caught exactly that:
    # the same two transactions in reverse order produced different entities.
    first_seen = (outs.sort(["timestamp", "txid"]).group_by("address")
                  .agg(pl.col("txid").first())
                  .rename({"txid": "first_txid"}))
    small_out = txs.filter((pl.col("output_addresses").list.len() >= 2)
                           & (pl.col("output_addresses").list.len() <= 6)) \
                   .select(["txid", "input_addresses", "output_addresses", "script_type"])
    cand = (small_out.explode("output_addresses", empty_as_null=True)
            .rename({"output_addresses": "address"})
            .join(first_seen, on="address", how="left"))
    cand = cand.filter(pl.col("first_txid") == pl.col("txid"))
    cand = cand.with_columns(script_of_address(pl.col("address")).alias("out_script"))
    # keep only fresh outputs whose script type matches the spending wallet's
    cand = cand.filter(pl.col("out_script") == pl.col("script_type"))
    # ...and require it to be unambiguous within the transaction
    counts = cand.group_by("txid").len().filter(pl.col("len") == 1).select("txid")
    fresh = cand.join(counts, on="txid", how="inner")
    if skip:
        fresh = fresh.filter(~pl.col("txid").is_in(list(skip)))
    if not change:
        fresh = fresh.clear()

    n_change_edges = 0
    for row in fresh.select(["input_addresses", "address"]).iter_rows():
        inputs, chg = row
        if not inputs or chg not in index:
            continue
        src = index.get(inputs[0])
        if src is None:
            continue
        rows.append(src)
        cols.append(index[chg])
        n_change_edges += 1

    if rows:
        data = np.ones(len(rows), dtype=np.int8)
        adj = coo_matrix((data, (np.array(rows), np.array(cols))), shape=(n, n))
    else:
        adj = coo_matrix((n, n), dtype=np.int8)
    n_comp, labels = connected_components(adj, directed=False)

    mapping = pl.DataFrame({
        "address": addresses,
        "entity_id": [f"ENT-{int(x):05d}" for x in labels],
    })
    sizes = np.bincount(labels)
    stats = {
        "n_addresses": n,
        "n_entities": int(n_comp),
        "coinjoin_txs_skipped": len(skip),
        "cospend_edges": n_cospend_edges,
        "change_edges": n_change_edges,
        "largest_entity_addresses": int(sizes.max()) if len(sizes) else 0,
        "mean_addresses_per_entity": float(n / max(1, n_comp)),
        "singleton_entities": int((sizes == 1).sum()),
    }
    return mapping, stats


def attach_entities(txs: pl.DataFrame, mapping: pl.DataFrame) -> pl.DataFrame:
    """Label each transaction with its spending entity and the entities it paid.

    Done as explode + join + group rather than a per-row Python UDF: at 170k
    transactions the UDF path costs tens of seconds and hands Polars a Series it
    cannot reason about, while the join stays vectorised and runs in well under
    a second.
    """
    sender = (txs.select(["txid", "input_addresses"])
              .with_columns(pl.col("input_addresses").list.first().alias("address"))
              .drop("input_addresses")
              .join(mapping, on="address", how="left")
              .select(["txid", pl.col("entity_id").alias("sender_entity")]))

    receivers = (txs.select(["txid", "output_addresses"])
                 .explode("output_addresses")
                 .rename({"output_addresses": "address"})
                 .join(mapping, on="address", how="left")
                 .drop_nulls("entity_id")
                 .group_by("txid")
                 .agg(pl.col("entity_id").unique().alias("receiver_entities")))

    return (txs.join(sender, on="txid", how="left")
               .join(receivers, on="txid", how="left")
               .with_columns(pl.col("receiver_entities").fill_null([])))
