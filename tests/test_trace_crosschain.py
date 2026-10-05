"""The trace across a bridge: a deposit matched to its payout goes on from the recipient
on the destination chain. Toy transfers on two toy chains (tracekit.py); the bridge's
answers are hand-written here, the real ones are in tests/chains/test_bridges.py."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

from tracekit import CHAIN, T0, ToyProvider, tx
from vaspfusion.chains.base import UnsupportedChain
from vaspfusion.chains.bridges import BridgeHop, Unresolved
from vaspfusion.labels.lookup import Label
from vaspfusion.trace import TraceConfig, trace

FAR = "far"


def ftx(n, frm, to, amount, minute, asset="USDC"):
    """A transfer on the other chain."""
    return replace(tx(n, frm, to, amount, minute, asset), chain=FAR)


class Labels:
    """{(address, chain): (entity, category[, kind])}: the same address may be two wallets."""

    def __init__(self, labels):
        self.labels = {
            (a, c): Label(address=a, chain=c, entity=spec[0], category=spec[1],
                          kind=spec[2] if len(spec) > 2 else "unknown", tier="curated",
                          source="toy", source_url=None, label=f"{spec[0]} toy label")
            for (a, c), spec in labels.items()}
        self.asked: list[tuple] = []

    def lookup_many(self, pairs):
        pairs = list(pairs)
        self.asked += pairs
        return {p: self.labels[p] for p in pairs if p in self.labels}


class Bridges:
    """Answers like chains.bridges.Crossings."""

    def __init__(self, hops, providers):
        self.hops, self.providers, self.asked = hops, providers, []

    def resolve(self, entity, transfer):
        self.asked.append((entity, transfer.tx_hash))
        return self.hops.get(transfer.tx_hash, Unresolved("the index holds no deposit"))

    def provider(self, chain):
        if chain not in self.providers:
            raise UnsupportedChain(f"no adapter for chain {chain!r}")
        return self.providers[chain]


def hop(deposit, recipient, payout, minute, dest=FAR, name=None):
    return BridgeHop(bridge="ToyBridge", source_chain=CHAIN, source_tx=deposit, dest_chain=dest,
                     dest_name=name or dest or "?", recipient=recipient, payout_tx=payout,
                     paid_at=T0 + timedelta(minutes=minute),
                     deposited_at=T0 + timedelta(minutes=minute - 1), source="toy.index")


BASE_LABELS = {("BR", CHAIN): ("ToyBridge", "bridge"), ("HOT", FAR): ("ExA", "exchange")}


def run(home, far, hops, labels=None, providers=None, **cfg):
    far_provider = ToyProvider(far)
    far_provider.chain = FAR
    bridges = Bridges(hops, {FAR: far_provider} if providers is None else providers)
    labels = Labels(BASE_LABELS if labels is None else labels)
    r = trace("S", CHAIN, ToyProvider(home), labels, TraceConfig(**cfg), crossings=bridges)
    r.bridges, r.far, r.labels = bridges, far_provider, labels
    return r


def out(r, wallet):
    return r.nodes[("outbound", wallet)]


def test_a_matched_deposit_goes_on_from_the_recipient_on_the_other_chain():
    r = run([tx(1, "S", "BR", 1000, 0)],
            [ftx(2, "PAYER", "R", 997, 1), ftx(3, "R", "HOT", 997, 5)],
            {"tx1": hop("tx1", "R", "tx2", 1)})
    bridge, rcpt, hot = out(r, "BR"), out(r, "far:R"), out(r, "far:HOT")
    assert (bridge.state, bridge.hop, bridge.received) == ("labelled", 1, D(1000))
    assert (rcpt.chain, rcpt.hop, rcpt.state, rcpt.received) == (FAR, 2, "expanded", D(997))
    assert (hot.chain, hot.hop, hot.received, hot.label.entity) == (FAR, 3, D(997), "ExA")
    assert [e.transfer.tx_hash for e in r.path_to("outbound", "far:HOT")] == ["tx1", "tx2", "tx3"]
    assert r.chains == [CHAIN, FAR]


def test_the_cross_chain_edge_is_the_payout_drawn_from_the_bridge_wallet():
    r = run([tx(1, "S", "BR", 1000, 0)], [ftx(2, "PAYER", "R", 997, 1)],
            {"tx1": hop("tx1", "R", "tx2", 1)})
    (edge,) = r.edges_into("outbound", "far:R")
    t = edge.transfer
    assert (t.chain, t.tx_hash, t.from_addr, t.to_addr, t.asset, t.amount) == \
        (FAR, "tx2", "BR", "far:R", "USDC", D(997))
    leg = edge.crossing
    assert (leg.status, leg.bridge_wallet, leg.entity, leg.deposit.tx_hash) == \
        ("followed", "BR", "ToyBridge", "tx1")
    assert (leg.traced_in, leg.traced_out, leg.payout.from_addr) == (D(1000), D(997), "far:PAYER")
    assert r.crossings == [leg]


def test_what_did_not_come_out_is_the_bridges_fee_and_nothing_is_missing():
    r = run([tx(1, "S", "BR", 1000, 0)], [ftx(2, "PAYER", "R", 997, 1)],
            {"tx1": hop("tx1", "R", "tx2", 1)})
    assert out(r, "BR").holds == {"bridge_fee": D(3)}
    assert r.stopped == {"bridge_fee": D(3), "unspent": D(997)}
    assert sum(r.stopped.values()) == r.total_out


def test_the_recipient_may_be_the_same_address_as_the_wallet_itself():
    # an EVM wallet bridging to itself: one address, two wallets
    r = run([tx(1, "S", "BR", 1000, 0)], [ftx(2, "PAYER", "S", 990, 1), ftx(3, "S", "HOT", 990, 3)],
            {"tx1": hop("tx1", "S", "tx2", 1)})
    assert out(r, "far:S").received == D(990) and "returned" not in r.stopped
    assert out(r, "far:HOT").received == D(990)
    assert r.nodes[("origin", "S")].chain is None


def test_labels_are_looked_up_on_the_chain_the_wallet_is_on():
    r = run([tx(1, "S", "BR", 1000, 0)],
            [ftx(2, "PAYER", "R", 997, 1), ftx(3, "R", "HOT", 997, 5)],
            {"tx1": hop("tx1", "R", "tx2", 1)},
            labels={**BASE_LABELS, ("R", CHAIN): ("Elsewhere", "exchange")})
    assert ("R", FAR) in r.labels.asked and ("HOT", FAR) in r.labels.asked
    assert out(r, "far:R").label is None        # the label is for the address on the home chain


def test_only_the_traced_part_of_a_deposit_crosses():
    # M1 deposits 4,000 of which 1,000 is the wallet's: a quarter of the payout is followed
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "X", "M1", 3000, 1), tx(3, "M1", "BR", 4000, 2)],
            [ftx(4, "PAYER", "R", 3980, 3)], {"tx3": hop("tx3", "R", "tx4", 3)})
    assert out(r, "far:R").received == D(995)
    assert out(r, "BR").holds == {"bridge_fee": D(5)}


def test_a_payout_larger_than_the_deposit_does_not_create_money():
    r = run([tx(1, "S", "BR", 1000, 0)], [ftx(2, "PAYER", "R", 1001, 1)],
            {"tx1": hop("tx1", "R", "tx2", 1)})
    assert out(r, "far:R").received == D(1000) and out(r, "BR").held == 0


def test_an_unmatched_deposit_stays_at_the_bridge_as_before():
    r = run([tx(1, "S", "BR", 1000, 0)], [], {})
    assert (out(r, "BR").held, out(r, "BR").holds) == (D(1000), {"labelled": D(1000)})
    (leg,) = r.crossings
    assert (leg.status, leg.reason, leg.hop) == ("unresolved", "the index holds no deposit", None)
    assert r.chains == [CHAIN] and len(r.edges) == 1


def test_without_crossings_a_bridge_is_where_the_trail_ends():
    r = trace("S", CHAIN, ToyProvider([tx(1, "S", "BR", 1000, 0)]), Labels(BASE_LABELS))
    assert out(r, "BR").holds == {"labelled": D(1000)} and r.crossings == []


def test_a_destination_without_an_adapter_names_the_chain_and_recipient():
    r = run([tx(1, "S", "BR", 1000, 0)], [],
            {"tx1": hop("tx1", "R", "tx2", 1, dest=None, name="Linea")})
    (leg,) = r.crossings
    assert (leg.status, leg.reason) == ("not_traced", "Linea is not a chain this tool reads")
    assert (leg.hop.recipient, leg.hop.payout_tx) == ("R", "tx2")
    assert out(r, "BR").holds == {"labelled": D(1000)}


def test_a_destination_whose_adapter_cannot_be_built_is_not_traced():
    r = run([tx(1, "S", "BR", 1000, 0)], [], {"tx1": hop("tx1", "R", "tx2", 1)}, providers={})
    (leg,) = r.crossings
    assert leg.status == "not_traced" and "could not be read (no adapter for chain 'far')" \
        in leg.reason


def test_a_payout_that_is_not_on_the_recipients_listing_is_not_followed():
    r = run([tx(1, "S", "BR", 1000, 0)], [ftx(9, "PAYER", "R", 997, 1)],
            {"tx1": hop("tx1", "R", "tx2", 1)})
    (leg,) = r.crossings
    assert leg.status == "not_traced" and leg.reason.startswith("the payout transaction shows")
    assert out(r, "BR").holds == {"labelled": D(1000)}


def test_a_change_of_asset_is_named_and_not_followed():
    r = run([tx(1, "S", "BR", 1000, 0)], [ftx(2, "PAYER", "R", "0.4", 1, asset="COIN")],
            {"tx1": hop("tx1", "R", "tx2", 1)})
    (leg,) = r.crossings
    assert leg.status == "not_traced" and leg.payout.asset == "COIN"
    assert leg.reason == "it was paid out in COIN, and a change of asset from USDT is not followed"


def test_one_stablecoin_paid_out_as_another_is_followed_in_the_new_one():
    r = run([tx(1, "S", "BR", 1000, 0)],
            [ftx(2, "PAYER", "R", 997, 1), ftx(3, "R", "HOT", 997, 5)],
            {"tx1": hop("tx1", "R", "tx2", 1)})
    asked = [(c[0], c[3]) for c in r.far.calls if c[1] == "out"]
    assert asked == [("R", "USDC")]             # the adapter is asked by plain address


def test_the_crossing_is_a_hop_and_the_hop_limit_counts_it():
    home, far = [tx(1, "S", "BR", 1000, 0)], [ftx(2, "PAYER", "R", 997, 1),
                                               ftx(3, "R", "M", 997, 5), ftx(4, "M", "HOT", 997, 6)]
    hops = {"tx1": hop("tx1", "R", "tx2", 1)}
    r = run(home, far, hops, max_hops=3)
    assert out(r, "far:M").state == "depth_limit" and ("outbound", "far:HOT") not in r.nodes
    r = run(home, far, hops, max_hops=4)
    assert out(r, "far:HOT").hop == 4


def test_a_bridge_at_the_hop_limit_is_matched_but_not_crossed():
    r = run([tx(1, "S", "BR", 1000, 0)], [ftx(2, "PAYER", "R", 997, 1)],
            {"tx1": hop("tx1", "R", "tx2", 1)}, max_hops=1)
    (leg,) = r.crossings
    assert (leg.status, leg.reason) == ("not_traced", "the trace's limit of 1 hops was reached "
                                                      "at the bridge")
    assert r.far.calls == [] and out(r, "BR").holds == {"labelled": D(1000)}


def test_a_deposit_too_small_to_follow_is_not_asked_about():
    r = run([tx(1, "S", "BR", 5, 0), tx(2, "S", "M1", 995, 1)], [], {})
    assert r.bridges.asked == []
    assert r.crossings[0].reason == "it is too small a part of the funds to follow"


def test_two_deposits_to_one_recipient_are_followed_together():
    r = run([tx(1, "S", "BR", 400, 0), tx(2, "S", "BR", 600, 10)],
            [ftx(3, "PAYER", "R", 399, 1), ftx(4, "PAYER", "R", 598, 11),
             ftx(5, "R", "HOT", 997, 20)],
            {"tx1": hop("tx1", "R", "tx3", 1), "tx2": hop("tx2", "R", "tx4", 11)})
    assert out(r, "far:R").received == D(997) and out(r, "far:HOT").received == D(997)
    assert out(r, "BR").holds == {"bridge_fee": D(3)}
    assert [c.deposit.tx_hash for c in r.crossings] == ["tx1", "tx2"]
    path = r.path_of(next(e for e in r.edges if e.transfer.tx_hash == "tx3"))
    assert [e.transfer.tx_hash for e in path] == ["tx1", "tx3"]     # each payout by its deposit


def test_money_bridged_back_to_the_wallet_itself_has_returned():
    r = run([tx(1, "S", "BR", 1000, 0)], [], {"tx1": hop("tx1", "S", "tx2", 1, dest=CHAIN)},
            providers={CHAIN: ToyProvider([tx(2, "PAYER", "S", 998, 1)])})
    assert r.stopped == {"bridge_fee": D(2), "returned": D(998)}


def test_a_second_bridge_on_the_other_chain_is_crossed_too():
    labels = {**BASE_LABELS, ("BR2", FAR): ("ToyBridge", "bridge"), ("HOT", CHAIN): ("ExB", "exchange")}
    back = BridgeHop(bridge="ToyBridge", source_chain=FAR, source_tx="tx3", dest_chain=CHAIN,
                     dest_name=CHAIN, recipient="W", payout_tx="tx4",
                     paid_at=T0 + timedelta(minutes=6), deposited_at=None, source="toy.index")
    home = ToyProvider([tx(1, "S", "BR", 1000, 0), tx(4, "PAYER", "W", 990, 6),
                        tx(5, "W", "HOT", 990, 7)])
    far = ToyProvider([ftx(2, "PAYER", "R", 997, 1), ftx(3, "R", "BR2", 997, 5)])
    far.chain = FAR
    r = trace("S", CHAIN, home, Labels(labels), TraceConfig(max_hops=5),
              crossings=Bridges({"tx1": hop("tx1", "R", "tx2", 1), "tx3": back},
                                {FAR: far, CHAIN: home}))
    assert out(r, "HOT").received == D(990) and out(r, "HOT").hop == 5
    assert r.stopped["bridge_fee"] == D(10) and r.chains == [CHAIN, FAR]


def test_the_inbound_walk_does_not_cross_bridges():
    r = run([tx(1, "S", "X", 10, 5), tx(2, "BR", "S", 1000, 0)], [], {})
    assert r.bridges.asked == [] and r.nodes[("inbound", "BR")].state == "labelled"
