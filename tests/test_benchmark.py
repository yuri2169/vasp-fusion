"""The multichain benchmark: sampling, hiding and scoring on toy traces, and the Tron row
recomputed from the tracked claims."""
from pathlib import Path

from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.eval import benchmark as B
from vaspfusion.eval.abstain import read_claims

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"DEP_A": ("ExA", "exchange", "deposit", "explorer_tag"),
          "DEP_A2": ("ExA", "exchange", "deposit", "explorer_tag"),
          "HOT_A": ("ExA", "exchange", "hot", "curated"),
          "HOT_B": ("ExB", "exchange", "hot", "curated"),
          "HOT_B2": ("ExB", "exchange", "hot", "curated"),
          "KNOWN": ("Somebody", "entity")}
ROWS = [
    # W1 pays ExA's deposit address, which sweeps to ExA's wallet
    tx(1, "W1", "DEP_A", 1000, 0), tx(2, "DEP_A", "HOT_A", 1000, 3),
    # W2 pays the same address a little, and most to a friend who pays ExB
    tx(3, "W2", "DEP_A", 100, 10), tx(4, "DEP_A", "HOT_A", 100, 13),
    tx(5, "W2", "FRIEND", 900, 11), tx(6, "FRIEND", "HOT_B", 900, 90),
    # W3 pays ExA's other deposit address, and ExB's wallet directly
    tx(7, "W3", "DEP_A2", 500, 20), tx(8, "DEP_A2", "HOT_A", 500, 25),
    tx(9, "W3", "HOT_B", 500, 21),
    # not eligible: too little, labelled, the zero address
    tx(10, "SMALL", "DEP_A", 5, 30), tx(11, "KNOWN", "DEP_A", 500, 31),
    tx(12, "0x0000", "DEP_A", 500, 32),
    # W4 pays ExB's wallet, which is a wallet that keeps the money
    tx(13, "W4", "HOT_B2", 700, 40),
]
CFG = B.BenchmarkConfig()


def labels():
    return ToyLabels(LABELS)


def exchange_labels():
    return [lab for lab in labels().labels.values() if lab.category == "exchange"]


def sample(**kw):
    cfg = B.BenchmarkConfig(**kw) if kw else CFG
    return B.sample_chain(CHAIN, exchange_labels(), ToyProvider(ROWS), labels(), cfg)


def row_for(wallet, picked=None):
    picked = picked or sample()[0]
    item = next(p for p in picked if p["wallet"] == wallet)
    return B.trace_wallet(item, CHAIN, ToyProvider(ROWS), labels())


def test_exchanges_are_ranked_by_how_many_labelled_addresses_they_have():
    ranked = B.exchanges_for(exchange_labels(), B.BenchmarkConfig(top_exchanges=1))
    assert [(e, len(labs)) for e, labs in ranked] == [("ExA", 3)]


def test_senders_of_labelled_addresses_are_sampled_and_the_ineligible_left_out():
    picked, report = sample()
    assert sorted(p["wallet"] for p in picked) == ["FRIEND", "W1", "W2", "W3", "W4"]
    w3 = next(p for p in picked if p["wallet"] == "W3")
    assert (w3["paid"], w3["tx"], w3["asset"], w3["exchange"]) == ("DEP_A2", "tx7", "USDT", "ExA")
    a = report["exchanges"][0]
    assert (a["exchange"], a["labelled_addresses"], a["wallets"], a["quota"]) == ("ExA", 3, 3, 12)


def test_the_sample_is_the_same_every_time_and_round_robin_spreads_it(monkeypatch):
    assert sample() == sample()
    monkeypatch.setitem(B.QUOTA, CHAIN, 2)
    picked, _ = sample()
    exa = [p for p in picked if p["exchange"] == "ExA"]
    # one sender from each of the two addresses that have one, not two from the first
    assert sorted(p["paid"] for p in exa) == ["DEP_A", "DEP_A2"]


def test_a_wallet_is_taken_once_even_if_it_paid_two_exchanges():
    picked, _ = sample()
    assert len({p["wallet"] for p in picked}) == len(picked)
    assert next(p for p in picked if p["wallet"] == "W3")["exchange"] == "ExA"


def test_with_the_paid_label_hidden_the_exchange_is_found_one_hop_further():
    r = row_for("W1")
    assert (r["named"], r["right"], r["hops"], r["known"]) == ("ExA", 1, 2, "ExA")
    assert (r["base_named"], r["base_right"]) == ("ExA", 1)
    assert r["hidden"] == 1 and r["outcome"] == "ATTRIBUTED"


def test_a_directly_paid_label_of_another_exchange_is_hidden_and_known():
    r = row_for("W3")
    assert r["known"] == "ExA|ExB" and r["hidden"] == 2
    assert (r["named"], r["hops"], r["right"]) == ("ExA", 2, 1)


def test_the_baseline_names_what_our_bar_does_not():
    r = row_for("W2")
    # 90% went through a friend to ExB (wrong); 10% through the hidden address to ExA
    assert r["base_named"] != "" and r["candidates"] == 2
    scored = B.measure([r], CHAIN)
    assert scored["baseline"]["named"] == 1


def test_a_wallet_whose_exchange_cannot_be_found_again_is_not_named():
    r = row_for("W4")
    assert (r["named"], r["base_named"], r["known"]) == ("", "", "ExB")
    assert r["stopped"].startswith("unspent")


def test_the_figures_count_wallets_and_bound_the_error():
    rows = [row_for(w) for w in ("W1", "W2", "W3", "W4")]
    m = B.measure(rows, CHAIN)
    assert (m["wallets"], m["ours"]["named"] + m["ours"]["not_named"]) == (4, 4)
    assert m["ours"]["by_hops"][0]["hops"] == 2
    assert m["not_named_because"].get("unspent") == 1
    assert B.upper_bound(0, 0) is None and B.upper_bound(3, 3) == 1.0
    assert B.upper_bound(15, 155) == 0.1451
    assert m["calibration"]["available"] is False


def test_calibration_bins_and_brier():
    rows = [{"base_named": "X", "base_confidence": c, "base_right": ok}
            for c, ok in [(0.2, 0)] * 6 + [(0.7, 1)] * 5 + [(0.7, 0)] * 3 + [(0.95, 1)] * 8]
    c = B.calibration(rows)
    assert c["wallets_with_a_confidence"] == 22 and c["available"]
    assert [b["wallets"] for b in c["bins"]] == [6, 0, 8, 0, 8]
    assert c["bins"][2]["observed"] == 0.625 and c["informative"] is True


def test_seconds_of_the_first_live_trace_survive_a_replay(tmp_path):
    picked, _ = sample()
    class Stats:                       # a fetcher that served everything from its cache
        stats = {"live": 0, "hits": 0, "retries": 0}
    first = B.collect(picked, CHAIN, ToyProvider(ROWS), labels(), fetcher=Stats())
    for r in first:
        r["seconds"] = 9.5
    B.write_csv(tmp_path / "w.csv", first, B.COLUMNS)
    again = B.collect(picked, CHAIN, ToyProvider(ROWS), labels(), fetcher=Stats(),
                      earlier=B.read_csv(tmp_path / "w.csv"))
    assert {r["seconds"] for r in again} == {9.5}
    B.write_csv(tmp_path / "w2.csv", again, B.COLUMNS)
    assert (tmp_path / "w.csv").read_text() == (tmp_path / "w2.csv").read_text()


def test_the_tron_row_is_the_tracked_run():
    claims = read_claims(ROOT / "artifacts" / "abstain_v1" / "tron" / "claims.csv")
    m = B.measure(B.tron_rows(claims, 0.60), "tron")
    assert (m["wallets"], m["ours"]["named"], m["ours"]["wrong"]) == (280, 155, 15)
    assert m["baseline"]["named"] >= m["ours"]["named"]
    assert m["median_seconds"] is None
