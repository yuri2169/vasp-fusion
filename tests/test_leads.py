"""Leads: unlabelled wallets on the trail scored by the deposit-address model. Toy
traces and a stub scorer here; the real model on real wallets is in test_demo_cases.py."""
from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.attribute.leads import LeadConfig, add_leads, wallets_to_score
from vaspfusion.attribute.rules import attribute
from vaspfusion.chains.base import ProviderError
from vaspfusion.classify.runtime import Score
from vaspfusion.trace import TraceConfig, trace

LABELS = {"HOT": ("ExA", "exchange", "hot", "curated")}
REASONS = [{"feature": "forward_ratio", "text": "forwards 100% of what it receives to one wallet",
            "weight": 2.1},
           {"feature": "n_recipients", "text": "pays 1 wallet", "weight": 0.4},
           {"feature": "left_share", "text": "keeps 20% of what it receives", "weight": -0.3}]


class StubScorer:
    def __init__(self, scores, fail=()):
        self.scores, self.fail, self.asked = scores, set(fail), []

    def score(self, address, arrived_at):
        self.asked.append((address, arrived_at))
        if address in self.fail:
            raise ProviderError("listing unavailable")
        if address not in self.scores:
            return None
        p, collector = self.scores[address]
        return Score(address, p, max(0.0, p - 0.03), min(1.0, p + 0.01), REASONS, collector, {},
                     6, True)


def case(transfers, scorer, labels=LABELS, **cfg):
    labels = ToyLabels(labels)
    tr = trace("S", CHAIN, ToyProvider(transfers), labels, TraceConfig(**cfg))
    att = attribute(tr)
    before = (att.outcome, att.top, [(c.vasp, c.confidence) for c in att.candidates])
    notes = add_leads(tr, att, scorer, labels)
    assert before == (att.outcome, att.top, [(c.vasp, c.confidence) for c in att.candidates])
    return tr, att, notes


# S pays D, D sweeps into the unlabelled collector C, which keeps it
SWEEP = [tx(1, "S", "D", 1000, 0), tx(2, "D", "C", 1000, 2)]


def test_a_deposit_like_wallet_is_a_lead_and_the_case_still_abstains():
    scorer = StubScorer({"D": (0.97, "C"), "C": (0.02, None)})
    tr, att, notes = case(SWEEP, scorer)
    assert att.outcome == "INSUFFICIENT_EVIDENCE" and att.top is None
    flag = next(f for f in att.flags if f["code"] == "deposit_like")
    assert (flag["wallet"], flag["severity"], flag["tx_hashes"]) == ("D", "info", ["tx1"])
    assert flag["figures"] == {"p": 0.97, "low": 0.94, "high": 0.98, "transfers_read": 6.0,
                               "share": 1.0, "amount": 1000.0}
    assert flag["text"] == (
        "D behaves like an exchange deposit address: 100% of the funds (1,000 USDT) reached it, "
        "and the deposit-address model gives 0.97 (range 0.94 to 0.98). What speaks for it: "
        "forwards 100% of what it receives to one wallet; pays 1 wallet. Neither it nor C, the wallet it "
        "sweeps into, is labelled, so the exchange cannot be named. A lead to check, not a "
        "finding: the model was measured on exchange customers and deposit addresses only.")
    assert att.what_would_change[0] == (
        "A label for C, the wallet D sweeps into: if it is an exchange's wallet, D is that "
        "exchange's deposit address (100% of the funds)")
    assert att.next_steps[0].startswith("Identify C: D, which received 100% of the funds")
    assert notes == ["Deposit-address model: 2 unlabelled wallets on the trail scored, 1 behaves "
                     "like a deposit address."]
    # each is asked about from when the money first reached it
    assert [a for a, _ in scorer.asked] == ["C", "D"] or [a for a, _ in scorer.asked] == ["D", "C"]
    assert dict(scorer.asked)["D"] == tr.edges_into("outbound", "D")[0].transfer.block_time


def test_a_low_score_is_no_lead():
    _, att, notes = case(SWEEP, StubScorer({"D": (0.89, "C")}))
    assert not [f for f in att.flags if f["code"] == "deposit_like"]
    assert "0 behave like a deposit address" in notes[0]


def test_a_lead_whose_collector_is_a_labelled_exchange_names_it_as_a_question():
    rows = [tx(1, "S", "D", 1000, 0), tx(2, "D", "HOT", 1000, 2)]
    _, att, _ = case(rows, StubScorer({"D": (0.95, "HOT")}))
    assert att.outcome == "ATTRIBUTED" and att.top.vasp == "ExA"     # by the label, as before
    flag = next(f for f in att.flags if f["code"] == "deposit_like")
    assert "is labelled ExA (curated list), so it may be a deposit address of ExA that the " \
           "discovery rules have not derived" in flag["text"]
    assert att.next_steps[0].startswith("Draft a request to ExA")
    assert att.next_steps[-1].startswith("Ask ExA whether D is one of its deposit addresses")


def test_hubs_labelled_and_small_wallets_are_not_scored_and_at_most_five_are():
    rows = [tx(1, "S", "HOT", 500, 0), tx(2, "S", "TINY", 10, 1), tx(3, "S", "HUB", 300, 2)] \
        + [tx(10 + i, "HUB", f"H{i}", 10, 5 + i) for i in range(30)] \
        + [tx(50 + i, "S", f"W{i}", 100 + i, 3) for i in range(7)]
    labels = ToyLabels(LABELS)
    tr = trace("S", CHAIN, ToyProvider(rows), labels, TraceConfig())
    assert tr.nodes[("outbound", "HUB")].state == "hub"
    assert [n.address for n in wallets_to_score(tr)] == ["W6", "W5", "W4", "W3", "W2"]
    assert [n.address for n in wallets_to_score(tr, LeadConfig(max_wallets=2))] == ["W6", "W5"]


def test_without_a_scorer_or_when_a_listing_fails_the_case_says_so():
    _, att, notes = case(SWEEP, None)
    assert att.flags == [f for f in att.flags if f["code"] != "deposit_like"]
    assert notes == ["2 unlabelled wallets on the trail not scored by the deposit-address model: "
                     "it is only used on Tron, where it recognised the deposit addresses of an "
                     "exchange it had never seen."]
    _, att, notes = case(SWEEP, StubScorer({"C": (0.1, None)}, fail={"D"}))
    assert notes[0] == "D could not be scored by the deposit-address model (listing unavailable)."
    assert "1 unlabelled wallet on the trail scored, 0 behave" in notes[1]


def test_a_wallet_that_sent_nothing_has_nothing_to_score():
    _, att, notes = case([tx(1, "X", "S", 5, 0)], StubScorer({}))
    assert notes == []


# ---- review: what the collector is decides what may be said
def test_a_wallet_that_pays_a_bridge_or_a_mixer_is_not_called_a_deposit_address():
    for what in (("Stargate", "bridge"), ("Tornado.Cash", "mixer"), ("Some DAO", "entity")):
        rows = [tx(1, "S", "D", 1000, 0), tx(2, "D", "C", 1000, 2)]
        _, att, notes = case(rows, StubScorer({"D": (0.99, "C")}), labels={"C": what})
        assert not [f for f in att.flags if f["code"] == "deposit_like"], what
        assert not any("Identify C" in s or "label for C" in s
                       for s in att.next_steps + att.what_would_change)


def test_a_collector_tagged_exchange_without_an_owner_is_not_called_unlabelled():
    rows = [tx(1, "S", "D", 1000, 0), tx(2, "D", "C", 1000, 2)]
    labels = {"C": ("Unidentified exchange", "exchange", "unknown", "explorer_tag")}
    _, att, _ = case(rows, StubScorer({"D": (0.99, "C")}), labels=labels)
    flag = next(f for f in att.flags if f["code"] == "deposit_like")
    assert "is tagged as an exchange but the source names no owner" in flag["text"]
    assert "Neither it nor" not in flag["text"]


def test_a_wallet_that_pays_the_traced_wallet_back_is_no_lead():
    rows = [tx(1, "S", "D", 1000, 0), tx(2, "D", "S", 1000, 2)]
    _, att, _ = case(rows, StubScorer({"D": (0.99, "S")}))
    assert not [f for f in att.flags if f["code"] == "deposit_like"]


def test_a_wallet_with_nothing_to_read_is_not_counted_as_scored():
    _, _, notes = case(SWEEP, StubScorer({"D": (0.2, "C")}))          # C: nothing usable
    assert notes == ["Deposit-address model: 1 unlabelled wallet on the trail scored, 0 behave "
                     "like a deposit address."]
