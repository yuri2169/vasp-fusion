"""The request letter and its SAHYOG payload, built from routed wallets.

Both are plain dicts (`RequestLetter`, and the payload documented in
docs/sahyog_contract.md). A letter never shortens an address or a transaction hash:
the exchange has to be able to search for them. What the officer should check before
approving goes in `review_notes`, which is not part of the request.
"""
from __future__ import annotations

from datetime import date, datetime

from ..explain import fmt
from .legal import legal_basis
from .routing import day

SCHEMA = "vaspfusion-sahyog-request/1"
WATERMARK = "Draft - officer review required"
ASK_ORDER = ("kyc", "transactions", "freeze", "preservation")
ASK_SUBJECT = {"kyc": "KYC records", "transactions": "transaction records",
               "freeze": "a freeze", "preservation": "preservation of records"}
ASK_TEXT = {
    "kyc": "furnish the KYC and account-opening records of the account or accounts that "
           "the wallets listed below belong to, or that were credited through them",
    "transactions": "furnish the transaction history of those accounts, including the "
                    "deposits listed below, internal transfers, withdrawals and the "
                    "destination of the funds",
    "freeze": "freeze those accounts to the extent of the amounts listed below, and "
              "confirm the freeze and the balance held",
    "preservation": "preserve all records, logs and communications relating to those "
                    "accounts until further notice",
}


# An instant-swap service takes the deposit into custody and pays out from its own pool,
# often on another chain: the payout cannot be matched on-chain, so it is asked for.
SWAP_TRANSACTIONS = (
    "furnish, for each deposit listed below, the swap order it belongs to and the payout "
    "made for it: the payout chain, the payout address, the payout transaction hash, the "
    "asset and amount paid out, the time, and any refund address given; and the further "
    "orders placed from the same account, device or IP address")
SWAP_PARAGRAPH = (
    "{vasp} operates a swap service: it receives a deposit and pays the customer out from "
    "its own funds, in another asset or on another chain. The payout is therefore not "
    "visible from the deposit on the public record, and this office cannot follow the funds "
    "further without the order records requested below.")


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _case_name(case: dict) -> str:
    return case.get("case_ref") or case.get("complaint_no") or case["case_id"]


def letter_wallet(w: dict) -> dict:
    """A routed wallet (desk/routing.py) as a `LetterWallet` row."""
    return {"address": w["address"], "chain": w["chain"], "amount_usd": w["amount_usd"],
            "tier": w["tier"], "first_seen": w["reached_at"], "tx_hashes": w["tx_hashes"],
            "case_id": w["case_id"], "case_ref": w["case_ref"], "asset": w["asset"],
            "amount": w["amount"], "confidence": w["confidence"],
            "paid_into": w["paid_into"], "label": w["label"]}


def _registration_note(entry: dict) -> str:
    name, reg = entry["name"], entry.get("fiu_ind_registered")
    if reg is None:
        return (f"No source was found for {name}'s FIU-IND registration. Check whether it "
                "is a reporting entity before relying on a reply.")
    as_of = day(entry["fiu_ind_as_of"])
    if reg is False:
        return (f"FIU-IND named {name} as operating without registration (as of {as_of}). "
                "A notice under Indian law may not be answered; consider the mutual legal "
                "assistance route.")
    kinds = {s.get("kind") for s in entry.get("sources", [])
             if s["field"] == "fiu_ind_registered"}
    if kinds == {"official"}:
        return (f"{name}'s FIU-IND registration is as of {as_of} (an official list). "
                "Confirm it is still current.")
    return (f"{name}'s FIU-IND registration is the exchange's own statement (as of {as_of}); "
            "no official list naming it was found.")


def _by_cluster(w: dict) -> bool:
    """The wallet's label was derived from its Bitcoin wallet cluster (cluster.py)."""
    from ..cluster import CLUSTER_MARK
    return CLUSTER_MARK in (w.get("label") or "")


def review_notes(wallets: list[dict], entry: dict) -> list[str]:
    """What the reviewing officer should know before approving. Not sent."""
    notes = []
    for w in wallets:
        if w["paid_into"]:
            notes.append(
                f"{w['address']} carries no label. It is named because it passed on "
                f"everything it received from this trail to {w['vasp']}'s wallet "
                f"{w['paid_into']}; it may be a customer's deposit address or an "
                "intermediary.")
        elif _by_cluster(w):
            notes.append(
                f"{w['address']} is in {w['vasp']}'s wallet cluster. Whether it is a "
                f"customer's deposit address or one of {w['vasp']}'s own wallets is not "
                f"known; {w['vasp']} can identify the account from the transactions listed "
                "for it.")
        elif w["kind"] != "deposit":
            notes.append(
                f"{w['address']} is {w['vasp']}'s own labelled wallet, not a customer's "
                f"deposit address. {w['vasp']} can identify the account only from the "
                "transactions listed for it.")
        if w.get("category") == "swap_service":
            notes.append(
                f"{w['vasp']} is a swap service. It may hold no KYC on the customer; the "
                "payout chain, address and transaction it is asked for are what lets the "
                "trace go on. Trace the payout address as a new case when the reply comes.")
        if w.get("chain") and w.get("case_chain") and w["chain"] != w["case_chain"]:
            notes.append(
                f"{w['address']} is on {fmt.chain_name(w['chain'])}, not on "
                f"{fmt.chain_name(w['case_chain'])} where the traced wallet is: the funds "
                "crossed a bridge on the way. The case file lists the bridge transactions.")
        if w["counterfactual_holds"] is False:
            notes.append(
                f"Naming {w['vasp']} for {w['address']} rests on one label "
                f"({fmt.tier_words(w['tier'])}): without it the trace does not reach "
                f"{w['vasp']}.")
        if w["tier"] == "derived":
            how = (f"it was spent in one transaction together with a labelled {w['vasp']} "
                   "address" if _by_cluster(w) else
                   f"it sweeps into a labelled {w['vasp']} wallet")
            notes.append(
                f"{w['address']} was labelled by VASP-FUSION's own rules ({how}), not by an "
                "outside source.")
        if w["amount_usd"] is None:
            notes.append(f"{fmt.amount(w['amount'], w['asset'])} is not a US-dollar "
                         "stablecoin; no rupee or dollar value is stated.")
    notes.append("Confidence figures are the tool's assessment (label weight, hops and "
                 "share of funds; calibrated only where a range is shown in the case). "
                 "They are a lead for investigation, not proof of ownership.")
    notes.append(_registration_note(entry))
    if not entry.get("le_request_channel"):
        notes.append(f"No published law-enforcement channel is on file for {entry['name']}.")
    if not entry.get("legal_name"):
        notes.append(f"No legal entity name is on file for {entry['name']}; the letter is "
                     "addressed to the trade name.")
    notes += [f"On file for {entry['name']}: {n}" for n in entry.get("notes", [])]
    return list(dict.fromkeys(notes))        # one wallet in two cases: say it once


def draft_letter(*, reference: str, vasp: str, entry: dict, wallets: list[dict],
                 asks: list[str], officer: str, today: date) -> dict:
    """`RequestLetter` for one exchange: every case, every wallet, the asks, the law."""
    asks = [a for a in ASK_ORDER if a in asks]
    cases, seen = [], set()
    for w in wallets:
        if w["case_id"] not in seen:
            seen.add(w["case_id"])
            cases.append({"case_id": w["case_id"], "case_ref": w["case_ref"],
                          "complaint_no": w["complaint_no"], "wallet": w["suspect"],
                          "chain": w.get("case_chain") or w["chain"]})
    names = [_case_name(c) for c in cases]
    n = len({w["address"] for w in wallets})         # one wallet in two cases is one wallet
    plural = "s" if n != 1 else ""
    legal_name = entry.get("legal_name")
    to = f"The Nodal Officer, {legal_name} ({vasp})" if legal_name else f"The Nodal Officer, {vasp}"
    basis, citations = legal_basis(asks)
    swap = bool(wallets) and all(w.get("category") == "swap_service" for w in wallets)
    if swap and "transactions" not in asks:     # the payout is the point of the request
        asks = [x for x in ASK_ORDER if x in (*asks, "transactions")]
        basis, citations = legal_basis(asks)
    ask_text = {**ASK_TEXT, "transactions": SWAP_TRANSACTIONS} if swap else ASK_TEXT
    paragraphs = [
        "This office is investigating the "
        + ("matter" if len(cases) == 1 else f"{len(cases)} matters")
        + f" referred to above ({_join(names)}).",
        f"Analysis of public blockchain records traced funds from the wallet{'s' if len(cases) != 1 else ''} "
        "under investigation ("
        + _join([f"{c['wallet']} on {c['chain'].capitalize()}, {_case_name(c)}" for c in cases])
        + f") to the {n} wallet{plural} listed in the table below, which the "
        f"analysis attributes to {vasp}. The table states, for each wallet, the amount traced, "
        "the transactions, and the evidence tier and confidence of the attribution.",
        *([SWAP_PARAGRAPH.format(vasp=vasp)] if swap else []),
        "You are requested to: "
        + "; ".join(f"({chr(97 + i)}) {ask_text[a]}" for i, a in enumerate(asks)) + ".",
        f"Please reply quoting reference {reference}.",
    ]
    return {
        "reference": reference, "date": today.isoformat(), "to": to,
        "subject": f"Request for {_join([ASK_SUBJECT[a] for a in asks])} in respect of "
                   f"{n} wallet{plural} attributed to {vasp} ({_join(names)})",
        "paragraphs": paragraphs, "wallets": [letter_wallet(w) for w in wallets],
        "asks": asks, "legal_basis": basis, "officer": officer, "watermark": WATERMARK,
        "cases": cases, "legal_citations": citations,
        "channel": entry.get("le_request_channel"),
        "review_notes": review_notes(wallets, entry),
    }


def build_payload(*, request_id: str, created_at: datetime | str, vasp: str, entry: dict,
                  letter: dict, code_version: str) -> dict:
    """The JSON a SAHYOG gateway is handed (docs/sahyog_contract.md). `draft` is true
    until the request is approved; a gateway must refuse a draft."""
    created = created_at if isinstance(created_at, str) else \
        created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": SCHEMA, "request_id": request_id, "reference": letter["reference"],
        "created_at": created, "draft": letter["watermark"] is not None,
        "recipient": {
            "vasp": vasp, "legal_name": entry.get("legal_name"),
            "jurisdiction": entry.get("jurisdiction"),
            "fiu_ind_registered": entry.get("fiu_ind_registered"),
            "fiu_ind_as_of": str(entry["fiu_ind_as_of"]) if entry.get("fiu_ind_as_of") else None,
            "channel": entry.get("le_request_channel"),
        },
        "officer": letter["officer"],
        "subject": letter["subject"],
        "cases": letter["cases"],
        "wallets": [{
            "address": w["address"], "chain": w["chain"], "case_id": w["case_id"],
            "asset": w["asset"], "amount": w["amount"], "amount_usd": w["amount_usd"],
            "evidence_tier": w["tier"], "confidence": w["confidence"],
            "first_seen": w["first_seen"], "tx_hashes": w["tx_hashes"],
            "paid_into": w["paid_into"],
        } for w in letter["wallets"]],
        "asks": letter["asks"],
        "legal_basis": {"text": letter["legal_basis"], "citations": letter["legal_citations"]},
        "documents": [],
        "generated_by": {"tool": "VASP-FUSION", "code_version": code_version},
    }
