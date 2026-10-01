"""The abstain threshold's validation set: claims from label-hidden traces (toy traces
here), and the tracked measurement recomputed from the tracked claims."""
import json
from pathlib import Path

import polars as pl
import pytest

from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.eval.abstain import (AbstainConfig, WithoutTier, claims_for, collect, measure,
                                     read_claims, sample_wallets, write_claims)

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"HOT_A": ("ExA", "exchange", "hot", "curated"),
          "HOT_B": ("ExB", "exchange", "hot", "curated"),
          "DEP_A": ("ExA", "exchange", "deposit", "derived", 0.8),
          "DEP_B": ("ExB", "exchange", "deposit", "derived", 0.8)}
ROWS = [
    # W1 pays ExA's derived deposit address, which sweeps to ExA's wallet
    tx(1, "W1", "DEP_A", 1000, 0), tx(2, "DEP_A", "HOT_A", 1000, 3),
    # W2 pays ExA's deposit address, and a friend who pays ExB's wallet
    tx(3, "W2", "DEP_A", 600, 10), tx(4, "DEP_A", "HOT_A", 600, 13),
    tx(5, "W2", "FRIEND", 400, 11), tx(6, "FRIEND", "HOT_B", 400, 90),
    # W3 pays ExB's wallet directly, and ExA's deposit address
    tx(7, "W3", "HOT_B", 500, 20), tx(8, "W3", "DEP_A", 500, 21), tx(9, "DEP_A", "HOT_A", 500, 25),
    # W4's deposit address has not swept yet
    tx(10, "W4", "DEP_B", 700, 30),
]


def rows_for(wallet, exchange):
    return claims_for(wallet, exchange, CHAIN, ToyProvider(ROWS), ToyLabels(LABELS))


def test_hiding_the_derived_labels_makes_the_trace_find_the_exchange_one_hop_further():
    r, = rows_for("W1", "ExA")
    assert r == {"wallet": "W1", "exchange": "ExA", "run": "", "known": "ExA", "vasp": "ExA", "rank": 1,
                 "hops": 2, "share": 1.0, "confidence": 0.7225, "direct": 0, "correct": 1}


def test_an_exchange_reached_through_a_wallet_that_is_no_deposit_address_counts_as_wrong():
    a, b = rows_for("W2", "ExA")
    assert (a["vasp"], a["correct"], a["direct"]) == ("ExA", 1, 0)
    assert (b["vasp"], b["correct"], b["direct"], b["known"]) == ("ExB", 0, 0, "ExA")


def test_an_exchange_paid_directly_is_known_and_its_claim_is_kept_apart():
    by = {r["vasp"]: r for r in rows_for("W3", "ExA")}
    assert by["ExB"]["direct"] == 1 and by["ExB"]["correct"] == 1
    assert by["ExA"]["direct"] == 0 and by["ExA"]["known"] == "ExA|ExB"


def test_a_wallet_is_traced_from_the_start_of_its_discovery_window():
    from datetime import timedelta

    from tracekit import T0
    # W2's payment to the friend (minute 11) is inside the window, the one before is not
    rows = claims_for("W2", "ExA", CHAIN, ToyProvider(ROWS), ToyLabels(LABELS),
                      since=T0 + timedelta(minutes=10, seconds=30), run="r9")
    assert [(r["vasp"], r["share"], r["run"]) for r in rows] == [("ExB", 1.0, "r9")]


def test_a_wallet_whose_exchange_cannot_be_found_is_one_empty_row():
    r, = rows_for("W4", "ExB")
    assert (r["vasp"], r["confidence"], r["known"]) == ("", "", "ExB")


def test_without_tier_hides_only_that_tier():
    seen = WithoutTier(ToyLabels(LABELS)).lookup_many([("DEP_A", CHAIN), ("HOT_A", CHAIN)])
    assert set(seen) == {("HOT_A", CHAIN)}


def test_the_sample_is_seeded_and_takes_customers_only():
    df = pl.DataFrame({"address": [f"A{i:02d}" for i in range(30)], "run": ["r1"] * 30,
                       "source": ["customer"] * 20 + ["derived"] * 10,
                       "group": ["ExA"] * 10 + ["ExB"] * 10 + ["ExA"] * 10})
    cfg = AbstainConfig(per_exchange=4)
    picked = sample_wallets(df, cfg)
    assert picked == sample_wallets(df.sample(fraction=1.0, shuffle=True, seed=1), cfg)
    assert [(e, r) for _, e, r in picked] == [("ExA", "r1")] * 4 + [("ExB", "r1")] * 4
    assert all(int(a[1:]) < 20 for a, _, _ in picked)


def test_collect_is_the_same_with_threads_and_the_csv_round_trips(tmp_path):
    wallets = [("W1", "ExA", "r"), ("W2", "ExA", "r"), ("W3", "ExA", "r"), ("W4", "ExB", "r")]
    one, stats = collect(wallets, CHAIN, ToyProvider(ROWS), lambda: ToyLabels(LABELS))
    many, _ = collect(wallets, CHAIN, ToyProvider(ROWS), lambda: ToyLabels(LABELS), workers=3)
    assert one == many and stats == {"wallets_sampled": 4, "wallets_read": 4, "errors": 0}
    back = read_claims(write_claims(tmp_path / "claims.csv", one))
    assert [r for r in back if r["vasp"]] == [r for r in one if r["vasp"]]
    assert measure(back, CHAIN) == measure(one, CHAIN)


def test_the_measurement_counts_claims_and_cases():
    wallets = [("W1", "ExA", "r"), ("W2", "ExA", "r"), ("W3", "ExA", "r"), ("W4", "ExB", "r")]
    rows, _ = collect(wallets, CHAIN, ToyProvider(ROWS), lambda: ToyLabels(LABELS))
    m = measure(rows, CHAIN)
    assert (m["wallets"], m["wallets_with_a_claim"]) == (4, 3)
    assert m["wallets_by_exchange"] == {"ExA": 3, "ExB": 1}
    assert {k: m["through_unlabelled"][k] for k in ("claims", "right", "wrong")} == \
        {"claims": 4, "right": 3, "wrong": 1}
    # W3 paid ExB directly: that claim rests on a label that was not hidden, so it is
    # counted apart and decides nothing below
    assert m["direct_claims"] == {"claims": 1, "wallets": 1}
    at = m["at_current"]
    assert m["current_threshold"] == 0.60
    assert {k: at[k] for k in ("claims_answered", "claims_wrong", "wallets", "named", "right",
                               "wrong", "abstained", "coverage", "risk")} == \
        {"claims_answered": 4, "claims_wrong": 1, "wallets": 4, "named": 3, "right": 3,
         "wrong": 0, "abstained": 1, "coverage": 0.75, "risk": 0.0}
    assert m["measured_threshold"] is None                # three wallets cannot show under 5%
    assert any("not calibrated" in n for n in m["notes"])


def claim(wallet, vasp, rank, conf, direct, correct):
    return {"wallet": wallet, "exchange": "ExA", "run": "r", "known": "ExA", "vasp": vasp,
            "rank": rank, "hops": 1 if direct else 2, "share": 0.5, "confidence": conf,
            "direct": direct, "correct": correct}


def test_a_direct_claim_cannot_hide_a_wrong_claim_made_through_an_unlabelled_wallet():
    rows = [r for i in range(10) for r in (claim(f"W{i}", "ExA", 1, 0.85, 1, 1),
                                           claim(f"W{i}", "ExB", 2, 0.7225, 0, 0))]
    at = measure(rows, CHAIN)["at_current"]
    assert (at["named"], at["wrong"], at["risk"]) == (10, 10, 1.0)


def test_the_bound_counts_wallets_not_claims():
    # three wallets with forty right claims each are three trials, not 120
    rows = [claim(f"W{i}", f"Ex{j}", j + 1, 0.8, 0, 1) for i in range(3) for j in range(40)]
    m = measure(rows, CHAIN)
    assert m["at_current"]["named"] == 3 and m["at_current"]["risk_upper_bound"] > 0.5
    assert m["measured_threshold"] is None
    many = [claim(f"W{i}", "ExA", 1, 0.8, 0, 1) for i in range(200)]
    assert measure(many, CHAIN)["measured_threshold"] == 0.30


def test_a_bar_off_the_grid_and_an_unsorted_grid_are_measured_all_the_same():
    rows = [claim(f"W{i}", "ExA", 1, 0.61 + i / 100, 0, 1) for i in range(5)]
    m = measure(rows, CHAIN, AbstainConfig(grid=(0.8, 0.6, 0.3)), current=0.62)
    assert [b["threshold"] for b in m["bars"]] == [0.3, 0.6, 0.8]
    assert (m["at_current"]["threshold"], m["at_current"]["named"]) == (0.62, 4)
    from vaspfusion.eval.abstain import abstain_info, risk_coverage_svg
    assert [b["wallets_named"] for b in abstain_info(m)["bars"]] == [5, 5, 0]
    assert "bar 0.62 in use" in risk_coverage_svg(m)


# ------------------------------------------------------------------ the tracked artefacts
TRACKED = ROOT / "artifacts" / "abstain_v1" / "tron"


@pytest.mark.skipif(not (TRACKED / "claims.csv").exists(), reason="make abstain-eval not run")
def test_the_tracked_measurement_is_what_the_tracked_claims_give():
    m = json.loads((TRACKED / "validation.json").read_text())
    rows = read_claims(TRACKED / "claims.csv")
    cfg = AbstainConfig(per_exchange=m["config"]["per_exchange"])
    again = measure(rows, "tron", cfg, current=m["current_threshold"])
    assert again == {k: v for k, v in m.items() if k in again}
    assert m["seed"] == 26182 and m["wallets"] == len({r["wallet"] for r in rows})
    # every wallet is a customer in the deposit model's tracked dataset
    from vaspfusion.classify.dataset import read_dataset
    df = read_dataset(ROOT / "artifacts" / "model_v1" / "tron" / "dataset.csv")
    customers = dict(df.filter(pl.col("source") == "customer").select("address", "group")
                     .iter_rows())
    assert all(customers.get(r["wallet"]) == r["exchange"] for r in rows)
