"""The trace on UTXO transactions: miner fees, change, cluster labels on the trail, and
what the rules and the counterfactual make of them. Toy transactions (utxokit.py)."""
from decimal import Decimal

from tracekit import ToyLabels
from utxokit import ToyUtxoProvider, utx
from vaspfusion.attribute.counterfactual import add_counterfactuals
from vaspfusion.attribute.rules import RuleConfig, attribute
from vaspfusion.cases import build_case
from vaspfusion.cluster import ClusterLabels
from vaspfusion.trace import TraceConfig, trace

EX = {"HOT": ("ExA", "exchange", "hot", "published_por")}


def sats(n):
    return Decimal(n).scaleb(-8)


def run(txs, labelled=EX, fail=(), **cfg):
    provider = ToyUtxoProvider(txs, fail=fail)
    labels = ClusterLabels(ToyLabels(labelled), provider)
    cfg = TraceConfig(**cfg)
    tr = trace("S", "bitcoin", provider, labels, cfg)
    tr.provider, tr.labels = provider, labels
    return tr


def out(tr, address):
    return tr.nodes[("outbound", address)]


# ------------------------------------------------------------------ fees and change
def test_the_miner_fee_is_its_own_stop_reason_not_money_that_has_not_moved():
    tr = run([utx(1, [("S", 100_000)], [("M", 99_000)]),
              utx(2, [("M", 99_000)], [("X", 98_000)], minute=5)], max_hops=2)
    assert tr.total_out == sats(99_000)
    assert out(tr, "M").holds == {"fee": sats(1_000)}
    assert tr.stopped == {"fee": sats(1_000), "depth_limit": sats(98_000)}
    assert sum(tr.stopped.values()) == tr.total_out


def test_change_kept_by_a_wallet_has_not_moved_on():
    tr = run([utx(1, [("S", 100_000)], [("M", 99_000)]),
              utx(2, [("M", 99_000)], [("X", 30_000), ("M", 68_000)], minute=5)], max_hops=2)
    assert out(tr, "M").holds == {"fee": sats(1_000), "unspent": sats(68_000)}
    assert out(tr, "X").received == sats(30_000)


def test_a_fee_is_charged_once_when_a_wallet_is_reached_twice():
    # S pays M directly and through N; M then spends both coins in one transaction
    tr = run([utx(1, [("S", 200_000)], [("M", 100_000), ("N", 99_000)]),
              utx(2, [("N", 99_000)], [("M", 98_000)], minute=1),
              utx(3, [("M", 100_000), ("M", 98_000)], [("X", 196_000)], minute=9)], max_hops=3)
    assert out(tr, "M").holds == {"fee": sats(2_000)}
    assert out(tr, "X").received == sats(196_000)
    assert sum(tr.stopped.values()) == tr.total_out


def test_other_chains_have_no_fee_reason():
    from tracekit import CHAIN, ToyProvider, tx
    r = trace("S", CHAIN, ToyProvider([tx(1, "S", "M", 1000, 0), tx(2, "M", "X", 400, 5)]),
              ToyLabels({}), TraceConfig(max_hops=2))
    assert "fee" not in r.stopped and r.stopped["unspent"] == 600


# ------------------------------------------------------------------ cluster labels
# S pays D; D is swept with D2 and the exchange's labelled HOT wallet into COLD
SWEEP = [utx(1, [("S", 100_000)], [("D", 99_000)]),
         utx(2, [("D", 99_000), ("D2", 50_000), ("HOT", 10_000)], [("COLD", 158_000)], minute=10)]


def test_a_wallet_swept_with_a_labelled_exchange_address_ends_the_trace_as_that_exchange():
    tr = run(SWEEP)
    d = out(tr, "D")
    assert (d.state, d.label.entity, d.label.source) == ("labelled", "ExA", "vaspfusion-cluster")
    assert ("outbound", "COLD") not in tr.nodes                 # a labelled wallet is not expanded
    att = attribute(tr)
    assert (att.outcome, att.top.vasp, att.top.hops) == ("ATTRIBUTED", "ExA", 1)
    assert att.top.confidence == 0.855 and att.top.deposit_address == "D"
    assert "cluster of 3 addresses, 1 labelled ExA" in att.top.evidence[0]["text"]
    assert att.top.request_wallets[0]["address"] == "D"


def test_a_directly_labelled_wallet_is_not_clustered():
    tr = run(SWEEP, labelled={**EX, "D": ("ExB", "exchange", "deposit", "curated")})
    assert out(tr, "D").label.entity == "ExB"
    assert ("txs", "D") not in tr.provider.calls


def test_the_traced_wallet_itself_can_be_an_exchange_address_by_its_cluster():
    tr = trace("D", "bitcoin", (p := ToyUtxoProvider(SWEEP)), ClusterLabels(ToyLabels(EX), p))
    assert tr.origin_label.entity == "ExA" and "not traced" in tr.notes[0]
    assert attribute(tr).candidates[0].hops == 0


def test_a_wallet_holding_too_little_of_the_funds_is_not_clustered():
    txs = [utx(1, [("S", 1_000_000)], [("BIG", 995_000), ("D", 4_000)]), *SWEEP[1:]]
    tr = run(txs)
    assert out(tr, "D").label is None and out(tr, "D").state == "small"
    assert ("txs", "D") not in tr.provider.calls


def test_the_funder_of_the_wallet_is_clustered_too():
    txs = [utx(1, [("W1", 60_000), ("HOT", 50_000)], [("S", 100_000)]),
           utx(2, [("S", 100_000)], [("X", 99_000)], minute=5)]
    tr = run(txs)
    funder = tr.nodes[("inbound", "W1")]
    assert funder.label.entity == "ExA" and funder.label.source == "vaspfusion-cluster"
    assert [c.vasp for c in attribute(tr).candidates if c.direction == "inbound"] == ["ExA"]


def test_cluster_notes_reach_the_trace():
    tr = run(SWEEP, labelled={"HOT": ("ExA", "exchange"), "D2": ("ExB", "exchange")})
    assert out(tr, "D").label is None
    assert any("two owners" in n for n in tr.notes)


def test_a_coinjoin_ends_the_trace_as_a_mixer():
    owners = ["M", "P2", "P3", "P4", "P5"]
    mix = utx(2, [(o, 1_100_000 + i) for i, o in enumerate(owners)],
              [(f"mix{i}", 1_000_000) for i in range(5)]
              + [(f"chg{i}", 99_000 + i) for i in range(5)], minute=5)
    tr = run([utx(1, [("S", 1_101_000)], [("M", 1_100_000)]), mix])
    sink = out(tr, "coinjoin:tx2")
    assert sink.label.category == "mixer" and sink.state == "labelled"
    assert not [a for (_, a) in tr.nodes if a.startswith("mix") or a.startswith("chg")]
    att = attribute(tr)
    assert att.outcome == "SANCTIONED_OR_MIXER_REACHED"
    assert any(f["code"] == "mixer_contact" for f in att.flags)


# ------------------------------------------------------------------ rules
def test_passing_everything_on_is_judged_net_of_the_fee():
    # M forwards all it got to the exchange's labelled hot wallet, less the miner fee
    tr = run([utx(1, [("S", 100_000)], [("M", 99_000)]),
              utx(2, [("M", 99_000)], [("HOT", 98_000)], minute=5)])
    c = attribute(tr).top
    assert (c.vasp, c.hops, c.passed_all) == ("ExA", 2, True)
    assert [w["address"] for w in c.request_wallets] == ["M"]


def test_the_fee_is_a_slice_of_where_the_funds_went():
    tr = run([utx(1, [("S", 100_000)], [("M", 99_000)]),
              utx(2, [("M", 99_000)], [("HOT", 98_000)], minute=5)])
    case = build_case(tr, attribute(tr), case_id="t")
    kinds = {s["kind"]: s["amount"] for s in case["where_funds_went"]}
    assert kinds == {"vasp": 0.00098, "fee": 0.00001}
    assert abs(sum(s["share"] for s in case["where_funds_went"]) - 1) < 1e-3


# ------------------------------------------------------------------ counterfactual
def test_without_the_cluster_label_the_money_is_followed_to_where_it_was_swept():
    labelled = {**EX, "COLD": ("ExA", "exchange", "cold", "published_por")}
    tr = run(SWEEP, labelled=labelled)
    att = attribute(tr)
    assert att.top.deposit_address == "D"
    add_counterfactuals(tr, att, tr.provider, tr.labels, TraceConfig(), RuleConfig())
    assert att.top.counterfactual_holds is True
    assert "COLD" in att.top.counterfactual


def test_hiding_one_cluster_label_leaves_the_other_wallets_clusters_in_place():
    # D is swept into Z, and Z is later spent together with HOT: Z is ExA's by its own cluster
    txs = [*SWEEP[:1],
           utx(2, [("D", 99_000), ("D2", 50_000), ("HOT", 10_000)], [("Z", 158_000)], minute=10),
           utx(3, [("Z", 158_000), ("HOT", 5_000)], [("COLD", 162_000)], minute=20)]
    tr = run(txs)
    att = attribute(tr)
    add_counterfactuals(tr, att, tr.provider, tr.labels, TraceConfig(), RuleConfig())
    assert att.top.deposit_address == "D" and att.top.counterfactual_holds is True
    assert "at Z" in att.top.counterfactual and "2 hops" in att.top.counterfactual


def test_a_cluster_label_with_nothing_behind_it_says_so():
    tr = run(SWEEP)
    att = attribute(tr)
    add_counterfactuals(tr, att, tr.provider, tr.labels, TraceConfig(), RuleConfig())
    assert att.top.counterfactual_holds is False
    assert "rests on that one label" in att.top.counterfactual
