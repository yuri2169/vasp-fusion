"""Draft, approve, send, track: the desk on the recorded real demo wallets."""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deskkit import NOW, demo_cases  # noqa: E402
from vaspfusion.cases import CODE_VERSION  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.desk.directory import Directory  # noqa: E402
from vaspfusion.desk.gateway import GatewayError, MockSahyogGateway, canonical  # noqa: E402
from vaspfusion.desk.pdf import letter_pdf  # noqa: E402
from vaspfusion.desk.service import TRANSITIONS, DeskError, DeskService  # noqa: E402
from vaspfusion.store.cases import CaseStore  # noqa: E402
from vaspfusion.store.requests import RequestStore  # noqa: E402

ASKS = ["kyc", "transactions", "freeze", "preservation"]
COINDCX_CASES = ["tron-coindcx", "tron-htx-coindcx"]


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t

    def later(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def desk(tmp_path):
    cases = CaseStore(tmp_path / "case.duckdb")
    for case in demo_cases():
        cases.save(case)
    svc = DeskService(cases, RequestStore(tmp_path / "desk.duckdb"), Directory.load(),
                      MockSahyogGateway(tmp_path / "outbox"), now=Clock())
    svc.outbox = tmp_path / "outbox"
    return svc


def _draft(desk, vasp="CoinDCX", cases=COINDCX_CASES, asks=ASKS, **kw):
    return desk.create(vasp, cases, asks, "Insp. A. Rao, Cyber PS", **kw)


# ---------------------------------------------------------------------- the draft
def test_one_request_consolidates_an_exchanges_wallets_across_cases(desk):
    req = _draft(desk)
    S.RequestDetail.model_validate(req)
    assert (req["id"], req["reference"], req["status"]) == (
        "req-2026-0001", "VF/REQ/2026/0001", "drafted")
    assert req["case_ids"] == COINDCX_CASES and req["due"] is None and req["receipt"] is None
    assert req["allowed_next"] == ["approved", "withdrawn"]
    letter = req["letter"]
    assert letter["to"] == "The Nodal Officer, Neblio Technologies Private Limited (CoinDCX)"
    assert letter["date"] == "2026-10-02" and letter["officer"] == "Insp. A. Rao, Cyber PS"
    assert letter["watermark"] == "Draft - officer review required"
    assert [c["case_ref"] for c in letter["cases"]] == ["DEMO/2026/101", "DEMO/2026/104"]
    assert "DEMO/2026/101 and DEMO/2026/104" in letter["subject"]
    assert "2 wallets attributed to CoinDCX" in letter["subject"]
    a, b = letter["wallets"]
    assert (a["address"], a["tier"], a["amount"], a["asset"], a["case_ref"]) == (
        "TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5", "derived", 1530.0, "USDT", "DEMO/2026/101")
    assert (b["address"], b["amount"], b["amount_usd"]) == (
        "TLUQsVHsmUrcWEy3tGrpEdh2ue8z2NHPYk", 6000.0, 6000.0)
    assert a["tx_hashes"] and all(len(h) == 64 for h in a["tx_hashes"] + b["tx_hashes"])
    assert a["first_seen"] and a["confidence"] >= 0.6 and a["paid_into"] is None
    assert req["status_history"] == [{"status": "drafted", "at": "2026-10-02T09:30:00Z",
                                      "note": "Drafted by Insp. A. Rao, Cyber PS"}]


def test_a_letter_never_shortens_an_address_and_names_the_traced_wallets(desk):
    letter = _draft(desk)["letter"]
    text = json.dumps(letter, ensure_ascii=False)
    assert "…" not in text
    for suspect in ("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", "TGfoGrh8ddh4zzpBe3G82p1tgmeUq49sWr"):
        assert suspect in letter["paragraphs"][1]


def test_the_legal_basis_names_the_notice_the_certificate_and_the_freeze_power(desk):
    full = _draft(desk)["letter"]
    assert full["legal_basis"].startswith(
        "Notice under Section 94 of the Bharatiya Nagarik Suraksha Sanhita, 2023. Electronic "
        "records to be furnished with a certificate under Section 63 of the Bharatiya "
        "Sakshya Adhiniyam, 2023.")
    assert "Section 106" in full["legal_basis"]
    assert [c["section"] for c in full["legal_citations"]] == ["94", "63", "106"]
    assert all(c["url"].startswith("https://www.indiacode.nic.in/") for c in full["legal_citations"])
    no_freeze = _draft(desk, vasp="HTX", cases=["tron-htx-coindcx"],
                       asks=["preservation", "kyc"])["letter"]
    assert no_freeze["asks"] == ["kyc", "preservation"]             # canonical order
    assert "106" not in no_freeze["legal_basis"]
    assert [c["section"] for c in no_freeze["legal_citations"]] == ["94", "63"]
    assert "freeze" not in " ".join(no_freeze["paragraphs"])


def test_review_notes_say_what_the_officer_should_check(desk):
    htx = _draft(desk, vasp="HTX", cases=["tron-htx-coindcx"])["letter"]
    w = htx["wallets"][0]
    assert (w["address"], w["paid_into"], w["tier"]) == (
        "THW7GJwxsZgZMdVrKTn2brDnNXXguUJt6a", "TFTWNgDBkQ5wQoP8RXpRznnHvAVV8x5jLu",
        "published_por")
    notes = " ".join(htx["review_notes"])
    assert "carries no label" in notes and "rests on one label" in notes
    assert "No source was found for HTX's FIU-IND registration" in notes
    assert htx["to"] == "The Nodal Officer, HTX" and htx["channel"] == "regulatory@htx-inc.com"
    assert "No legal entity name is on file for HTX" in notes
    assert "On file for HTX: Named as Huobi" in notes       # the directory's cited remarks
    coindcx = " ".join(_draft(desk)["letter"]["review_notes"])
    assert "labelled by VASP-FUSION's own rules" in coindcx
    assert "No published law-enforcement channel is on file for CoinDCX" in coindcx
    assert ("CoinDCX's FIU-IND registration is as of 4 Dec 2023 (an official list). "
            "Confirm it is still current.") in coindcx
    assert "sweeps into a labelled CoinDCX wallet" in coindcx


def test_a_bitcoin_request_names_the_exchanges_address_and_says_how_it_was_labelled(tmp_path):
    cases = CaseStore(tmp_path / "case.duckdb")
    cases.save(demo_cases("btc-htx")[0])
    desk = DeskService(cases, RequestStore(tmp_path / "desk.duckdb"), Directory.load(),
                       MockSahyogGateway(tmp_path / "outbox"), now=Clock())
    letter = _draft(desk, vasp="HTX", cases=["btc-htx"])["letter"]
    w, = letter["wallets"]
    assert (w["address"], w["paid_into"], w["tier"], w["asset"]) == (
        "19vP8bkaR5K9K5W12QyHoYd7TZpz16BxSV", None, "derived", "BTC")
    notes = " ".join(letter["review_notes"])
    # how the label came about is the cluster, not a sweep; and what the address is, is not known
    assert "spent in one transaction together with a labelled HTX address" in notes
    assert "sweeps into a labelled HTX wallet" not in notes
    assert "is in HTX's wallet cluster" in notes and "is not known" in notes
    assert "is HTX's own labelled wallet, not a customer's deposit address" not in notes
    assert "rests on one label" in notes
    assert "is not a US-dollar stablecoin" in notes


def test_the_payload_follows_the_documented_contract(desk):
    req = _draft(desk)
    p = req["payload"]
    assert set(p) == {"schema", "request_id", "reference", "created_at", "draft", "recipient",
                      "officer", "subject", "cases", "wallets", "asks", "legal_basis",
                      "documents", "generated_by"}
    assert (p["schema"], p["draft"], p["documents"]) == ("vaspfusion-sahyog-request/1", True, [])
    assert p["recipient"] == {
        "vasp": "CoinDCX", "legal_name": "Neblio Technologies Private Limited",
        "jurisdiction": None, "fiu_ind_registered": True, "fiu_ind_as_of": "2023-12-04",
        "channel": None}
    assert [w["address"] for w in p["wallets"]] == [w["address"] for w in req["letter"]["wallets"]]
    assert p["wallets"][0]["evidence_tier"] == "derived"
    assert p["generated_by"] == {"tool": "VASP-FUSION", "code_version": CODE_VERSION}
    json.dumps(p)                                           # plain JSON all the way down


def test_wallets_can_be_chosen_and_a_stranger_is_refused(desk):
    one = _draft(desk, wallets=["TLUQsVHsmUrcWEy3tGrpEdh2ue8z2NHPYk"])
    assert [w["address"] for w in one["letter"]["wallets"]] == ["TLUQsVHsmUrcWEy3tGrpEdh2ue8z2NHPYk"]
    assert one["case_ids"] == ["tron-htx-coindcx"]
    with pytest.raises(DeskError, match="is not a wallet these cases route to CoinDCX") as e:
        _draft(desk, wallets=["TFTWNgDBkQ5wQoP8RXpRznnHvAVV8x5jLu"])
    assert e.value.status == 422


@pytest.mark.parametrize("vasp, cases, status, words", [
    ("CoinDCX", ["nope"], 404, "No case nope"),
    ("CoinDCX", ["tron-abstain"], 422, "under the 0.60 needed"),
    ("OKX", ["tron-coindcx"], 422, "does not reach OKX"),
    ("Unidentified exchange", ["tron-coindcx"], 422, "names no owner"),
])
def test_no_request_without_evidence(desk, vasp, cases, status, words):
    with pytest.raises(DeskError, match=words) as e:
        _draft(desk, vasp=vasp, cases=cases)
    assert e.value.status == status
    assert desk.requests.list() == []


def test_an_alias_drafts_for_the_exchange_it_names(desk):
    assert _draft(desk, vasp="huobi", cases=["tron-htx-coindcx"])["vasp"] == "HTX"


# ---------------------------------------------------------------------- the status machine
def test_a_draft_must_be_approved_before_it_is_sent(desk):
    rid = _draft(desk)["id"]
    with pytest.raises(DeskError, match="drafted cannot become sent. Next: approved") as e:
        desk.patch(rid, "sent")
    assert e.value.status == 409 and not desk.outbox.exists()
    approved = desk.patch(rid, "approved", "Approved by SHO")
    assert approved["letter"]["watermark"] is None and approved["payload"]["draft"] is False
    assert approved["allowed_next"] == ["sent", "drafted", "withdrawn"]
    back = desk.patch(rid, "drafted", "Wrong officer name")
    assert back["letter"]["watermark"] == "Draft - officer review required"
    assert back["payload"]["draft"] is True


def test_sending_writes_the_payload_and_the_letter_to_the_outbox_once(desk):
    rid = _draft(desk)["id"]
    desk.patch(rid, "approved")
    desk.now.later(hours=1)
    sent = desk.patch(rid, "sent", "Sent by the SHO")
    S.RequestDetail.model_validate(sent)
    assert sent["status"] == "sent" and sent["due"] == "2026-10-09"
    assert sorted(p.name for p in desk.outbox.iterdir()) == [f"{rid}.json", f"{rid}.pdf"]
    body = (desk.outbox / f"{rid}.json").read_bytes()
    assert json.loads(body) == sent["payload"] and body == canonical(sent["payload"])
    pdf = (desk.outbox / f"{rid}.pdf").read_bytes()
    assert pdf == desk.pdf(rid) and b"OFFICER REVIEW REQUIRED" not in pdf
    assert sent["payload"]["documents"] == [{
        "name": f"{rid}.pdf", "media_type": "application/pdf",
        "sha256": hashlib.sha256(pdf).hexdigest()}]
    r = sent["receipt"]
    assert (r["gateway"], r["submitted_at"], r["payload_sha256"], r["location"]) == (
        "mock-outbox", "2026-10-02T10:30:00Z", hashlib.sha256(body).hexdigest(),
        f"outbox/{rid}.json")
    last = sent["status_history"][-1]
    assert last["note"].startswith("Sent by the SHO. Written to the SAHYOG outbox (mock-outbox); "
                                   "nothing left this machine, receipt outbox-")
    with pytest.raises(DeskError) as e:
        desk.patch(rid, "sent")
    assert e.value.status == 409


def test_the_status_follows_what_the_exchange_does(desk):
    rid = _draft(desk)["id"]
    for status in ("approved", "sent", "acknowledged", "answered", "freeze_confirmed"):
        req = desk.patch(rid, status)
    assert [h["status"] for h in req["status_history"]] == [
        "drafted", "approved", "sent", "acknowledged", "answered", "freeze_confirmed"]
    assert req["allowed_next"] == [] and req["due"] == "2026-10-09"
    with pytest.raises(DeskError, match="It is closed"):
        desk.patch(rid, "refused")
    with pytest.raises(DeskError) as e:
        desk.patch("req-2026-9999", "approved")
    assert e.value.status == 404


def test_every_status_has_its_transitions_and_every_target_exists():
    assert set(TRANSITIONS) == set(S.RequestStatus.__args__)
    assert all(t in TRANSITIONS for ts in TRANSITIONS.values() for t in ts)


def test_a_gateway_refuses_a_draft_and_a_failed_send_leaves_the_request_approved(desk, tmp_path):
    req = _draft(desk)
    with pytest.raises(GatewayError, match="draft"):
        MockSahyogGateway(tmp_path / "o2").submit(req["payload"], b"%PDF", now=NOW)
    assert not (tmp_path / "o2").exists()

    class Down:
        name = "down"

        def submit(self, payload, pdf, *, now):
            raise GatewayError("portal unreachable")

    desk.patch(req["id"], "approved")
    desk.gateway = Down()
    with pytest.raises(DeskError, match="Not sent: portal unreachable") as e:
        desk.patch(req["id"], "sent")
    assert e.value.status == 502
    again = desk.get(req["id"])
    assert (again["status"], again["due"], again["receipt"]) == ("approved", None, None)
    assert again["payload"]["documents"] == []


# ---------------------------------------------------------------------- desk and VASP page
def test_the_desk_follows_requests_from_draft_to_overdue(desk):
    rows = {r["vasp"]: r for r in desk.desk()["rows"]}
    assert set(rows) == {"CoinDCX", "HTX", "Bitget"} and rows["CoinDCX"]["status"] == "not_requested"
    rid = _draft(desk)["id"]
    row = next(r for r in desk.desk()["rows"] if r["vasp"] == "CoinDCX")
    assert (row["status"], row["unrequested_wallets"], row["last_request_id"]) == ("drafted", 0, rid)
    desk.patch(rid, "approved")
    desk.patch(rid, "sent")
    row = next(r for r in desk.desk()["rows"] if r["vasp"] == "CoinDCX")
    assert row["next_action"] == "Await acknowledgement (reply due 9 Oct 2026)"
    desk.now.later(days=8)
    d = desk.desk()
    S.Desk.model_validate(d)
    assert [f["request_id"] for f in d["follow_ups"]] == [rid]
    page = desk.vasp("CoinDCX", {"tron": 571})
    S.VaspDetail.model_validate(page)
    assert [r["id"] for r in page["requests"]] == [rid] and page["requests"][0]["status"] == "sent"


# ---------------------------------------------------------------------- the PDF
def test_the_pdf_is_the_same_bytes_every_time_and_holds_every_identifier(desk):
    req = _draft(desk)
    pdf = letter_pdf(req, "b8-desk-1")
    assert pdf[:5] == b"%PDF-" and pdf == letter_pdf(desk.get(req["id"]), "b8-desk-1")
    for w in req["letter"]["wallets"]:
        assert w["address"].encode() in pdf
        for h in w["tx_hashes"]:
            assert h.encode() in pdf
    for needle in (b"VF/REQ/2026/0001", b"Neblio Technologies Private Limited", b"Section 94",
                   b"Section 63", b"Section 106", b"Insp. A. Rao, Cyber PS", b"2 Oct 2026",
                   b"1,530 USDT", b"derived by"):
        assert needle in pdf, needle


def test_a_draft_pdf_says_so_and_an_approved_one_does_not(desk):
    req = _draft(desk)
    draft = desk.pdf(req["id"])
    assert b"DRAFT - OFFICER REVIEW REQUIRED" in draft and b"NOT PART OF THE REQUEST" in draft
    assert b"unsigned draft" in draft
    desk.patch(req["id"], "approved")
    final = desk.pdf(req["id"])
    for words in (b"DRAFT", b"NOT PART OF THE REQUEST", b"unsigned draft", b"carries no label"):
        assert words not in final
    assert final != draft


def test_markup_in_a_name_is_printed_as_typed_and_another_script_is_refused(desk):
    req = desk.create("CoinDCX", COINDCX_CASES, ASKS, "Insp. <b>Rao</b> & Co\x00")
    assert req["letter"]["officer"] == "Insp. <b>Rao</b> & Co"
    pdf = desk.pdf(req["id"])
    # the tags are printed character for character, not read as bold
    assert b"(Insp. <) Tj (b) Tj (>) Tj (Rao) Tj (<) Tj (/b) Tj (> & Co) Tj" in pdf
    with pytest.raises(DeskError, match="Latin letters") as e:
        desk.create("HTX", ["tron-htx-coindcx"], ASKS, "Insp. राव")
    assert e.value.status == 422 and len(desk.requests.list()) == 1


# ---------------------------------------------------------------------- review findings
def test_wallets_already_asked_about_are_not_asked_twice(desk):
    first = _draft(desk, cases=["tron-coindcx"])
    with pytest.raises(DeskError, match="already asked about in req-2026-0001") as e:
        _draft(desk, cases=["tron-coindcx"])
    assert e.value.status == 409
    # the default takes only what is new: the second case's wallet
    second = _draft(desk)
    assert [w["case_id"] for w in second["letter"]["wallets"]] == ["tron-htx-coindcx"]
    with pytest.raises(DeskError, match="is already asked about in req-2026-0001") as e:
        _draft(desk, wallets=[first["letter"]["wallets"][0]["address"]])
    assert e.value.status == 409


def test_a_withdrawn_draft_frees_its_wallets_and_a_refused_one_can_be_asked_again(desk):
    rid = _draft(desk, cases=["tron-coindcx"])["id"]
    gone = desk.patch(rid, "withdrawn", "Wrong case")
    assert gone["allowed_next"] == [] and gone["letter"]["watermark"] is not None
    row = next(r for r in desk.desk()["rows"] if r["vasp"] == "CoinDCX")
    assert (row["status"], row["unrequested_wallets"], row["last_request_id"]) == (
        "not_requested", 2, None)
    again = _draft(desk, cases=["tron-coindcx"])
    for status in ("approved", "sent", "refused"):
        desk.patch(again["id"], status)
    assert _draft(desk, cases=["tron-coindcx"])["status"] == "drafted"
    page = desk.vasp("CoinDCX", {})
    assert [r["status"] for r in page["requests"]] == ["drafted", "refused", "withdrawn"]


def test_a_draft_cannot_go_forward_once_its_case_no_longer_supports_it(desk):
    rid = _draft(desk, cases=["tron-coindcx"])["id"]
    case = desk.cases.get("tron-coindcx")
    weaker = [{**c, "confidence": 0.2} for c in case["candidates"]]
    desk.cases.save({**case, "candidates": weaker})
    with pytest.raises(DeskError, match="no longer supports this request") as e:
        desk.patch(rid, "approved")
    assert e.value.status == 409 and desk.get(rid)["status"] == "drafted"
    desk.cases.save(case)
    desk.patch(rid, "approved")
    desk.cases.save({**case, "candidates": weaker})
    with pytest.raises(DeskError, match="Withdraw this request"):
        desk.patch(rid, "sent")
    assert not desk.outbox.exists()
    assert desk.patch(rid, "withdrawn")["status"] == "withdrawn"


def test_a_send_that_failed_to_save_can_be_sent_again(desk, monkeypatch):
    rid = _draft(desk)["id"]
    desk.patch(rid, "approved")
    real = desk.requests.save
    monkeypatch.setattr(desk.requests, "save",
                        lambda r: (_ for _ in ()).throw(RuntimeError("disk full")))
    with pytest.raises(RuntimeError):
        desk.patch(rid, "sent")
    assert desk.get(rid)["status"] == "approved" and (desk.outbox / f"{rid}.json").exists()
    monkeypatch.setattr(desk.requests, "save", real)
    sent = desk.patch(rid, "sent")                        # the same submission: accepted
    assert sent["status"] == "sent" and len(list(desk.outbox.iterdir())) == 2
    tampered = {**sent["payload"], "officer": "someone else"}
    with pytest.raises(GatewayError, match="different contents"):
        desk.gateway.submit(tampered, b"%PDF", now=NOW)


def test_two_status_changes_at_once_cannot_both_act_on_the_same_state(desk):
    import threading
    rid = _draft(desk)["id"]
    desk.patch(rid, "approved")
    results = []

    def go(status):
        try:
            results.append(desk.patch(rid, status)["status"])
        except DeskError as e:
            results.append(e.status)

    threads = [threading.Thread(target=go, args=(s,)) for s in ("sent", "drafted")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = desk.get(rid)
    assert sorted(map(str, results)) in (["409", "sent"], ["409", "drafted"])
    assert (final["status"] == "sent") == (desk.outbox / f"{rid}.json").exists()


def test_the_served_letter_is_the_one_that_was_sent(desk, monkeypatch):
    rid = _draft(desk)["id"]
    desk.patch(rid, "approved")
    sent = desk.patch(rid, "sent")
    stored = (desk.outbox / f"{rid}.pdf").read_bytes()
    monkeypatch.setattr("vaspfusion.desk.service.letter_pdf",
                        lambda *a, **k: b"%PDF-rendered-by-a-later-version")
    assert desk.pdf(rid) == stored
    assert hashlib.sha256(desk.pdf(rid)).hexdigest() == sent["payload"]["documents"][0]["sha256"]


def test_a_label_spelling_of_an_exchange_is_the_directorys_exchange(desk):
    case = desk.cases.get("tron-coindcx")
    renamed = [{**c, "vasp": "coindcx"} if c["vasp"] == "CoinDCX" else c
               for c in case["candidates"]]
    desk.cases.save({**case, "candidates": renamed})
    rows = [r for r in desk.desk()["rows"] if r["vasp"].lower() == "coindcx"]
    assert [(r["vasp"], r["wallet_count"]) for r in rows] == [("CoinDCX", 2)]
    assert len(_draft(desk)["letter"]["wallets"]) == 2
    assert len([w for w in desk.vasp("CoinDCX", {})["wallets"] if w["routable"]]) == 2


def test_one_wallet_in_two_cases_is_counted_once_in_the_letter(desk):
    case = desk.cases.get("tron-coindcx")
    desk.cases.save({**case, "id": "tron-coindcx-again", "case_ref": "DEMO/2026/201"})
    letter = _draft(desk, cases=["tron-coindcx", "tron-coindcx-again"])["letter"]
    assert len(letter["wallets"]) == 2 and "1 wallet attributed to CoinDCX" in letter["subject"]
    assert len(letter["review_notes"]) == len(set(letter["review_notes"]))
