"""The case file of each demo wallet: what it says (golden text), that it says all of
it, and its A4 PDF. Recorded demo wallets; no network."""
import copy
from pathlib import Path

import pytest

from demokit import SPECS
from refresh_golden import COMMIT, golden_case
from vaspfusion.explain import case_file as CF
from vaspfusion.explain.case_pdf import case_pdf
from vaspfusion.explain.flow import layout, wallet_index

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    d = tmp_path_factory.mktemp("cf")
    return {cid: golden_case(cid, d / f"{cid}.duckdb") for cid in SPECS}


# ------------------------------------------------------------------ the text
@pytest.mark.parametrize("case_id", list(SPECS))
def test_the_case_file_of_each_demo_wallet_is_the_golden_one(case_id, cases):
    assert CF.case_file_text(cases[case_id]) == (GOLDEN / f"{case_id}.txt").read_text()


@pytest.mark.parametrize("case_id", list(SPECS))
def test_it_holds_every_finding(case_id, cases):
    case = cases[case_id]
    text = CF.case_file_text(case)
    flat = " ".join(text.split())
    assert case["address"] in text
    for c in case["candidates"]:
        assert c["vasp"] in text and c["deposit_address"] in text
        for ev in c["evidence"]:
            for h in ev["tx_hashes"]:
                assert h in text                       # every evidence hash, in full
    for f in case["typology_flags"]:
        assert f["wallet"] in text
        assert all(h in text for h in f["tx_hashes"])
    for h in case["hop_rail"]:
        assert h["tx_hash"] in text
    for n in case["graph"]["nodes"]:
        assert (n["address"] or n["id"]) in text       # the wallet table lists every wallet
    assert "base:0x" not in text                       # a graph id is never printed
    for x in case["crossings"]:                        # each bridge leg, both transactions
        assert x["source_tx"] in text and (x["payout_tx"] or "") in text
    if case["abstain_reason"]:
        assert " ".join(case["abstain_reason"].split()) in flat
    for step in case["next_steps"]:
        assert " ".join(step.split()) in flat
    assert " ".join(case["narrative"].split()) in flat          # printed as the trace wrote it
    prov = case["provenance"]
    for digest in (prov["findings_sha256"], prov["input_sha256"], prov["responses_sha256"]):
        assert digest in text
    assert all(p["sha256"] in text and p["query"] in text for p in prov["responses"])
    assert "LIMITATIONS" in text and "does not identify a person" in flat
    assert f"verify {case_id}" in flat


@pytest.mark.parametrize("case_id", list(SPECS))
def test_what_the_file_states_itself_is_in_full_and_short_forms_are_explained(case_id, cases):
    case = cases[case_id]
    blocks = CF.case_file(case)
    for b in blocks:                       # tables, key/value rows, hashes: never shortened
        if b["t"] == "table":
            assert not any("…" in cell for row in b["rows"] for cell in row)
        elif b["t"] == "kv":
            assert not any("…" in v for _, v in b["rows"])
        elif b["t"] == "evidence":
            assert not any("…" in h for h in b["hashes"])
    assert any(b["t"] == "small" and "first six and last six characters" in b["text"]
               for b in blocks)


def test_an_attributed_case_says_what_its_confidence_is_made_of(cases):
    text = " ".join(CF.case_file_text(cases["tron-coindcx"]).split())
    assert "EXCHANGE NAMED" in text and "Nearest exchange: CoinDCX. Confidence 0.85" in text
    assert "What is calibrated: only the deposit-address model's probability" in text
    assert "Confidence is not the probability that the named exchange is right" in text
    assert "An exchange is named only at 0.60 or more" in text
    assert "checked on 280 real Tron wallets" in text and "not a calibration" in text


def test_a_rule_confidence_is_called_one(cases):
    text = " ".join(CF.case_file_text(cases["eth-bitget"]).split())
    assert "Nearest exchange: Bitget. Confidence 0.75 (rule confidence)." in text
    assert "The bar has not been measured on this chain." in text
    assert "not used in this case" in text           # no model on Ethereum


def test_an_abstain_names_no_exchange_and_says_why(cases):
    text = CF.case_file_text(cases["tron-abstain"])
    assert "INSUFFICIENT EVIDENCE: NO EXCHANGE IS NAMED" in text
    assert "under 0.60: not named" in text           # CoinDCX is listed, for the record
    assert "Nearest exchange:" not in text
    assert "LEADS TO CHECK" in text and "A lead is not a finding" in " ".join(text.split())


def test_a_sanctioned_result_leads_with_the_alert(cases):
    text = CF.case_file_text(cases["tron-ofac"])
    assert "SANCTIONED OR MIXING ADDRESS REACHED" in text
    assert "TFdHux43bs21qRsygv5WQWfgtbQeT6nXey" in text
    assert "No exchange is named." in text


def test_a_demo_case_says_it_is_one_and_a_real_one_does_not(cases):
    demo = cases["tron-coindcx"]
    assert "Demonstration case." in CF.case_file_text(demo)
    assert "Demonstration case." not in CF.case_file_text({**demo, "demo": False})


def test_the_officers_details_are_in_the_header(cases):
    case = {**cases["tron-coindcx"], "case_ref": "FIR 12/2026", "complaint_no": "1930-778",
            "amount_lost_inr": 250000.0}
    text = CF.case_file_text(case)
    assert "FIR 12/2026" in text and "1930-778" in text and "Rs 250,000" in text


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_a_case_with_no_result_has_no_file(status, cases):
    case = {**cases["tron-coindcx"], "status": status, "outcome": None}
    with pytest.raises(CF.NotReady, match="no result yet"):
        CF.case_file(case)


def test_a_case_stored_before_receipts_still_gets_a_file(cases):
    old = copy.deepcopy(cases["tron-coindcx"])
    old["provenance"] = {"seed": 26182, "code_version": "b8-desk-1"}
    text = CF.case_file_text(old)
    assert "This case carries no receipt" in " ".join(text.split())


def test_a_bitcoin_case_file_states_the_rules_that_only_apply_to_bitcoin(cases):
    flat = " ".join(CF.case_file_text(cases["btc-htx"]).split())
    # how a transaction with many inputs and outputs became transfers
    assert "only where that has one answer" in flat
    assert "Change is not guessed" in flat
    # the generic "not a fact recorded on the chain" is not true of Bitcoin
    assert "Bitcoin does record which coin each transaction spent" in flat
    assert "not a fact recorded on the chain" not in flat
    # what a cluster label is, and that it is a rule
    assert "spent together with a labelled address" in flat
    assert "0.90 for having been spent together" in flat
    # and none of it leaks into the other chains' files
    other = " ".join(CF.case_file_text(cases["tron-coindcx"]).split())
    assert "spent together" not in other and "has one answer" not in other
    assert "not a fact recorded on the chain" in other


# ------------------------------------------------------------------ the flow diagram
@pytest.mark.parametrize("case_id", list(SPECS))
def test_every_wallet_is_numbered_once_and_the_traced_wallet_is_w0(case_id, cases):
    case = cases[case_id]
    index = wallet_index(case)
    assert [r["n"] for r in index] == list(range(len(case["graph"]["nodes"])))
    assert index[0]["address"] == case["address"] and index[0]["col"] == 0
    assert {r["address"] for r in index} == {n["id"] for n in case["graph"]["nodes"]}


@pytest.mark.parametrize("case_id", list(SPECS))
def test_the_layout_is_columns_by_hop_and_bounded(case_id, cases):
    case = cases[case_id]
    lay = layout(case, max_boxes=12, max_rows=5)
    index = {r["address"]: r for r in wallet_index(case)}
    assert len(lay["boxes"]) <= 12 and lay["omitted"] == len(index) - len(lay["boxes"])
    assert len({(b["col"], b["row"]) for b in lay["boxes"]}) == len(lay["boxes"])
    per_col = {}
    for b in lay["boxes"]:
        per_col[b["col"]] = per_col.get(b["col"], 0) + 1
        title = lay["columns"][b["col"]]
        col = index[b["address"]]["col"]
        assert title == ("Funded the wallet" if col < 0 else "Traced wallet" if col == 0
                         else f"Hop {col}")
    assert max(per_col.values()) <= 5
    shown = {b["address"] for b in lay["boxes"]}
    assert case["address"] in shown
    assert all(a["source"] in shown and a["target"] in shown for a in lay["arrows"])
    assert lay == layout(case, max_boxes=12, max_rows=5)          # same case, same picture


def test_the_named_route_is_always_drawn(cases):
    case = cases["tron-htx-coindcx"]
    lay = layout(case, max_boxes=4, max_rows=2)
    shown = {b["address"] for b in lay["boxes"]}
    assert set(case["candidates"][0]["path"]) <= shown
    funders = [b for b in lay["boxes"] if lay["columns"][b["col"]] == "Funded the wallet"]
    assert all(b["col"] == 0 for b in funders)                   # left of the traced wallet


# ------------------------------------------------------------------ the PDF
@pytest.mark.parametrize("case_id", list(SPECS))
def test_the_pdf_is_the_same_bytes_every_time(case_id, cases):
    a, b = case_pdf(cases[case_id]), case_pdf(copy.deepcopy(cases[case_id]))
    assert a.startswith(b"%PDF-") and a == b
    assert 2 <= a.count(b"/Type /Page\n") <= 12


def test_the_pdf_holds_the_findings_as_searchable_text(cases):
    case = cases["tron-coindcx"]
    pdf = case_pdf(case)
    for needle in (case["address"], case["candidates"][0]["deposit_address"],
                   case["hop_rail"][0]["tx_hash"], case["provenance"]["findings_sha256"],
                   "DEMO/2026/101", "Exchange named", COMMIT):
        assert needle.encode() in pdf, needle
    assert f"fingerprint {case['provenance']['findings_sha256']}".encode() in pdf   # footer


def test_a_fixture_case_is_watermarked_and_a_real_one_is_not(cases):
    case = cases["eth-bitget"]
    assert b"DEMO FIXTURE - NOT EVIDENCE" in case_pdf(case, watermark="Demo fixture - not evidence")
    assert b"NOT EVIDENCE" not in case_pdf(case)


def test_text_outside_the_pdf_fonts_does_not_break_it(cases):
    case = {**cases["tron-coindcx"], "case_ref": "प्राथमिकी 12/2026 <b>&", "complaint_no": "₹ 5"}
    pdf = case_pdf(case)
    assert pdf.startswith(b"%PDF-") and b"Rs 5" in pdf
