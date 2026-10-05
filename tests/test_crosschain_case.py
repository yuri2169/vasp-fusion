"""A case whose money crossed a bridge, end to end: attribution, the words an officer
reads, the CaseDetail the interface gets, and the request desk. Toy transfers on two
chains (tracekit.py); the real crossing is the recorded `eth-bridge` wallet."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from tracekit import T0, ToyProvider, tx
from test_trace_crosschain import Bridges, Labels
from vaspfusion.api import schemas as S
from vaspfusion.attribute.counterfactual import HiddenLabels
from vaspfusion.cases import run_case
from vaspfusion.chains.bridges import BridgeHop, Unresolved
from vaspfusion.desk.letter import draft_letter
from vaspfusion.desk.routing import routed_wallets
from vaspfusion.explain.case_file import case_file_text
from vaspfusion.trace import TraceConfig

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
HOME, FAR = "ethereum", "base"
LABELS = {("BR", HOME): ("Across Protocol", "bridge"), ("OTHER", HOME): ("Hop Protocol", "bridge"),
          ("DEP", FAR): ("ExA", "exchange", "deposit"), ("SWAP", HOME): ("ChangeNOW", "swap_service")}


def h(n, frm, to, amount, minute, asset="USDT"):
    return replace(tx(n, frm, to, amount, minute, asset), chain=HOME)


def f(n, frm, to, amount, minute, asset="USDC"):
    return replace(tx(n, frm, to, amount, minute, asset), chain=FAR)


def hop(deposit, recipient, payout, minute, dest=FAR, name=None):
    return BridgeHop(bridge="Across", source_chain=HOME, source_tx=deposit, dest_chain=dest,
                     dest_name=name or dest, recipient=recipient, payout_tx=payout,
                     paid_at=T0 + timedelta(minutes=minute),
                     deposited_at=T0 + timedelta(minutes=minute - 1), source="toy.index")


def case(home, far, hops, providers=None, **cfg):
    far_provider = ToyProvider(far)
    far_provider.chain = FAR
    bridges = Bridges(hops, {FAR: far_provider} if providers is None else providers)
    home_provider = ToyProvider(home)
    home_provider.chain = HOME
    return run_case("S", HOME, home_provider, Labels(LABELS), case_id="c-x", now=NOW,
                    cfg=TraceConfig(**cfg), crossings=bridges)


REACHED = ([h(1, "S", "BR", 1000, 0)],
           [f(2, "PAYER", "S", 996, 1), f(3, "S", "DEP", 996, 9)],
           {"tx1": hop("tx1", "S", "tx2", 1)})


def test_an_exchange_on_the_other_chain_is_named_with_the_crossing_counted_as_a_hop():
    c = case(*REACHED)
    assert (c["outcome"], c["top_vasp"], c["chains"]) == ("ATTRIBUTED", "ExA", [HOME, FAR])
    (cand,) = c["candidates"]
    # deposit, payout, transfer on Base: three hops, so two steps of hop decay on 0.85
    assert (cand["hops"], cand["chain"], cand["deposit_address"]) == (3, FAR, "DEP")
    assert cand["confidence"] == round(0.85 * 0.85 ** 2, 4)
    assert cand["share_of_funds"] == 0.996 and cand["amount"] == 996.0
    assert (cand["path"], cand["path_chains"]) == (["S", "BR", "S", "DEP"], [HOME, HOME, FAR, FAR])


def test_the_crossing_is_evidence_with_both_transactions():
    (cand,) = case(*REACHED)["candidates"]
    crossing = next(e for e in cand["evidence"] if e["text"].startswith("Crossed"))
    assert crossing["tx_hashes"] == ["tx1", "tx2"]
    assert crossing["text"] == (
        "Crossed from Ethereum to Base through the Across Protocol bridge: 1,000 USDT went in "
        "and 996 USDC was paid out to S on Base 1 minute later. The two transactions are "
        "matched by the bridge's own index (toy.index); the amount paid out is read from the "
        "payout transaction on Base")
    reached = next(e for e in cand["evidence"] if "reached it" in e["text"])
    assert "(996 USDC) reached it in 3 hops" in reached["text"]


def test_the_fee_is_a_fee_and_the_slices_add_up():
    c = case(*REACHED)
    assert [(w["kind"], w["name"], w["amount"]) for w in c["where_funds_went"]] == [
        ("vasp", "ExA", 996.0), ("bridge_fee", None, 4.0)]
    assert sum(w["amount"] for w in c["where_funds_went"]) == c["total_sent"]


def test_the_case_states_the_leg_on_the_rail_the_graph_and_the_list():
    c = case(*REACHED)
    S.CaseDetail.model_validate(c)
    rail = c["hop_rail"]
    assert [(r["from_address"], r["from_chain"], r["to_address"], r["to_chain"], r["tx_hash"])
            for r in rail] == [("S", HOME, "BR", HOME, "tx1"), ("BR", HOME, "S", FAR, "tx2"),
                               ("S", FAR, "DEP", FAR, "tx3")]
    leg = rail[1]["bridge"]
    assert rail[0]["bridge"] is None and rail[2]["bridge"] is None
    assert (leg["bridge"], leg["status"], leg["source_tx"], leg["payout_tx"], leg["dest_chain"],
            leg["amount_in"], leg["amount_out"], leg["fee"], leg["seconds"], leg["paid_by"]) == \
        ("Across Protocol", "followed", "tx1", "tx2", FAR, 1000.0, 996.0, 4.0, 60, "PAYER")
    assert c["crossings"] == [leg]
    nodes = {n["id"]: (n["address"], n["chain"], n["hop"]) for n in c["graph"]["nodes"]}
    assert nodes == {"S": ("S", HOME, 0), "BR": ("BR", HOME, 1), "base:S": ("S", FAR, 2),
                     "base:DEP": ("DEP", FAR, 3)}
    edges = {e["tx_hash"]: (e["source"], e["target"], e["chain"], e["bridge"] is not None)
             for e in c["graph"]["edges"]}
    assert edges == {"tx1": ("S", "BR", HOME, False), "tx2": ("BR", "base:S", FAR, True),
                     "tx3": ("base:S", "base:DEP", FAR, False)}
    assert c["tx_chains"] == {"tx2": FAR, "tx3": FAR}


def test_the_words_say_the_chain_of_a_wallet_reached_over_the_bridge():
    c = case(*REACHED)
    assert "1,000 USDT (100%) left Ethereum through the Across Protocol bridge in 1 deposit, " \
           "and 996 USDC of it arrived at S on Base, where the trace goes on." in c["narrative"]
    assert "996 USDC (99%) reached ExA in 3 hops" in c["narrative"]
    rapid = next(x for x in c["typology_flags"] if x["code"] == "rapid_forwarding")
    assert (rapid["wallet"], rapid["chain"]) == ("S", FAR)
    assert rapid["text"].startswith("S on Base passed on 100% of the 996 USDC that reached it")
    assert c["next_steps"][0] == ("Draft a request to ExA for KYC and a freeze on the account "
                                  "behind DEP on Base")
    assert not any(s.startswith("Follow the") for s in c["next_steps"])
    flag = next(x for x in c["typology_flags"] if x["code"] == "bridge_hop")
    assert flag["chain"] == HOME and flag["text"].endswith("followed onto Base")


def test_the_request_names_the_wallet_on_the_chain_it_is_on():
    c = case(*REACHED)
    (w,) = routed_wallets(c)
    assert (w["address"], w["chain"], w["case_chain"], w["asset"], w["amount"],
            w["amount_usd"]) == ("DEP", FAR, HOME, "USDC", 996.0, 996.0)
    letter = draft_letter(reference="R/1", vasp="ExA", entry={"name": "ExA"}, wallets=[w],
                          asks=["kyc", "freeze"], officer="Insp. A", today=date(2026, 10, 5))
    assert letter["wallets"][0]["chain"] == FAR and letter["cases"][0]["chain"] == HOME
    assert "S on Ethereum" in letter["paragraphs"][1]
    assert ("DEP is on Base, not on Ethereum where the traced wallet is: the funds crossed a "
            "bridge on the way. The case file lists the bridge transactions.") \
        in letter["review_notes"]


def test_the_case_file_lists_the_bridge_leg():
    text = case_file_text(case(*REACHED), bar_check=None)
    assert "Chain             Ethereum; followed onto Base" in text
    assert "BRIDGES" in text and "Payout transaction   tx2" in text
    assert "Cost of crossing     4 USDT" in text and "Matched by           toy.index" in text
    assert "Kept by a bridge as the cost of crossing" in text
    assert "(over the Across Protocol bridge, Ethereum to Base)" in text
    assert "base:" not in text


def test_a_bridge_with_no_resolver_keeps_the_step_that_says_what_to_follow():
    c = case([h(1, "S", "OTHER", 1000, 0)], [], {"tx1": Unresolved("no resolver for it")})
    assert c["chains"] == [HOME] and c["tx_chains"] == {}
    (x,) = c["crossings"]
    assert (x["status"], x["reason"], x["recipient"]) == ("unresolved", "no resolver for it", None)
    assert c["next_steps"][0].startswith(
        "Follow the 1,000 USDT that went into the Hop Protocol bridge at OTHER onto the "
        "destination chain: a bridge is not an exchange")
    assert c["what_would_change"] == ["Following the funds across the bridge (Hop Protocol) "
                                      "onto the destination chain"]
    assert c["where_funds_went"] == [{"kind": "bridge", "name": "Hop Protocol", "share": 1.0,
                                      "amount": 1000.0}]


def test_a_destination_that_cannot_be_traced_is_named_with_its_recipient_and_payout():
    c = case([h(1, "S", "BR", 1000, 0)], [],
             {"tx1": hop("tx1", "0xRECIPIENT", "0xPAYOUT", 1, dest=None, name="Linea")})
    assert c["next_steps"][0] == (
        "Trace 0xRECIPIENT on Linea: the 1,000 USDT that went into the Across Protocol bridge "
        "at BR was paid out to it (transaction 0xPAYOUT; matched by toy.index). It was not "
        "followed there because Linea is not a chain this tool reads")
    assert c["what_would_change"] == ["Tracing 0xRECIPIENT on Linea, where the Across Protocol "
                                      "bridge paid out"]
    (x,) = c["crossings"]
    assert (x["status"], x["dest_chain"], x["dest_name"], x["payout_tx"]) == \
        ("not_traced", None, "Linea", "0xPAYOUT")
    assert c["where_funds_went"][0]["kind"] == "bridge" and c["tx_chains"] == {}


def test_a_destination_with_no_key_says_exactly_that():
    def no_key(chain):
        from vaspfusion.chains.base import UnsupportedChain
        raise UnsupportedChain("bsc needs ANKR_API_KEY")

    bridges = Bridges({"tx1": hop("tx1", "R", "tx2", 1, dest="bsc")}, {})
    bridges.provider = no_key
    home = ToyProvider([h(1, "S", "BR", 1000, 0)])
    c = run_case("S", HOME, home, Labels(LABELS), case_id="c-x", now=NOW, crossings=bridges)
    assert c["next_steps"][0].endswith(
        "It was not followed there because the recipient's transfers on bsc could not be read "
        "(bsc needs ANKR_API_KEY)")
    assert c["next_steps"][0].startswith("Trace R on BNB Smart Chain:")


def test_the_counterfactual_hides_the_label_on_the_other_chain_only():
    hidden = HiddenLabels(Labels({("DEP", FAR): ("ExA", "exchange"),
                                  ("DEP", HOME): ("ExB", "exchange")}), {"base:DEP"}, HOME)
    assert list(hidden.lookup_many([("DEP", FAR), ("DEP", HOME)])) == [("DEP", HOME)]
    c = case(*REACHED)
    (cand,) = c["candidates"]
    # hidden, DEP is an unlabelled wallet at the hop limit: "not reached" would be a guess
    assert cand["counterfactual_holds"] is None
    assert cand["counterfactual"].startswith("Not checked: without the label on DEP on Base")


# ------------------------------------------------------------------ swap services
SWAPPED = [h(1, "S", "M1", 1000, 0), h(2, "M1", "SWAP", 1000, 4)]


def test_reaching_a_swap_service_is_reaching_a_vasp_that_can_answer():
    c = case(SWAPPED, [], {})
    assert (c["outcome"], c["top_vasp"]) == ("ATTRIBUTED", "ChangeNOW")
    assert c["candidates"][0]["category"] == "swap_service"
    assert c["next_steps"][0] == (
        "Draft a request to ChangeNOW for the swap order paid in at M1: the payout chain, "
        "address and transaction, and what it holds on the customer. ChangeNOW is a swap "
        "service: it took custody of the funds and paid out from its own pool, so the trail "
        "cannot be followed past it on-chain")


def test_the_letter_to_a_swap_service_asks_for_the_payout():
    wallets = routed_wallets(case(SWAPPED, [], {}))
    assert [w["category"] for w in wallets] == ["swap_service"]
    letter = draft_letter(reference="R/2", vasp="ChangeNOW", entry={"name": "ChangeNOW"},
                          wallets=wallets, asks=["kyc"], officer="Insp. A",
                          today=date(2026, 10, 5))
    assert letter["asks"] == ["kyc", "transactions"]       # the payout is always asked for
    body = " ".join(letter["paragraphs"])
    assert "the payout chain, the payout address, the payout transaction hash" in body
    assert "ChangeNOW operates a swap service" in body
    assert any(n.startswith("ChangeNOW is a swap service. It may hold no KYC")
               for n in letter["review_notes"])
    S.RequestLetter.model_validate(letter)


def test_a_letter_to_an_exchange_is_worded_as_before():
    (w,) = routed_wallets(case(*REACHED))
    letter = draft_letter(reference="R/3", vasp="ExA", entry={"name": "ExA"}, wallets=[w],
                          asks=["transactions"], officer="Insp. A", today=date(2026, 10, 5))
    assert "swap" not in " ".join(letter["paragraphs"]).lower()
    assert "furnish the transaction history of those accounts" in letter["paragraphs"][2]
