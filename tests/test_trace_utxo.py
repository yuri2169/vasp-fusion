"""The trace on UTXO transactions: what is followed and what is not, miner fees, change,
cluster labels on the trail, and what the rules and the counterfactual make of them.
Toy transactions (utxokit.py)."""
import random
from datetime import timedelta
from decimal import Decimal

import pytest

from tracekit import ToyLabels
from utxokit import T0, ToyUtxoProvider, utx
from vaspfusion.attribute.counterfactual import add_counterfactuals
from vaspfusion.attribute.rules import RuleConfig, attribute
from vaspfusion.cases import build_case
from vaspfusion.cluster import ClusterLabels
from vaspfusion.explain.case_narrative import narrative
from vaspfusion.trace import TraceConfig, trace

EX = {"HOT": ("ExA", "exchange", "hot", "published_por")}
EXB = {"EXB": ("ExB", "exchange", "deposit", "curated")}


def sats(n):
    return Decimal(n).scaleb(-8)


def run(txs, labelled=EX, fail=(), unread=(), origin="S", **cfg):
    provider = ToyUtxoProvider(txs, fail=fail, unread=unread)
    labels = ClusterLabels(ToyLabels(labelled), provider)
    cfg = TraceConfig(**cfg)
    tr = trace(origin, "bitcoin", provider, labels, cfg)
    tr.provider, tr.labels = provider, labels
    return tr


def out(tr, address):
    return tr.nodes[("outbound", address)]


def flags(att, code):
    return [f for f in att.flags if f["code"] == code]


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


def test_traced_money_that_is_part_of_a_bigger_spend_goes_to_every_output_in_proportion():
    """M got 0.01 BTC from S and 0.09 from elsewhere, and spends all 0.1 in one
    transaction. Its outputs happen at once: the traced tenth goes to each of them (and
    to the fee) in proportion, whatever the addresses are called."""
    def case(first, second):
        tr = run([utx(1, [("S", 1_001_000)], [("M", 1_000_000)]),
                  utx(2, [("ELSE", 9_001_000)], [("M", 9_000_000)]),
                  utx(3, [("M", 1_000_000), ("M", 9_000_000)],
                      [(first, 5_000_000), (second, 4_999_000)], minute=5)], max_hops=2)
        return out(tr, first).received, out(tr, second).received, out(tr, "M").holds
    assert case("AAA", "ZZZ") == (sats(500_000), sats(499_900), {"fee": sats(100)})
    assert case("ZZZ", "AAA") == (sats(500_000), sats(499_900), {"fee": sats(100)})


# ------------------------------------------------------------------ what is not followed
def test_coins_pooled_with_other_wallets_coins_stop_where_they_were_pooled():
    """S deposits at D. D's owner sweeps it with other deposits AND pays W in the same
    transaction; W then pays ExB. S's coins did not pay W: nothing says so on the chain."""
    txs = [utx(1, [("S", 400_000)], [("D", 399_000)]),
           utx(2, [("D", 399_000)] + [(f"D{i}", 100_000) for i in range(9)],
               [("SVC", 890_000), ("W", 400_000)], minute=10),
           utx(3, [("W", 400_000)], [("EXB", 399_000)], minute=30)]
    tr = run(txs, labelled=EXB)
    assert ("outbound", "W") not in tr.nodes and ("outbound", "EXB") not in tr.nodes
    d = out(tr, "D")
    assert set(d.holds) == {"pooled", "fee"} and sum(d.holds.values()) == sats(399_000)
    assert d.sunk == [("outbound", "pooled", "tx2", d.holds["pooled"])]
    att = attribute(tr)
    assert att.outcome == "INSUFFICIENT_EVIDENCE" and att.candidates == []
    assert "spent together with other addresses' coins" in att.abstain_reason
    assert any("D" in w and "pooled" in w for w in att.what_would_change)
    case = build_case(tr, att, case_id="t")
    assert {s["kind"] for s in case["where_funds_went"]} == {"not_followed", "fee"}


def test_a_sweep_into_one_destination_is_followed():
    txs = [utx(1, [("S", 100_000)], [("D", 99_000)]),
           utx(2, [("D", 99_000), ("D2", 50_000), ("D3", 10_000)], [("EXB", 158_000)], minute=10)]
    tr = run(txs, labelled=EXB)
    assert out(tr, "EXB").received == sats(158_000 * 99_000 // 159_000)
    assert attribute(tr).top.vasp == "ExB"


def test_a_consolidation_into_one_of_its_own_inputs_is_followed_to_that_address():
    # [M, M2] -> M2, then M2 pays the exchange: M's coins are at M2, not "still at M"
    txs = [utx(1, [("S", 100_000)], [("M", 99_000)]),
           utx(2, [("M", 99_000), ("M2", 50_000)], [("M2", 148_000)], minute=5),
           utx(3, [("M2", 148_000)], [("HOT", 147_000)], minute=9)]
    tr = run(txs)
    assert "unspent" not in out(tr, "M").holds
    c = attribute(tr).top
    assert (c.vasp, c.hops) == ("ExA", 3)


def test_the_traced_wallets_own_multi_address_spend_is_split():
    txs = [utx(1, [("S", 60_000), ("S2", 40_000)], [("X", 50_000), ("Y", 30_000)])]
    tr = run(txs, max_hops=1)
    assert tr.total_out == sats(48_000)
    assert (out(tr, "X").received, out(tr, "Y").received) == (sats(30_000), sats(18_000))


def test_a_traced_wallet_whose_every_spend_is_pooled_says_so():
    txs = [utx(1, [("S", 20_000)] + [(f"S{i}", 20_000) for i in range(4)],
               [("X", 50_000), ("Y", 49_000)])]
    tr = run(txs)
    assert tr.total_out == sats(19_800) and tr.stopped == {"pooled": sats(19_800)}
    att = attribute(tr)
    assert att.outcome == "INSUFFICIENT_EVIDENCE"
    text = narrative(tr, att)
    assert "sent 0.000198 BTC" in text and "none of it could be followed" in text


def test_an_output_with_no_address_is_its_own_reason_not_unmoved_money():
    txs = [utx(1, [("S", 100_000)], [("M", 99_000)]),
           utx(2, [("M", 99_000)], [(None, 98_000)], minute=5)]
    tr = run(txs)
    assert out(tr, "M").holds == {"no_address": sats(98_000), "fee": sats(1_000)}
    assert "no address form" in attribute(tr).abstain_reason


MIX = utx(2, [(o, 1_100_000 + i) for i, o in enumerate(["M", "P2", "P3", "P4", "P5"])],
          [(f"mix{i}", 1_000_000) for i in range(5)] + [(f"chg{i}", 99_000 + i) for i in range(5)],
          minute=5)


def test_a_coinjoin_shape_stops_the_trace_and_is_flagged_but_never_decides_the_outcome():
    tr = run([utx(1, [("S", 1_101_000)], [("M", 1_100_000)]), MIX])
    assert not [a for (_, a) in tr.nodes if a.startswith(("mix", "chg", "coinjoin"))]
    assert set(out(tr, "M").holds) == {"coinjoin", "fee"}
    att = attribute(tr)
    assert att.outcome == "INSUFFICIENT_EVIDENCE"          # a shape is not an alert
    assert not flags(att, "mixer_contact")
    f, = flags(att, "coinjoin_shape")
    assert (f["severity"], f["wallet"], f["tx_hashes"]) == ("warn", "M", ["tx2"])
    assert "shape of a CoinJoin" in f["text"] and "a rule, not a proof" in f["text"]
    assert "shape of a CoinJoin" in att.abstain_reason
    assert "Escalate" not in " ".join(att.next_steps)


def test_a_coinjoin_shape_does_not_displace_an_exchange_that_was_reached():
    # S sends 60% straight to the exchange and 40% through M into a join
    tr = run([utx(1, [("S", 2_751_000)], [("HOT", 1_650_000), ("M", 1_100_000)]), MIX])
    att = attribute(tr)
    assert (att.outcome, att.top.vasp) == ("ATTRIBUTED", "ExA")
    assert flags(att, "coinjoin_shape")


def test_money_that_came_out_of_a_coinjoin_or_a_block_reward_has_no_funder_wallet():
    mix = utx(1, [(o, 1_100_000 + i) for i, o in enumerate(["P1", "P2", "P3", "P4", "P5"])],
              [("S", 1_000_000)] + [(f"mix{i}", 1_000_000) for i in range(4)]
              + [(f"chg{i}", 99_000 + i) for i in range(5)])
    txs = [mix, utx(2, [(None, 0)], [("S", 5_000_000)], minute=1, coinbase=True),
           utx(3, [("S", 6_000_000)], [("X", 5_999_000)], minute=9)]
    tr = run(txs)
    assert not [a for (side, a) in tr.nodes if side == "inbound"]
    assert tr.stopped_in == {"coinjoin": sats(1_000_000), "mined": sats(5_000_000)}
    f, = flags(attribute(tr), "coinjoin_shape")
    assert "of what the wallet received" in f["text"] and f["tx_hashes"] == ["tx1"]


# ------------------------------------------------------------------ unread histories
def test_a_wallet_too_busy_to_read_back_to_the_arrival_is_not_followed():
    txs = [utx(1, [("S", 100_000)], [("M", 99_000)]),
           utx(2, [("M", 99_000)], [("EXB", 98_000)], minute=500)]   # long after, and unread
    tr = run(txs, labelled=EXB, unread={"M"})
    assert out(tr, "M").holds == {"truncated": sats(99_000)}
    assert attribute(tr).candidates == []


def test_a_traced_wallet_that_cannot_be_read_back_to_the_start_date_says_so():
    txs = [utx(1, [("S", 100_000)], [("X", 99_000)])]
    tr = run(txs, unread={"S"}, since=T0 - timedelta(days=30))
    assert tr.asset is None and tr.total_out == 0
    att = attribute(tr)
    assert att.outcome == "INSUFFICIENT_EVIDENCE"
    assert "could not be read back to 2 Dec 2025" in att.abstain_reason
    assert "has not sent any funds" not in narrative(tr, att)


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


def test_a_request_names_the_exchanges_address_not_the_wallet_that_paid_it():
    """M forwards everything to D, and D is ExA's by its cluster. D is the address ExA
    can look up; M is whoever paid it, not "the customer's deposit address"."""
    txs = [utx(1, [("S", 101_000)], [("M", 100_000)]),
           utx(5, [("M", 100_000)], [("D", 99_000)], minute=3), *SWEEP[1:]]
    tr = run(txs)
    att = attribute(tr)
    c = att.top
    assert (c.vasp, c.hops, c.deposit_address, c.label.kind) == ("ExA", 2, "D", "unknown")
    assert [(w["address"], w["paid_into"]) for w in c.request_wallets] == [("D", None)]
    assert "that received the funds at D" in att.next_steps[0]
    case = build_case(tr, att, case_id="t")
    node = next(n for n in case["graph"]["nodes"] if n["id"] == "D")
    assert node["role"] == "exchange"


def test_a_directly_labelled_wallet_is_not_clustered():
    tr = run(SWEEP, labelled={**EX, "D": ("ExB", "exchange", "deposit", "curated")})
    assert out(tr, "D").label.entity == "ExB"
    assert ("txs", "D") not in tr.provider.calls


def test_the_traced_wallet_itself_can_be_an_exchange_address_by_its_cluster():
    tr = run(SWEEP, origin="D")
    assert tr.origin_label.entity == "ExA" and "not traced" in tr.notes[0]
    assert attribute(tr).candidates[0].hops == 0


def test_a_wallet_holding_too_little_of_the_funds_is_not_clustered():
    txs = [utx(1, [("S", 1_000_000)], [("BIG", 995_000), ("D", 4_000)]), *SWEEP[1:]]
    tr = run(txs)
    assert out(tr, "D").label is None and out(tr, "D").state == "small"
    assert ("txs", "D") not in tr.provider.calls


def test_a_wallet_that_was_too_small_and_is_then_named_holds_all_its_money_as_labelled():
    """D first gets 0.5% (too small to look at), then 99% by another route. Once its
    cluster names it, everything it holds is at a labelled wallet: counted once."""
    txs = [utx(1, [("S", 2_001_000)], [("D", 10_000), ("N", 1_990_000)]),
           utx(2, [("N", 1_990_000)], [("D", 1_989_000)], minute=2),
           utx(3, [("D", 10_000), ("D", 1_989_000), ("HOT", 5_000)], [("COLD", 2_003_000)],
               minute=10)]
    tr = run(txs)
    d = out(tr, "D")
    assert d.label.entity == "ExA" and d.state == "labelled"
    assert d.holds == {"labelled": sats(1_999_000)}
    assert sum(tr.stopped.values()) == tr.total_out and "small" not in tr.stopped
    case = build_case(tr, attribute(tr), case_id="t")
    assert abs(sum(s["share"] for s in case["where_funds_went"]) - 1) < 1e-3


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
def cf(tr):
    att = attribute(tr)
    add_counterfactuals(tr, att, tr.provider, tr.labels, TraceConfig(), RuleConfig())
    return att.top


def test_without_the_cluster_label_the_money_is_followed_to_where_it_was_swept():
    top = cf(run(SWEEP, labelled={**EX, "COLD": ("ExA", "exchange", "cold", "published_por")}))
    assert top.deposit_address == "D" and top.counterfactual_holds is True
    assert "COLD" in top.counterfactual


def test_hiding_one_cluster_label_leaves_the_other_wallets_clusters_in_place():
    # D is swept into Z, and Z is later spent together with HOT: Z is ExA's by its own cluster
    txs = [*SWEEP[:1],
           utx(2, [("D", 99_000), ("D2", 50_000), ("HOT", 10_000)], [("Z", 158_000)], minute=10),
           utx(3, [("Z", 158_000), ("HOT", 5_000)], [("COLD", 162_000)], minute=20)]
    top = cf(run(txs))
    assert top.deposit_address == "D" and top.counterfactual_holds is True
    assert "at Z" in top.counterfactual and "2 hops" in top.counterfactual


def test_a_cluster_label_with_nothing_behind_it_says_so():
    top = cf(run(SWEEP))
    assert top.counterfactual_holds is False
    assert "rests on that one label" in top.counterfactual


def test_a_sweep_that_pools_the_money_is_not_reported_as_not_reached():
    # without D's label its coins go into a sweep with several destinations: not followed,
    # so "ExA is not reached" would be a guess
    txs = [*SWEEP[:1],
           utx(2, [("D", 99_000), ("D2", 50_000), ("HOT", 10_000)],
               [("COLD", 100_000), ("OUT", 58_000)], minute=10)]
    top = cf(run(txs))
    assert top.counterfactual_holds is None
    assert top.counterfactual.startswith("Not checked") and "pooled" in top.counterfactual


# ------------------------------------------------------------------ nothing created, nothing lost
@pytest.mark.parametrize("seed", range(150))
def test_every_satoshi_the_wallet_sent_ends_in_exactly_one_place(seed):
    rng = random.Random(26182 + seed)
    names = ["S"] + [f"W{i}" for i in range(8)] + ["HOT"]
    balance = {"S": [rng.randrange(200_000, 3_000_000) for _ in range(rng.randint(1, 3))]}
    txs, minute = [], 0
    for n in range(1, rng.randint(4, 14)):
        minute += rng.randint(0, 6)
        funders = [a for a in rng.sample(sorted(balance), k=min(len(balance), rng.randint(1, 3)))
                   if balance[a]]
        if not funders:
            continue
        inputs = [(a, balance[a].pop(rng.randrange(len(balance[a])))) for a in funders]
        total = sum(v for _, v in inputs)
        fee = min(total // 2, rng.randrange(100, 2_000))
        outs, left = [], total - fee
        for _ in range(rng.randint(1, 4)):
            if left <= 1_000:
                break
            v = left if rng.random() < 0.3 else rng.randrange(1_000, left)
            outs.append((rng.choice(names + [None] * 1), v))
            left -= v
        if not outs:
            continue
        fee += left
        txs.append(utx(n, inputs, outs, minute=minute))
        for to, v in outs:
            if to is not None:
                balance.setdefault(to, []).append(v)
    tr = run(txs, max_hops=rng.randint(1, 5), inbound_hops=rng.randint(0, 2),
             fetch_limit=rng.choice([3, 100]), hub_degree=rng.choice([3, 30]))
    assert sum(tr.stopped.values(), Decimal(0)) == tr.total_out
    assert sum(tr.stopped_in.values(), Decimal(0)) == tr.total_in
    used: dict = {}
    for e in tr.edges:
        assert Decimal(0) < e.traced <= e.transfer.amount
        used[(e.side, e.transfer)] = used.get((e.side, e.transfer), Decimal(0)) + e.traced
    assert all(v <= t.amount for (_, t), v in used.items())
    for (side, _), n in tr.nodes.items():
        if side == "outbound":
            onward = sum((e.traced for e in tr.edges if e.side == "outbound"
                          and e.transfer.from_addr == n.address), Decimal(0))
            assert n.received == n.held + onward
        assert all(v > 0 for v in n.holds.values())
