"""The legal-basis line of a request, and where each section it names can be read.

Two sections are always cited: the notice to produce (section 94 BNSS) and the
certificate for electronic records (section 63 BSA). A request that asks for a freeze
also cites section 106 BNSS, the power under which an investigating officer restrains
property suspected to be connected with an offence. The wording is a draft for the
officer to review; nothing here is legal advice.
"""
from __future__ import annotations

BNSS = "Bharatiya Nagarik Suraksha Sanhita, 2023"
BSA = "Bharatiya Sakshya Adhiniyam, 2023"
# India Code: the Government of India's repository of central acts
BNSS_SOURCE_URL = "https://www.indiacode.nic.in/handle/123456789/20099"
BSA_SOURCE_URL = "https://www.indiacode.nic.in/handle/123456789/20063"

CITATIONS = {
    "bnss-94": {"section": "94", "act": BNSS,
                "heading": "Summons to produce document or other thing", "url": BNSS_SOURCE_URL},
    "bsa-63": {"section": "63", "act": BSA,
               "heading": "Admissibility of electronic records", "url": BSA_SOURCE_URL},
    "bnss-106": {"section": "106", "act": BNSS,
                 "heading": "Power of police officer to seize certain property",
                 "url": BNSS_SOURCE_URL},
    # The offshore route. Read on 8 Oct 2026 in the text of the Bharatiya Nagarik Suraksha
    # (Second) Sanhita, 2023 as hosted by PRS Legislative Research (the Bill that became
    # Act 46 of 2023): section 112(1) to (3) in full. India Code refused the fetch (HTTP
    # 403), so the heading was matched on a second published copy of the Act instead.
    "bnss-112": {"section": "112", "act": BNSS,
                 "heading": "Letter of request to competent authority for investigation "
                            "in a country or place outside India",
                 "url": BNSS_SOURCE_URL},
}

NOTICE = (f"Notice under Section 94 of the {BNSS}. Electronic records to be furnished with "
          f"a certificate under Section 63 of the {BSA}.")
FREEZE = f" The freeze is requested under Section 106 of the {BNSS}."


def legal_basis(asks: list[str]) -> tuple[str, list[dict]]:
    """(the legal-basis line, its citations) for a request with these asks."""
    keys = ["bnss-94", "bsa-63"] + (["bnss-106"] if "freeze" in asks else [])
    return NOTICE + (FREEZE if "freeze" in asks else ""), [dict(CITATIONS[k]) for k in keys]


LETTER_OF_REQUEST = (
    f"Letter of request under Section 112 of the {BNSS}: issued by a Criminal Court on "
    "the application of the investigating officer, to a Court or authority competent to "
    "deal with it in the country or place where the evidence may be available, and "
    "transmitted in the manner the Central Government specifies.")


def letter_of_request_basis() -> tuple[str, list[dict]]:
    """(the legal-basis line, its citation) of a letter-of-request draft."""
    return LETTER_OF_REQUEST, [dict(CITATIONS["bnss-112"])]
