"""The draft request to the issuer of USDT: when it is offered, what it lists, what it
leaves blank, and that it never claims to be sent."""
from vaspfusion.desk import issuer as I
from vaspfusion.labels.frozen import FreezeList

S = "TSuspectAAAAAAAAAAAAAAAAAAAAAAAAAA"
M = "TMiddleBBBBBBBBBBBBBBBBBBBBBBBBBBB"
H = "THolderCCCCCCCCCCCCCCCCCCCCCCCCCCC"
X = "TExchangeDDDDDDDDDDDDDDDDDDDDDDDDD"


def edge(src, dst, amount, tx, t="2026-05-01T10:00:00Z", asset="USDT"):
    return {"id": tx, "source": src, "target": dst, "traced_amount": amount, "asset": asset,
            "direction": "outbound", "tx_hash": tx, "block_time": t}


def case(**kw):
    c = {"id": "c1", "case_ref": "FIR 9/2026", "address": S, "chain": "tron", "asset": "USDT",
         "status": "done", "outcome": "ATTRIBUTED",
         "provenance": {"findings_sha256": "ab" * 32},
         "hop_rail": [{"from_address": S, "to_address": M}, {"from_address": M, "to_address": X}],
         "graph": {"nodes": [
             {"id": S, "address": S, "chain": "tron", "role": "suspect", "hop": 0},
             {"id": M, "address": M, "chain": "tron", "role": "intermediary", "hop": 1},
             {"id": H, "address": H, "chain": "tron", "role": "unknown", "hop": 2},
             {"id": X, "address": X, "chain": "tron", "role": "exchange_deposit", "hop": 2,
              "label": {"category": "exchange", "entity": "CoinDCX"}}],
             "edges": [edge(S, M, 1000.0, "0x1"), edge(M, X, 700.0, "0x2", "2026-05-01T11:00:00Z"),
                       edge(M, H, 300.0, "0x3", "2026-05-01T12:00:00Z")]}}
    return {**c, **kw}


def none():
    return FreezeList({}, {})


def test_offered_with_the_addresses_outside_the_exchange():
    r = I.issuer_request(case(), none())
    assert r["offered"] is True
    d = r["draft"]
    assert [(w["address"], w["role"], w["received"], w["held"]) for w in d["wallets"]] == [
        (H, "held", 300.0, 300.0), (M, "passed_through", 1000.0, 0.0)]
    assert d["wallets"][0]["tx_hashes"] == ["0x3"]
    assert d["officer"] is None and d["legal_provision"] is None
    assert d["evidence_fingerprint"] == "ab" * 32
    assert d["watermark"].startswith("Draft")
    assert "inforequests@tether.to" in d["channel"] and "no channel" in d["channel"]
    assert any("appropriate legal process" in n for n in d["review_notes"])
    assert not any("sent to" in p.lower() for p in d["paragraphs"])


def test_not_offered_for_another_asset_or_chain():
    r = I.issuer_request(case(asset="ETH", chain="ethereum"), none())
    assert r["offered"] is False and "USDT on Tron or Ethereum" in r["reason"]
    assert I.issuer_request(case(chain="bsc"), none())["offered"] is False


def test_not_offered_when_everything_went_into_the_exchange():
    c = case()
    c["graph"]["edges"] = [edge(S, M, 1000.0, "0x1"), edge(M, X, 1000.0, "0x2")]
    c["hop_rail"] = [{"from_address": S, "to_address": X}]
    r = I.issuer_request(c, none())
    assert r["offered"] is False and "exchange request covers it" in r["reason"]


def test_an_address_already_frozen_is_left_out_and_said_so():
    fl = FreezeList({(H, "tron"): {"address": H, "chain": "tron", "asset": "USDT",
                                   "issuer": "Tether", "frozen_at": "2026-06-01T00:00:00Z",
                                   "tx_hash": "f", "contract": "c"}}, {})
    d = I.issuer_request(case(), fl)["draft"]
    assert [w["address"] for w in d["wallets"]] == [M]
    assert any(H in n and "Frozen by Tether on 1 Jun 2026" in n for n in d["review_notes"])


def test_the_pdf_is_a_draft_with_blanks_and_the_same_bytes_each_time():
    d = I.issuer_request(case(), none())["draft"]
    pdf = I.issuer_pdf(d)
    assert pdf == I.issuer_pdf(d) and pdf.startswith(b"%PDF")
    for text in (b"NOT SENT", H.encode(), b"0x3", b"entered by the officer",
                 b"FOR THE REVIEWING OFFICER"):
        assert text in pdf


def test_dust_off_the_path_is_left_out_and_a_busy_wallet_is_marked():
    c = case()
    c["graph"]["nodes"][2]["is_hub"] = True
    c["graph"]["edges"].append(edge(M, "TDust", 0.5, "0x4"))
    c["graph"]["nodes"].append({"id": "TDust", "address": "TDust", "chain": "tron",
                                "role": "unknown", "hop": 2})
    ws = I.issuer_request(c, none())["draft"]["wallets"]
    assert [w["address"] for w in ws] == [H, M] and ws[0]["busy"] is True
