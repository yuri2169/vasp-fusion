"""The offshore route: a draft letter of request for a Court or authority outside India.

For an exchange that no source shows as registered with FIU-IND, a notice under
section 94 BNSS may go unanswered. The route the Sanhita gives for evidence held
abroad is section 112: on the investigating officer's application a Criminal Court may
issue a letter of request to a Court or authority of that country or place, and the
letter is transmitted as the Central Government specifies.

So what is made here is a draft for the officer and the Court, with the same evidence
table as the domestic letter. It is not a request of the desk: it has no reference
(the Court gives one), no status, is never stored and is never sent by this tool. Its
watermark never comes off. Where the directory holds no cited jurisdiction the country
is left blank for the officer.
"""
from __future__ import annotations

from datetime import date

from .legal import letter_of_request_basis
from .letter import _case_name, _join, letter_wallet, review_notes
from .routing import day

WATERMARK = "Draft: officer and competent authority review required"
KIND = "letter_of_request"
ASKS = ("kyc", "transactions", "preservation")       # evidence only: see the review notes
BLANK = "____________________"
ASK_TEXT = {
    "kyc": "the KYC and account-opening records of the account or accounts that the "
           "wallets listed below belong to, or that were credited through them",
    "transactions": "the transaction history of those accounts, including the deposits "
                    "listed below, internal transfers, withdrawals and the destination of "
                    "the funds",
    "preservation": "to preserve all records, logs and communications relating to "
                    "those accounts until the request is executed",
}


def letter_of_request(*, vasp: str, entry: dict, wallets: list[dict], officer: str,
                      today: date) -> dict:
    """`RequestLetter`, with `kind: letter_of_request`, for one exchange."""
    cases, seen = [], set()
    for w in wallets:
        if w["case_id"] not in seen:
            seen.add(w["case_id"])
            cases.append({"case_id": w["case_id"], "case_ref": w["case_ref"],
                          "complaint_no": w["complaint_no"], "wallet": w["suspect"],
                          "chain": w.get("case_chain") or w["chain"]})
    names = [_case_name(c) for c in cases]
    n = len({w["address"] for w in wallets})
    plural = "s" if n != 1 else ""
    holder = f"{entry['legal_name']} ({vasp})" if entry.get("legal_name") else vasp
    place = entry.get("jurisdiction")
    basis, citations = letter_of_request_basis()
    paragraphs = [
        "This is a draft of a letter of request, prepared for the Court's consideration on "
        "the application of the investigating officer in the "
        + ("matter" if len(cases) == 1 else f"{len(cases)} matters")
        + f" referred to above ({_join(names)}).",
        f"Analysis of public blockchain records traced funds from the wallet{'s' if len(cases) != 1 else ''} "
        "under investigation ("
        + _join([f"{c['wallet']} on {c['chain'].capitalize()}, {_case_name(c)}" for c in cases])
        + f") to the {n} wallet{plural} listed in the table below, which the analysis "
        f"attributes to {vasp}. The table states, for each wallet, the amount traced, the "
        "transactions, and the evidence tier and confidence of the attribution.",
        (f"The records of the accounts behind these wallets are held by {holder}. "
         + (f"The directory this office keeps gives its jurisdiction as {place}."
           if place else
           f"The country or place where {vasp} holds them is to be stated by the officer: "
            "none is on record with this office.")),
        "The competent Court or authority is requested to require "
        f"{holder}, or any other person in possession of them, to produce, and to forward "
        "to the Court issuing this letter, the authenticated copies of: (a) "
        f"{ASK_TEXT['kyc']}; and (b) {ASK_TEXT['transactions']}. It is further requested "
        f"to require {holder} {ASK_TEXT['preservation']}.",
        "This letter is to be transmitted in the manner specified by the Central Government.",
    ]
    notes = [
        "This is a draft. A letter of request is issued by a Criminal Court on the "
        "application of the investigating officer or an officer superior in rank, and is "
        "transmitted in the manner the Central Government specifies. This tool sends "
        "nothing and records no sending.",
        "The draft asks for evidence only. An order attaching property outside India is a "
        "separate order of the Court; it is not drafted here.",
        "No reference is printed: the issuing Court gives the letter its number.",
    ]
    if not place:
        notes.append(f"No jurisdiction is on record for {vasp}. Fill in the country or "
                     "place, and the Court or authority competent there, before the "
                     "application is made.")
    notes += review_notes(wallets, entry)
    to = "The competent Court or authority, " + (place or BLANK)
    return {
        "kind": KIND, "reference": "", "date": today.isoformat(), "to": to,
        "subject": f"Draft letter of request for evidence held by {holder}, in respect of "
                   f"{n} wallet{plural} ({_join(names)})",
        "paragraphs": paragraphs, "wallets": [letter_wallet(w) for w in wallets],
        "asks": list(ASKS), "legal_basis": basis, "officer": officer,
        "watermark": WATERMARK, "cases": cases, "legal_citations": citations,
        "channel": None, "review_notes": list(dict.fromkeys(notes)),
    }


def as_request(vasp: str, letter: dict) -> dict:
    """The shape `letter_pdf` draws (a `RequestDetail` has the letter under `letter`)."""
    return {"vasp": vasp, "letter": letter}
