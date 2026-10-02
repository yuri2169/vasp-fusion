"""Cluster labels: an address spent together with a labelled exchange address is that
exchange's (vaspfusion/cluster.py). Toy transactions; the real one is the Bitcoin demo."""
from vaspfusion.chains.btc import tx_frame
from vaspfusion.cluster import ClusterLabels, cluster_of
from vaspfusion.graph.resolve import resolve_entities

from tracekit import ToyLabels
from utxokit import ToyUtxoProvider, utx

# S pays D; D is later swept together with D2 and the exchange's labelled hot wallet
SWEEP = [utx(1, [("S", 100_000)], [("D", 99_000)]),
         utx(2, [("D", 99_000), ("D2", 50_000), ("HOT", 10_000)], [("COLD", 158_000)], minute=10)]


def labels_for(txs, labelled, **kw):
    return ClusterLabels(ToyLabels(labelled), ToyUtxoProvider(txs, **kw))


def test_the_cluster_is_the_addresses_spent_together_with_it():
    c = cluster_of("D", SWEEP)
    assert c.members == ("D", "D2", "HOT") and c.links == ("tx2",) and c.coinjoin_skipped == 0
    assert cluster_of("S", SWEEP).members == ("S",)         # paying someone is not co-spending
    assert cluster_of("NOBODY", SWEEP).members == ("NOBODY",)


def test_an_address_spent_together_with_a_labelled_one_gets_that_owners_label():
    lab = labels_for(SWEEP, {"HOT": ("ExA", "exchange", "hot", "published_por")}).infer("D", "bitcoin")
    assert (lab.address, lab.entity, lab.category, lab.kind) == ("D", "ExA", "exchange", "deposit")
    assert (lab.tier, lab.source) == ("derived", "vaspfusion-cluster")
    assert lab.confidence == 0.855                          # 0.95 (published label) x 0.90
    assert "cluster of 3 addresses, 1 labelled ExA" in lab.evidence
    assert "HOT" in lab.evidence and "tx2" in lab.evidence
    assert "hand-set, not calibrated" in lab.evidence


def test_the_strongest_labelled_member_sets_the_confidence():
    lab = labels_for(SWEEP, {"HOT": ("ExA", "exchange", "hot", "explorer_tag"),
                             "D2": ("ExA", "exchange", "deposit", "curated")}).infer("D", "bitcoin")
    assert lab.confidence == 0.765                          # 0.85 (curated) x 0.90
    assert "cluster of 3 addresses, 2 labelled ExA" in lab.evidence


def test_no_labelled_member_no_label():
    assert labels_for(SWEEP, {"COLD": ("ExA", "exchange")}).infer("D", "bitcoin") is None
    assert labels_for(SWEEP, {"HOT": ("ExA", "exchange")}).infer("S", "bitcoin") is None


def test_two_owners_in_one_cluster_give_no_label_and_a_note():
    labels = labels_for(SWEEP, {"HOT": ("ExA", "exchange"), "D2": ("ExB", "exchange")})
    assert labels.infer("D", "bitcoin") is None
    assert any("ExA" in n and "ExB" in n for n in labels.notes)


def test_a_cluster_labelled_as_something_other_than_a_vasp_is_not_inferred():
    assert labels_for(SWEEP, {"HOT": ("OFAC SDN", "sanctioned")}).infer("D", "bitcoin") is None


def test_inputs_of_a_coinjoin_are_not_one_owner():
    owners = ["D", "HOT", "P3", "P4", "P5"]
    mix = utx(3, [(o, 1_100_000 + i) for i, o in enumerate(owners)],
              [(f"mix{i}", 1_000_000) for i in range(5)]
              + [(f"chg{i}", 99_000 + i) for i in range(5)])
    labels = labels_for([mix], {"HOT": ("ExA", "exchange")})
    assert labels.infer("D", "bitcoin") is None
    assert cluster_of("D", [mix]).coinjoin_skipped == 1


def test_the_participants_of_a_real_wasabi_round_stay_apart():
    import json
    from pathlib import Path

    from vaspfusion.chains.btc import UtxoTx
    doc = json.loads((Path(__file__).parent / "fixtures" / "chains"
                      / "btc_wasabi_rounds.json").read_text())
    round_ = UtxoTx.from_esplora(doc["transactions"][1])
    who = round_.input_addresses[0]
    c = cluster_of(who, [round_])
    assert len(round_.input_addresses) == 81
    assert c.members == (who,) and c.coinjoin_skipped == 1


def test_the_real_demo_deposit_address_is_clustered_with_the_exchanges_published_wallet():
    import json
    from pathlib import Path

    from vaspfusion.chains.btc import UtxoTx, coinjoin_ids
    doc = json.loads((Path(__file__).parent / "fixtures" / "demo" / "btc-htx.json").read_text())
    deposit, published = "19vP8bkaR5K9K5W12QyHoYd7TZpz16BxSV", "1AQLXAB6aXSVbRMjbhSBudLf1kcsbWSEjg"
    page = doc["responses"][f"https://blockstream.info/api/address/{deposit}/txs"]["body"]
    txs = [UtxoTx.from_esplora(t) for t in page if t["status"]["confirmed"]]
    c = cluster_of(deposit, txs)
    assert len(c.members) == 288 and published in c.members and len(c.links) == 9
    assert coinjoin_ids(txs) == set() and c.coinjoin_skipped == 0


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


def test_a_coinjoin_sink_is_named_as_a_mixer_with_the_transactions_shape():
    owners = "ABCDE"
    mix = utx(20, [(o, 1_100_000 + i) for i, o in enumerate(owners)],
              [(f"mix{i}", 1_000_000) for i in range(5)]
              + [(f"chg{i}", 99_000 + i) for i in range(5)])
    labels = labels_for([mix], {})
    lab = labels.lookup_many([("coinjoin:tx20", "bitcoin")])[("coinjoin:tx20", "bitcoin")]
    assert (lab.entity, lab.category, lab.tier) == ("CoinJoin", "mixer", "derived")
    assert "5 input addresses" in lab.evidence and "5 of its 10 outputs" in lab.evidence
    assert "0.01 BTC" in lab.evidence and "tx20" in lab.evidence


def test_newly_mined_coins_have_a_name_so_nothing_tries_to_read_their_history():
    lab = labels_for([], {}).lookup_many([("coinbase", "bitcoin")])[("coinbase", "bitcoin")]
    assert lab.category == "entity" and "mined" in lab.entity.lower()
