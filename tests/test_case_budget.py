"""The budget in a case: what the receipt records, what the officer is told, and that a
case traced under a changed budget (or ended by a time limit) still verifies.
A recorded demo wallet; no network."""
from datetime import datetime, timezone

import pytest

from demokit import SPECS, DemoLabels, demo_fetcher, demo_provider
from vaspfusion import cases as C
from vaspfusion.api import schemas as S
from vaspfusion.classify.runtime import make_scorer
from vaspfusion.explain.case_file import limitations
from vaspfusion.trace import TraceConfig, trace

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
WALLET = "eth-abstain"          # reads several wallets at the default budget


def run(cache, **budget) -> dict:
    spec = SPECS[WALLET]
    fetcher = demo_fetcher(cache, WALLET)
    cfg = TraceConfig(max_hops=spec["max_hops"], **budget)
    return C.run_case(spec["address"], spec["chain"], demo_provider(spec["chain"], fetcher, cfg),
                      DemoLabels(), case_id=WALLET, cfg=cfg, fetcher=fetcher, now=NOW,
                      scorer=make_scorer(spec["chain"], fetcher, key="test-key"))


def verify(case, cache) -> dict:
    return C.verify_stored(case, demo_fetcher(cache, offline=True), DemoLabels(), now=NOW,
                           key="test-key")


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    return tmp_path_factory.mktemp("budget") / "cache.duckdb"


@pytest.fixture(scope="module")
def default(cache):
    return run(cache)


def test_the_default_budget_leaves_the_receipt_input_as_it_always_was(default):
    prov = default["provenance"]
    assert set(prov["input"]) == {"address", "chain", "max_hops", "since"}
    budget = S.TraceBudget.model_validate(prov["budget"])
    assert (budget.max_wallets, budget.max_seconds, budget.ended_by) == (40, None, None)
    assert budget.wallets_read >= 2 and budget.share_not_followed == 0
    assert budget.text.startswith("The budget did not end this trace: it read ")
    assert not any("budget, not the evidence" in line for line in limitations(default))


def test_a_small_budget_says_it_ended_the_trace_and_how_much_it_left(cache, default):
    case = run(cache, max_nodes=1)
    prov = case["provenance"]
    assert prov["input"]["max_wallets"] == 1 and "max_seconds" not in prov["input"]
    assert prov["input_sha256"] != default["provenance"]["input_sha256"]
    budget = prov["budget"]
    assert (budget["ended_by"], budget["ended_side"], budget["wallets_read"]) == \
        ("wallets", "outbound", 1)
    assert 0 < budget["share_not_followed"] <= 1
    assert budget["text"].startswith("The budget, not the evidence, ended this trace: it "
                                     "reached its budget of 1 wallets on the way out. ")
    assert budget["text"].endswith("Trace the wallet again with a larger budget to follow them.")
    slices = {s["kind"]: s["share"] for s in case["where_funds_went"]}
    assert slices["not_followed"] >= budget["share_not_followed"]
    assert budget["text"] in limitations(case)
    assert any("after 1 wallets" in line for line in limitations(case))
    assert prov["findings_sha256"] != default["provenance"]["findings_sha256"]


def test_a_case_traced_under_a_changed_budget_verifies(cache):
    case = run(cache, max_nodes=1)
    result = verify(case, cache)
    assert result["matches"] is True, result["summary"]


def test_a_budget_larger_than_the_trace_needs_gives_the_default_findings(cache, default):
    case = run(cache, max_nodes=500)
    assert case["provenance"]["input"]["max_wallets"] == 500
    assert case["provenance"]["findings_sha256"] == default["provenance"]["findings_sha256"]
    assert case["provenance"]["budget"]["ended_by"] is None


class Ticks:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def test_a_case_a_time_limit_ended_records_where_and_verifies(cache, default, monkeypatch):
    clock = Ticks()
    monkeypatch.setattr(C, "trace", lambda *a, **k: trace(*a, **k, clock=clock))
    case = run(cache, max_seconds=1.5)           # one wallet is asked for, then time is up
    monkeypatch.undo()
    prov = case["provenance"]
    assert prov["input"]["max_seconds"] == 1.5 and prov["input"]["stopped_after"] == [1, None]
    assert "max_wallets" not in prov["input"]
    assert prov["budget"]["ended_by"] == "time"
    assert "its time budget of 1.5 seconds" in prov["budget"]["text"]
    S.CaseDetail.model_validate(case)
    result = verify(case, cache)                 # replayed with no clock at all
    assert result["matches"] is True, (result["summary"], result["checks"])
    assert prov["findings_sha256"] != default["provenance"]["findings_sha256"]


# ------------------------------------------------------------ across a bridge
BRIDGED = "eth-bridge"          # real: 60% of it came out on Base


def run_bridged(cache, **budget) -> dict:
    spec = SPECS[BRIDGED]
    fetcher = demo_fetcher(cache, BRIDGED)
    cfg = TraceConfig(max_hops=spec["max_hops"], **budget)
    return C.run_case(spec["address"], spec["chain"], demo_provider(spec["chain"], fetcher, cfg),
                      DemoLabels(), case_id=BRIDGED, cfg=cfg, fetcher=fetcher, now=NOW,
                      scorer=make_scorer(spec["chain"], fetcher, key="test-key"),
                      provider_opts={"key": "test-key"})


def test_the_wallets_read_past_a_bridge_come_out_of_the_same_budget(cache):
    whole = run_bridged(cache)
    assert whole["chains"] == ["ethereum", "base"]
    read = whole["provenance"]["budget"]["wallets_read"]
    case = run_bridged(cache, max_nodes=read - 1)
    budget = case["provenance"]["budget"]
    assert (budget["ended_by"], budget["wallets_read"]) == ("wallets", read - 1)
    assert case["chains"] == ["ethereum", "base"]        # the crossing itself is still shown
    result = verify(case, cache)
    assert result["matches"] is True, result["summary"]


def test_a_time_limit_that_ends_a_bridged_trace_replays_exactly(cache, monkeypatch):
    clock = Ticks()
    monkeypatch.setattr(C, "trace", lambda *a, **k: trace(*a, **k, clock=clock))
    case = run_bridged(cache, max_seconds=2.5)
    monkeypatch.undo()
    prov = case["provenance"]
    assert prov["budget"]["ended_by"] == "time" and prov["input"]["stopped_after"] == [2, None]
    assert case["chains"] == ["ethereum", "base"]
    result = verify(case, cache)                 # replayed with no clock at all
    assert result["matches"] is True, (result["summary"], result["checks"])
