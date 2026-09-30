"""Typology matchers - EVIDENCE GENERATORS, never detectors.

THE DISTINCTION IS THE POINT. These rules never decide whether an alert is
raised; the models do that. What a matcher contributes is concrete,
human-checkable corroboration attached to an alert the model already raised: the
actual transaction IDs, the actual path, the actual amounts. That is what makes
an alert auditable rather than merely explained, and it is what satisfies the
PS's "working model - not just rules" wording while still giving the analyst
something they can verify by hand (roadmap §4.3, §6.8 layer 3).

If these ever start gating alerts, the project has quietly become the
rules-engine every other team is building.
"""
from __future__ import annotations

import polars as pl

ROUND_SATS = 100_000_000


class Evidence(dict):
    """One corroborating observation: a label, a strength, and the receipts."""


def _fmt_btc(sats) -> str:
    return f"{(sats or 0) / 1e8:.4f}"


def match_typologies(fm: pl.DataFrame, txs: pl.DataFrame,
                     top_entities: list[str]) -> dict[str, list[dict]]:
    """Return entity -> list of evidence dicts.

    Computed only for the entities actually being shown to an analyst. Running it
    across all 89k entities would cost time nobody spends: the analyst opens the
    top of the queue, not the tail.
    """
    if not top_entities:
        return {}
    f = fm.filter(pl.col("entity").is_in(top_entities))
    sub = txs.filter(pl.col("sender_entity").is_in(top_entities))

    # Per-entity transaction detail, newest first, for quoting real TXIDs.
    detail: dict[str, list[dict]] = {}
    for row in sub.select(["sender_entity", "txid", "timestamp", "output_amounts",
                           "output_addresses", "fee"]).sort("timestamp").iter_rows(named=True):
        detail.setdefault(row["sender_entity"], []).append(row)

    out: dict[str, list[dict]] = {}
    for r in f.iter_rows(named=True):
        eid = r["entity"]
        txlist = detail.get(eid, [])
        ev: list[dict] = []

        # --- peel chain ---------------------------------------------------
        # A long, thin outward reach where most spends split into exactly two
        # outputs and one of them is consistently tiny.
        if (r.get("peel_ratio_mean", 0) or 0) > 0 and r.get("two_output_frac", 0) > 0.45 \
                and r.get("chain_linearity", 0) > 1.8 and r.get("peel_ratio_mean", 1) < 0.22:
            examples = [t for t in txlist if len(t["output_amounts"]) == 2][:3]
            ev.append(Evidence(
                typology="peel_chain",
                strength=min(1.0, float(r["chain_linearity"]) / 6.0),
                summary=(f"Peel pattern: {r['two_output_frac']:.0%} of spends split into two "
                         f"outputs with a mean peel of {r['peel_ratio_mean']:.1%}, "
                         f"reaching {int(r.get('reach_3', 0))} entities within 3 hops."),
                txids=[t["txid"] for t in examples],
                detail=[{"txid": t["txid"],
                         "peel_btc": _fmt_btc(min(t["output_amounts"])),
                         "remainder_btc": _fmt_btc(max(t["output_amounts"]))}
                        for t in examples]))

        # --- fan-out / fan-in ---------------------------------------------
        if r.get("max_n_outputs", 0) >= 8 and r.get("n_counterparties_out", 0) >= 8:
            examples = sorted(txlist, key=lambda t: -len(t["output_amounts"]))[:2]
            ev.append(Evidence(
                typology="fan_out_in",
                strength=min(1.0, float(r["max_n_outputs"]) / 30.0),
                summary=(f"Fan-out: a single transaction split across "
                         f"{int(r['max_n_outputs'])} outputs; "
                         f"{int(r['n_counterparties_out'])} distinct counterparties overall."),
                txids=[t["txid"] for t in examples],
                detail=[{"txid": t["txid"], "n_outputs": len(t["output_amounts"]),
                         "total_btc": _fmt_btc(sum(t["output_amounts"]))}
                        for t in examples]))

        # --- rapid layering ------------------------------------------------
        gap = r.get("gap_mean", 0) or 0
        if 0 < gap < 3600 and r.get("n_tx_sent", 0) >= 5 and r.get("chain_linearity", 0) > 1.4:
            ev.append(Evidence(
                typology="rapid_layering",
                strength=min(1.0, 3600.0 / max(gap, 60.0) / 12.0),
                summary=(f"Rapid layering: {int(r['n_tx_sent'])} spends with a mean gap of "
                         f"{gap / 60:.0f} minutes - almost no dwell time between hops."),
                txids=[t["txid"] for t in txlist[:3]],
                detail=[{"txid": t["txid"], "ts": str(t["timestamp"])} for t in txlist[:3]]))

        # --- mixer signature -----------------------------------------------
        # Many outputs paying the SAME value, plus uniform script types. Keyed on
        # output_uniformity rather than entropy: entropy is maximal for uniform
        # values, so an earlier version of this rule matched the exact inverse of
        # a CoinJoin. A property test caught it.
        # Equal output VALUES is the primary signal and an excellent one:
        # mixer-archetype entities average 0.86 here against under 0.02 for every
        # other archetype. Script uniformity corroborates and raises the strength,
        # but does NOT gate - gating on it suppressed the rule entirely on wallets
        # whose participants used mixed address types.
        _unif = float(r.get("output_uniformity_max", 0) or 0)
        if _unif >= 0.5 and r.get("max_n_outputs", 0) >= 6:
            examples = sorted(txlist, key=lambda t: -len(t["output_amounts"]))[:2]
            ev.append(Evidence(
                typology="mixer_passthrough",
                strength=float(min(1.0, _unif * (1.0 + 0.3 * float(
                    r.get("script_uniformity", 0) or 0)))),
                summary=(f"Mixer signature: {_unif:.0%} of outputs in one transaction "
                         f"repeat the same value"
                         + (f", and {float(r.get('script_uniformity', 0)):.0%} of outputs "
                            f"share one script type" if float(r.get("script_uniformity", 0) or 0) > 0.7
                            else "")
                         + " - the CoinJoin fingerprint."),
                txids=[t["txid"] for t in examples],
                detail=[{"txid": t["txid"], "n_outputs": len(t["output_amounts"]),
                         "distinct_values": len(set(t["output_amounts"]))}
                        for t in examples]))

        # --- dormancy burst -------------------------------------------------
        # A short-lived wallet with four spends trivially has one gap covering
        # most of its life; that is not dormancy, it is just a brief existence.
        # Require a long observed lifespan AND a genuinely large absolute gap.
        if (r.get("dormancy_ratio", 0) > 0.7 and r.get("n_tx_sent", 0) >= 4
                and r.get("lifespan_days", 0) >= 7
                and (r.get("gap_max", 0) or 0) >= 5 * 86400):
            ev.append(Evidence(
                typology="dormancy_burst",
                strength=float(r["dormancy_ratio"]),
                summary=(f"Dormancy: {r['dormancy_ratio']:.0%} of this entity's "
                         f"{r['lifespan_days']:.0f}-day lifespan is a single "
                         f"{(r['gap_max'] or 0) / 86400:.0f}-day gap, followed by "
                         f"{int(r['n_tx_sent'])} spends in a burst."),
                txids=[t["txid"] for t in txlist[-3:]],
                detail=[{"txid": t["txid"], "ts": str(t["timestamp"])} for t in txlist[-3:]]))

        # --- cross-ASN structuring ------------------------------------------
        if r.get("structuring_proximity", 0) > 0.45 and r.get("n_asns", 0) >= 3:
            ev.append(Evidence(
                typology="cross_asn_structuring",
                strength=float(r["structuring_proximity"]),
                summary=(f"Structuring: {r['structuring_proximity']:.0%} of outputs sit just "
                         f"below a round threshold, spread over {int(r['n_asns'])} "
                         f"autonomous systems."),
                txids=[t["txid"] for t in txlist[:3]],
                detail=[{"txid": t["txid"], "total_btc": _fmt_btc(sum(t["output_amounts"]))}
                        for t in txlist[:3]]))

        if ev:
            out[eid] = ev
    return out


def evidence_strength(fm: pl.DataFrame, txs: pl.DataFrame,
                      entities: list[str]) -> pl.DataFrame:
    """A scalar per entity for the fusion stage.

    Note what this is NOT: it never raises an alert on its own. It is one of
    three inputs to the fused score, weighted lowest of the three by config.
    """
    matches = match_typologies(fm, txs, entities)
    rows = [{"entity": e,
             "evidence_strength": max((m["strength"] for m in ev), default=0.0),
             "n_evidence": len(ev),
             "matched_typologies": "|".join(sorted({m["typology"] for m in ev}))}
            for e, ev in matches.items()]
    if not rows:
        return pl.DataFrame({"entity": [], "evidence_strength": [], "n_evidence": [],
                             "matched_typologies": []},
                            schema={"entity": pl.Utf8, "evidence_strength": pl.Float64,
                                    "n_evidence": pl.Int64, "matched_typologies": pl.Utf8})
    return pl.DataFrame(rows)
