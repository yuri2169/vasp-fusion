"""The offshore route: a letter-of-request draft, and the reply day an officer sets."""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deskkit import NOW, demo_cases  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.desk.directory import Directory  # noqa: E402
from vaspfusion.desk.foreign import WATERMARK, as_request  # noqa: E402
from vaspfusion.desk.gateway import MockSahyogGateway  # noqa: E402
from vaspfusion.desk.legal import BNSS, letter_of_request_basis  # noqa: E402
from vaspfusion.desk.pdf import letter_pdf  # noqa: E402
from vaspfusion.desk.routing import follow_ups  # noqa: E402
from vaspfusion.desk.service import DeskError, DeskService  # noqa: E402
from vaspfusion.store.cases import CaseStore  # noqa: E402
from vaspfusion.store.requests import RequestStore  # noqa: E402

OFFICER = "Insp. A. Rao, Cyber PS"
ASKS = ["kyc", "transactions"]


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


@pytest.fixture
def desk(tmp_path):
    cases = CaseStore(tmp_path / "case.duckdb")
    for case in demo_cases():
        cases.save(case)
    svc = DeskService(cases, RequestStore(tmp_path / "desk.duckdb"), Directory.load(),
                      MockSahyogGateway(tmp_path / "outbox"), now=Clock())
    svc.outbox = tmp_path / "outbox"
    return svc


# ---------------------------------------------------------------------- the draft
def test_the_draft_cites_section_112_and_carries_the_evidence_of_the_domestic_letter(desk):
    made = desk.letter_of_request("HTX", ["tron-htx-coindcx"], OFFICER)
    S.LetterOfRequest.model_validate({**made, "pdf_url": "/x"})
    letter = made["letter"]
    assert letter["kind"] == "letter_of_request" and letter["reference"] == ""
    assert letter["watermark"] == WATERMARK == \
        "Draft: officer and competent authority review required"
    assert letter["legal_citations"] == [{
        "section": "112", "act": BNSS, "url": "https://www.indiacode.nic.in/handle/123456789/20099",
        "heading": "Letter of request to competent authority for investigation in a country "
                   "or place outside India"}]
    assert "Section 112" in letter["legal_basis"] and "Section 94" not in letter["legal_basis"]
    domestic = desk.create("HTX", ["tron-htx-coindcx"], ASKS, OFFICER)["letter"]
    assert letter["wallets"] == domestic["wallets"] and letter["cases"] == domestic["cases"]
    assert "freeze" not in letter["asks"]
    # nothing was stored for it, and nothing went to the outbox
    assert [r["id"] for r in desk.requests.list()] == ["req-2026-0001"]
    assert not desk.outbox.exists() or not list(desk.outbox.iterdir())


def test_a_blank_jurisdiction_stays_blank_for_the_officer(desk):
    made = desk.letter_of_request("HTX", None, OFFICER)
    entry, letter = made["directory"], made["letter"]
    assert entry["jurisdiction"] is None            # nothing cited in the directory
    assert letter["to"] == "The competent Court or authority, ____________________"
    assert any("No jurisdiction is on record for HTX" in n for n in letter["review_notes"])
    assert "none is on record with this office" in letter["paragraphs"][2]
    assert made["recommended"] is False             # HTX publishes a channel


def test_a_cited_jurisdiction_is_used(desk, monkeypatch):
    real = desk.directory.get
    monkeypatch.setattr(desk.directory, "get",
                        lambda name: {**real(name), "jurisdiction": "Seychelles"})
    letter = desk.letter_of_request("HTX", None, OFFICER)["letter"]
    assert letter["to"] == "The competent Court or authority, Seychelles"
    assert not any("No jurisdiction" in n for n in letter["review_notes"])


def test_the_draft_never_says_it_was_sent(desk):
    made = desk.letter_of_request("HTX", None, OFFICER)
    letter = made["letter"]
    said = " ".join(letter["paragraphs"] + [letter["subject"], letter["legal_basis"]]).lower()
    for claim in ("has been sent", "was sent", "transmitted on", "issued on"):
        assert claim not in said
    pdf = letter_pdf(as_request("HTX", letter), "test")
    assert pdf == letter_pdf(as_request("HTX", letter), "test")       # same draft, same bytes
    assert b"DRAFT: OFFICER AND COMPETENT AUTHORITY REVIEW REQUIRED. NOT SENT." in pdf
    assert b"Letter-of-request draft" in pdf and b"Section 112" in pdf
    assert any("sends" in n and "nothing" in n for n in letter["review_notes"])


def test_a_registered_exchange_gets_the_domestic_notice_not_this(desk):
    with pytest.raises(DeskError) as e:
        desk.letter_of_request("CoinDCX", None, OFFICER)
    assert e.value.status == 422 and "domestic notice applies" in str(e.value)


def test_no_routed_wallet_no_draft(desk):
    with pytest.raises(DeskError) as e:
        desk.letter_of_request("HTX", ["tron-coindcx"], OFFICER)
    assert e.value.status == 404
    with pytest.raises(DeskError) as e:
        desk.letter_of_request("HTX", ["no-such-case"], OFFICER)
    assert e.value.status == 404
    with pytest.raises(DeskError) as e:
        desk.letter_of_request("HTX", None, "  ")
    assert e.value.status == 422


def test_the_basis_line_names_who_issues_and_who_transmits():
    line, cites = letter_of_request_basis()
    assert "issued by a Criminal Court" in line and "Central Government" in line
    assert [c["section"] for c in cites] == ["112"]


# ---------------------------------------------------------------------- the desk
def test_the_desk_offers_the_draft_and_orders_the_two_exchange_case(desk):
    board = desk.desk()
    S.Desk.model_validate(board)
    rows = {r["vasp"]: r for r in board["rows"]}
    assert (rows["CoinDCX"]["route"], rows["CoinDCX"]["letter_of_request"]) == \
        ("domestic_notice", False)
    assert (rows["HTX"]["route"], rows["HTX"]["letter_of_request"]) == ("direct_channel", True)
    assert [(w["case_id"], [x["vasp"] for x in w["order"]["exchanges"]])
            for w in board["write_first"]] == [("tron-htx-coindcx", ["CoinDCX", "HTX"])]


# ---------------------------------------------------------------------- the reply day
def _sent(desk, **kw):
    req = desk.create("CoinDCX", ["tron-coindcx"], ASKS, OFFICER)
    desk.patch(req["id"], "approved")
    return desk.patch(req["id"], "sent", **kw)


def test_the_officer_sets_the_reply_day_when_marking_sent(desk):
    due = (NOW + timedelta(days=3)).date()
    req = _sent(desk, due=due)
    S.RequestDetail.model_validate({**req, "pdf_url": "/x"})
    assert (req["due"], req["due_basis"]) == (due.isoformat(), "officer")


def test_without_one_the_office_setting_applies_and_says_so(desk):
    req = _sent(desk)
    assert req["due"] == (NOW + timedelta(days=7)).date().isoformat()
    assert req["due_basis"] == "office_setting"


def test_a_past_day_or_a_day_on_another_step_is_refused(desk):
    req = desk.create("CoinDCX", ["tron-coindcx"], ASKS, OFFICER)
    with pytest.raises(DeskError) as e:
        desk.patch(req["id"], "approved", due=NOW.date())
    assert e.value.status == 422
    desk.patch(req["id"], "approved")
    with pytest.raises(DeskError) as e:
        desk.patch(req["id"], "sent", due=(NOW - timedelta(days=1)).date())
    assert e.value.status == 422 and "in the past" in str(e.value)
    assert desk.get(req["id"])["status"] == "approved"


def test_follow_ups_put_the_overdue_first_then_the_soonest_due():
    today = NOW.date()

    def r(i, status, days):
        return {"id": f"req-{i}", "vasp": f"X{i}", "status": status,
                "due": (today + timedelta(days=days)).isoformat() if days is not None else None}
    found = follow_ups([r(1, "sent", 5), r(2, "acknowledged", -2), r(3, "sent", 0),
                        r(4, "sent", -9), r(5, "answered", -4), r(6, "approved", None),
                        r(7, "sent", 1)], today)
    assert [(f["request_id"], f["kind"], f["days_left"]) for f in found] == [
        ("req-4", "reply_overdue", -9), ("req-2", "reply_overdue", -2),
        ("req-3", "reply_due", 0), ("req-7", "reply_due", 1), ("req-1", "reply_due", 5)]
    assert found[2]["text"].startswith("X3: reply due today")
    assert "in 1 day (" in found[3]["text"] and "in 5 days (" in found[4]["text"]
