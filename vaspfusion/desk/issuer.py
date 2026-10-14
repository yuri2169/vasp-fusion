"""A draft request to the issuer of USDT to freeze traced funds.

The issuer of USDT (Tether) can freeze an address: the token contract keeps a blacklist
(labels/frozen.py). That is a route to stopping funds that exists outside SAHYOG, and it
is the only one when the money sits at, or passed through, an address that is not an
exchange account: no exchange can be asked to act on it.

The draft is offered beside the exchange request when the traced asset is USDT on a
chain whose contract we read (Tron, Ethereum) and the trace has such an address. It
lists each address with the USDT that reached it, what the trace left there, the times
and the transaction hashes, and the case's evidence fingerprint. The officer's details
and the legal provision are left blank for the officer. It is a draft, and nothing here
sends it.

The only process cited is what Tether itself publishes: its Law Enforcement Requests
Policy says a request to freeze should come with appropriate legal process, and gives an
address for inquiries about its policies and procedures. It names no channel for
submitting a request, so none is given here as one.
"""
from __future__ import annotations

from io import BytesIO

from ..explain import fmt
from ..labels.frozen import CONTRACTS, FreezeList, mark_text

ISSUER = "Tether (the issuer of USDT)"
ASSET = "USDT"
POLICY = {
    "title": "Law Enforcement Requests Policy",
    "publisher": "Tether",
    "url": "https://tether.to/en/legal/?tab=law-enforcement-requests",
    "updated": "3 January 2018",
    "read": "14 October 2026",
    "says": ("Requests to freeze Tether addresses should be accompanied by appropriate legal "
             "process. Inquiries from law enforcement about its policies and procedures: "
             "inforequests@tether.to."),
}
CHANNEL = (f"Tether publishes no channel for submitting a request. For inquiries about its "
           f"policies and procedures it gives inforequests@tether.to ({POLICY['publisher']}, "
           f"{POLICY['title']}, last updated {POLICY['updated']}, {POLICY['url']}).")
WATERMARK = "Draft - officer review required"
BLANK = "____________________"
# a wallet with one of these labels is a service that can be asked itself, or a contract
SERVICE_ROLES = {"exchange", "exchange_hot", "exchange_deposit", "custodial_wallet",
                 "swap_service", "bridge", "mixer"}
SERVICE_CATEGORIES = {"exchange", "custodial_wallet", "swap_service", "bridge", "mixer", "defi"}
EPS = 1e-6
DUST = 1.0      # USDT: less than this left at an address off the Hop Rail is not listed


def _service(node: dict) -> bool:
    lab = node.get("label") or {}
    return node.get("role") in SERVICE_ROLES or lab.get("category") in SERVICE_CATEGORIES


def addresses(case: dict, freeze_list: FreezeList | None = None) -> list[dict]:
    """The non-exchange addresses USDT reached in this trace: on the Hop Rail (passed
    through) or with traced money left at them (held), most money first."""
    fl = freeze_list or FreezeList.load()
    graph = case.get("graph") or {}
    edges = [e for e in graph.get("edges") or []
             if e.get("direction") == "outbound" and e.get("asset") == ASSET]
    on_path = {h["to_address"] for h in case.get("hop_rail") or []}
    out = []
    for n in graph.get("nodes") or []:
        chain = n.get("chain") or case["chain"]
        if n.get("role") == "suspect" or chain not in CONTRACTS or _service(n):
            continue
        into = sorted((e for e in edges if e["target"] == n["id"]),
                      key=lambda e: (e["block_time"], e["tx_hash"]))
        if not into:
            continue
        got = sum(e["traced_amount"] for e in into)
        sent = sum(e["traced_amount"] for e in edges if e["source"] == n["id"])
        held = max(0.0, got - sent)
        address = n.get("address") or n["id"].rpartition(":")[2]
        passed = address in on_path
        if held < DUST and not passed:
            continue
        frozen = fl.lookup(address, chain)
        lab = n.get("label") or {}
        out.append({
            "address": address, "chain": chain, "hop": n.get("hop"),
            "role": "held" if held > EPS else "passed_through",
            "busy": bool(n.get("is_hub")),
            "received": round(got, 6), "held": round(held, 6), "asset": ASSET,
            "first_seen": into[0]["block_time"], "last_seen": into[-1]["block_time"],
            "tx_hashes": sorted({e["tx_hash"] for e in into}),
            "label": lab.get("label") or lab.get("entity"),
            "frozen": mark_text(frozen) if frozen else None,
        })
    return sorted(out, key=lambda a: (-a["held"], -a["received"], a["address"]))


def issuer_request(case: dict, freeze_list: FreezeList | None = None) -> dict:
    """`IssuerRequest`: offered or not, why, and the draft."""
    if case.get("status") != "done" or case.get("outcome") is None:
        return {"offered": False, "reason": "The case has no finished trace yet.", "draft": None}
    if case.get("asset") != ASSET or case.get("chain") not in CONTRACTS:
        return {"offered": False, "draft": None,
                "reason": f"The traced asset is {case.get('asset') or 'not known'} on "
                          f"{fmt.chain_name(case['chain'])}. A request to the issuer applies "
                          "to USDT on Tron or Ethereum, whose freeze lists this tool reads."}
    found = addresses(case, freeze_list)
    open_ = [a for a in found if not a["frozen"]]
    if not open_:
        return {"offered": False, "draft": None,
                "reason": ("Every address outside an exchange that the traced USDT reached is "
                           "already frozen by the issuer." if found else
                           "The traced USDT did not stop at, or pass through, an address "
                           "outside an exchange: the exchange request covers it.")}
    one = len(open_) == 1
    held = any(a["role"] == "held" for a in open_)
    verb = ("holds" if one else "hold") if held else "passed on"
    return {"offered": True, "reason": (
        f"{len(open_)} address{'' if one else 'es'} outside any exchange {verb} traced USDT. "
        f"No exchange can be asked to act on {'it' if one else 'them'}; the issuer of USDT can "
        "freeze it at an address."),
        "draft": _draft(case, open_, [a for a in found if a["frozen"]])}


def _draft(case: dict, wallets: list[dict], already: list[dict]) -> dict:
    ref = case.get("case_ref") or case["id"]
    fp = (case.get("provenance") or {}).get("findings_sha256")
    held = sum(a["held"] for a in wallets)
    paragraphs = [
        f"This office is investigating case {ref}. Funds were traced on the public "
        f"{fmt.chain_name(case['chain'])} blockchain from the wallet {case['address']}.",
        f"Traced USDT stopped at, or passed through, the {len(wallets)} address"
        f"{'es' if len(wallets) != 1 else ''} listed below. None is an account at an "
        "exchange, so no exchange can be asked to act on it. At the time of the trace "
        f"{fmt.amount(held, ASSET)} of the traced funds was left at them.",
        "You are requested to freeze the USDT held at the addresses listed below, to "
        "confirm for each the time of the freeze and the balance frozen, and to preserve "
        "your records relating to them until further notice.",
        "The trace can be checked independently: every address and transaction below is "
        "on the public blockchain, and the findings of the trace have the fingerprint "
        f"SHA-256 {fp or BLANK}.",
    ]
    notes = [
        f"Tether's own published policy ({POLICY['title']}, last updated {POLICY['updated']}, "
        f"{POLICY['url']}, read {POLICY['read']}) says a request to freeze should come with "
        "appropriate legal process. Attach it, and enter the legal provision above.",
        "Tether names no channel for submitting a request. The address it gives "
        "(inforequests@tether.to) is for inquiries about its policies and procedures.",
        "'Held' is what the trace left at the address when it ran. The balance today may "
        "be different: check it on a block explorer before sending.",
        "An address outside any exchange may still belong to a service this tool has no "
        "label for. Check each address before asking for it to be frozen; those marked "
        "as having a great many counterparties most likely do.",
        "This tool sends nothing. The draft is not sent until the officer sends it.",
    ]
    if already:
        notes.append("Already frozen by the issuer, so left out: " + "; ".join(
            f"{a['address']} ({a['frozen']})" for a in already) + ".")
    return {
        "watermark": WATERMARK, "to": ISSUER, "channel": CHANNEL,
        "subject": f"Request to freeze USDT at {len(wallets)} address"
                   f"{'es' if len(wallets) != 1 else ''} - case {ref}",
        "case_id": case["id"], "case_ref": ref, "chain": case["chain"],
        "traced_wallet": case["address"], "evidence_fingerprint": fp,
        "paragraphs": paragraphs, "wallets": wallets,
        "legal_provision": None, "officer": None,
        "policy": POLICY, "review_notes": notes,
    }


def issuer_pdf(draft: dict) -> bytes:
    """The draft as an A4 PDF: a banner and a watermark on every page, blanks for the
    officer and the legal provision, the reviewer's notes on a sheet of their own."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    from .pdf import (BOLD, BODY, CELL, HEAD, INK, MONO, NOTE, RULE, SECTION, SMALL, _t,
                      _when, _unescaped, colors, ParagraphStyle)
    from .pdf import DRAFT as RED
    footer = f"Draft request to the issuer of USDT | case {draft['case_ref']} | " \
             "generated by VASP-FUSION from public blockchain records"

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 38)
        canvas.setFillColor(colors.Color(0.64, 0.27, 0.23, alpha=0.13))
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(52)
        canvas.drawCentredString(0, 0, draft["watermark"].upper())
        canvas.rotate(-52)
        canvas.translate(-A4[0] / 2, -A4[1] / 2)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(RED)
        canvas.drawString(18 * mm, A4[1] - 11 * mm, f"{draft['watermark'].upper()}. NOT SENT.")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#4A5B69"))
        canvas.drawString(18 * mm, 10 * mm, _unescaped(footer))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    story = [Paragraph("To", SMALL), Paragraph(_t(draft["to"]), BOLD),
             Paragraph(f"Channel: {_t(draft['channel'])}", SMALL), Spacer(1, 6),
             Paragraph(f"Subject: {_t(draft['subject'])}", BOLD)]
    for i, p in enumerate(draft["paragraphs"], 1):
        story.append(Paragraph(f"{i}. {_t(p)}", BODY))
    story.append(Paragraph("ADDRESSES", SECTION))
    rows = [[Paragraph(h, HEAD) for h in ("#", "ADDRESS", "USDT RECEIVED", "LEFT THERE",
                                           "FIRST ARRIVED")]]
    for i, w in enumerate(draft["wallets"], 1):
        cell = [Paragraph(_t(w["address"]), MONO),
                Paragraph(f"{_t(fmt.chain_name(w['chain']))} &middot; "
                          f"{'held funds' if w['role'] == 'held' else 'passed funds on'}"
                          f" &middot; {w['hop']} hop{'s' if w['hop'] != 1 else ''} from the "
                          "traced wallet", SMALL)]
        if w.get("label"):
            cell.append(Paragraph(f"label: {_t(w['label'])}", SMALL))
        if w.get("busy"):
            cell.append(Paragraph("a wallet with a great many counterparties: probably a "
                                  "service; check before asking", SMALL))
        rows.append([Paragraph(str(i), CELL), cell,
                     Paragraph(_t(fmt.amount(w["received"], w["asset"])), CELL),
                     Paragraph(_t(fmt.amount(w["held"], w["asset"])), CELL),
                     Paragraph(_when(w["first_seen"]), CELL)])
    table = Table(rows, repeatRows=1, colWidths=[6 * mm, 84 * mm, 28 * mm, 28 * mm, 28 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(table)
    story.append(Paragraph("TRANSACTIONS", SECTION))
    for i, w in enumerate(draft["wallets"], 1):
        story.append(Paragraph(f"Address {i}:", SMALL))
        story += [Paragraph(_t(h), MONO) for h in w["tx_hashes"]]
    story.append(Paragraph("LEGAL PROVISION", SECTION))
    story.append(Paragraph(f"{BLANK}{BLANK} (entered by the officer)", BODY))
    story.append(KeepTogether([Spacer(1, 22), Paragraph(f"{BLANK} (name, rank, office)", BODY),
                               Paragraph("Investigating officer (unsigned draft)", SMALL)]))
    story.append(PageBreak())
    story.append(Paragraph("FOR THE REVIEWING OFFICER. NOT PART OF THE REQUEST.",
                           ParagraphStyle("rn", parent=SECTION, textColor=RED)))
    story += [Paragraph(f"- {_t(n)}", NOTE) for n in draft["review_notes"]]
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, invariant=1,
                            pageCompression=0, title=f"Draft request to the issuer of USDT "
                                                     f"- case {draft['case_ref']}",
                            author="VASP-FUSION", subject=_unescaped(_t(draft["subject"])))
    doc.build(story, onFirstPage=page, onLaterPages=page)
    return out.getvalue()
