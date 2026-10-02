"""Cluster labels: an address spent together with a labelled exchange address is that
exchange's (vaspfusion/cluster.py). Toy transactions, and two real recorded ones."""
import json
from pathlib import Path

from vaspfusion.chains.btc import UtxoTx, coinjoin_ids, tx_frame
from vaspfusion.cluster import ClusterLabels, cluster_of
from vaspfusion.graph.resolve import resolve_entities

from tracekit import ToyLabels
from utxokit import ToyUtxoProvider, utx

FIX = Path(__file__).parent / "fixtures"
# S pays D; D is later swept together with D2 and the exchange's labelled hot wallet
SWEEP = [utx(1, [("S", 100_000)], [("D", 99_000)]),
         utx(2, [("D", 99_000), ("D2", 50_000), ("HOT", 10_000)], [("COLD", 158_000)], minute=10)]


def labels_for(txs, labelled, **kw):
    return ClusterLabels(ToyLabels(labelled), ToyUtxoProvider(txs, **kw))


def test_the_cluster_is_the_addresses_spent_together_with_it():
    c = cluster_of("D", SWEEP)
    assert c.members == ("D", "D2", "HOT") and c.links == ("tx2",) and c.left_out == 0
    assert c.direct == {"D2": ("tx2",), "HOT": ("tx2",)}
    assert cluster_of("S", SWEEP).members == ("S",)         # paying someone is not co-spending
    assert cluster_of("NOBODY", SWEEP).members == ("NOBODY",)


def test_an_address_spent_together_with_a_labelled_one_gets_that_owners_label():
    lab = labels_for(SWEEP, {"HOT": ("ExA", "exchange", "hot", "published_por")}).infer("D", "bitcoin")
    assert (lab.address, lab.entity, lab.category, lab.tier) == ("D", "ExA", "exchange", "derived")
    assert lab.source == "vaspfusion-cluster"
    assert lab.confidence == 0.855                          # 0.95 (published label) x 0.90
    assert "cluster of 3 addresses, 1 labelled ExA" in lab.evidence
    assert "spent together with 2 other addresses in 1 transaction " in lab.evidence
    assert "Labelled address spent with it: HOT" in lab.evidence
    assert "Transaction with both among its inputs: tx2" in lab.evidence
    assert "Rule confidence 0.855 = 0.95 (that label) x 0.90" in lab.evidence
    assert "hand-set, not calibrated" in lab.evidence
    assert lab.evidence.endswith("Read from all 2 transactions of the address.")
    assert lab.label == "ExA wallet (derived: spent together with 1 labelled ExA address)"


def test_co_spending_shows_who_controls_an_address_not_what_it_is_used_for():
    lab = labels_for(SWEEP, {"HOT": ("ExA", "exchange", "hot")}).infer("D", "bitcoin")
    assert lab.kind == "unknown"            # a deposit address or one of the exchange's own


def test_the_strongest_labelled_address_it_was_spent_with_sets_the_confidence():
    lab = labels_for(SWEEP, {"HOT": ("ExA", "exchange", "hot", "explorer_tag"),
                             "D2": ("ExA", "exchange", "deposit", "curated")}).infer("D", "bitcoin")
    assert lab.confidence == 0.765                          # 0.85 (curated) x 0.90
    assert "cluster of 3 addresses, 2 labelled ExA" in lab.evidence
    assert "Labelled address spent with it: D2" in lab.evidence
    assert "spent together with 2 labelled ExA addresses" in lab.label


def test_no_labelled_member_no_label():
    assert labels_for(SWEEP, {"COLD": ("ExA", "exchange")}).infer("D", "bitcoin") is None
    assert labels_for(SWEEP, {"HOT": ("ExA", "exchange")}).infer("S", "bitcoin") is None


def test_two_owners_in_one_cluster_give_no_label_and_a_note():
    labels = labels_for(SWEEP, {"HOT": ("ExA", "exchange"), "D2": ("ExB", "exchange")})
    assert labels.infer("D", "bitcoin") is None
    assert any("ExA" in n and "ExB" in n for n in labels.notes)


def test_a_labelled_address_it_was_never_spent_with_does_not_carry_a_label():
    """D was spent with A only; A was spent with HOT in a transaction that pays D. They
    are one cluster, but no transaction has D and HOT among its inputs."""
    txs = [utx(1, [("A", 60_000), ("HOT", 50_000)], [("D", 109_000)]),
           utx(2, [("D", 109_000), ("A", 5_000)], [("COLD", 113_000)], minute=5)]
    assert cluster_of("D", txs).members == ("A", "D", "HOT")
    labels = labels_for(txs, {"HOT": ("ExA", "exchange")})
    assert labels.infer("D", "bitcoin") is None
    assert any("only through other addresses" in n for n in labels.notes)


def test_being_spent_with_a_sanctioned_address_is_said_not_dropped():
    labels = labels_for(SWEEP, {"HOT": ("OFAC SDN", "sanctioned")})
    assert labels.infer("D", "bitcoin") is None
    assert any("HOT" in n and "OFAC SDN (sanctioned)" in n for n in labels.notes)


def test_an_exchange_tag_with_no_owner_is_no_owner():
    labels = labels_for(SWEEP, {"HOT": ("Unidentified exchange", "exchange"),
                                "D2": ("Unidentified exchange", "exchange")})
    assert labels.infer("D", "bitcoin") is None
    assert any("names no owner" in n for n in labels.notes)


def test_inputs_of_a_coinjoin_are_not_one_owner():
    owners = ["D", "HOT", "P3", "P4", "P5"]
    mix = utx(3, [(o, 1_100_000 + i) for i, o in enumerate(owners)],
              [(f"mix{i}", 1_000_000) for i in range(5)]
              + [(f"chg{i}", 99_000 + i) for i in range(5)])
    labels = labels_for([mix], {"HOT": ("ExA", "exchange")})
    assert labels.infer("D", "bitcoin") is None
    c = cluster_of("D", [mix])
    assert c.members == ("D",) and c.left_out == 1 and c.links == ()


def test_nor_are_the_inputs_of_a_small_join():
    # three parties, three equal outputs and their change: under the CoinJoin bar of five
    join = utx(4, [("D", 600_000), ("HOT", 700_000), ("P3", 650_000)],
               [(f"eq{i}", 500_000) for i in range(3)]
               + [("c1", 99_000), ("c2", 199_000), ("c3", 149_000)])
    assert coinjoin_ids([join]) == set()
    assert labels_for([join], {"HOT": ("ExA", "exchange")}).infer("D", "bitcoin") is None
    assert cluster_of("D", [join]).left_out == 1


def test_the_participants_of_a_real_wasabi_round_stay_apart():
    doc = json.loads((FIX / "chains" / "btc_wasabi_rounds.json").read_text())
    round_ = UtxoTx.from_esplora(doc["transactions"][1])
    who = round_.input_addresses[0]
    c = cluster_of(who, [round_])
    assert len(round_.input_addresses) == 81
    assert c.members == (who,) and c.left_out == 1


def test_a_change_guess_never_carries_a_label():
    """OLD funds S; S then pays the exchange's HOT wallet and sends its change to OLD.
    HOT is the only output never seen before, so the change heuristic calls it S's own
    change and would make S itself an ExA address. Only co-spending is used."""
    txs = [utx(1, [("OLD", 200_000)], [("S", 100_000), ("OLD", 99_000)]),
           utx(2, [("S", 100_000)], [("HOT", 60_000), ("OLD", 39_000)], minute=5)]
    merged, _ = resolve_entities(tx_frame(txs), change=True)
    owner = dict(zip(merged["address"], merged["entity_id"]))
    assert owner["S"] == owner["HOT"]                       # what the heuristic would do
    plain, _ = resolve_entities(tx_frame(txs), change=False)
    owner = dict(zip(plain["address"], plain["entity_id"]))
    assert owner["S"] != owner["HOT"]
    assert labels_for(txs, {"HOT": ("ExA", "exchange")}).infer("S", "bitcoin") is None


def test_only_bitcoin_addresses_are_clustered():
    labels = labels_for(SWEEP, {"HOT": ("ExA", "exchange")})
    assert labels.infer("D", "tron") is None
    assert not [c for c in labels.provider.calls if c[0] == "txs"]


def test_a_listing_that_cannot_be_read_gives_no_label_and_a_note():
    labels = labels_for(SWEEP, {"HOT": ("ExA", "exchange")}, fail={"D"})
    assert labels.infer("D", "bitcoin") is None
    assert any("D" in n and "could not be read" in n for n in labels.notes)


def test_direct_labels_pass_through_and_an_address_is_inferred_once():
    labels = labels_for(SWEEP, {"HOT": ("ExA", "exchange")})
    assert labels.lookup_many([("HOT", "bitcoin"), ("D", "bitcoin")])[("HOT", "bitcoin")].entity == "ExA"
    assert ("D", "bitcoin") not in labels.lookup_many([("D", "bitcoin")])   # infer is a separate step
    labels.infer("D", "bitcoin")
    labels.infer("D", "bitcoin")
    assert labels.provider.calls.count(("txs", "D")) == 1


# ------------------------------------------------------------------ the real demo page
def _demo_page():
    doc = json.loads((FIX / "demo" / "btc-htx.json").read_text())
    deposit = "19vP8bkaR5K9K5W12QyHoYd7TZpz16BxSV"
    page = doc["responses"][f"https://blockstream.info/api/address/{deposit}/txs"]["body"]
    return deposit, [UtxoTx.from_esplora(t) for t in page if t["status"]["confirmed"]]


def test_the_real_demo_deposit_address_was_spent_with_the_exchanges_published_wallet():
    deposit, txs = _demo_page()
    published = "1AQLXAB6aXSVbRMjbhSBudLf1kcsbWSEjg"
    c = cluster_of(deposit, txs)
    assert published in c.direct and published in c.members
    assert set(c.direct) | {deposit} == set(c.members)       # nobody is in it only by a chain
    assert coinjoin_ids(txs) == set()
