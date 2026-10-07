"""The case file: everything a finished case found, laid out as a document that has to
survive being forwarded to someone who has never seen this tool.

`case_file(case)` returns the document as plain blocks (headings, paragraphs,
tables, lists). `case_pdf.py` draws them on A4; `case_file_text` writes the same
blocks as text (the golden files in tests/golden/ are that text). The blocks are
built from the stored case alone, so the same case always gives the same file.

Addresses and transaction hashes are written in full wherever the file states them
itself: the tables, the routes, the address each exchange was reached at. Sentences
produced by the trace (the narrative, the evidence) shorten addresses for the screen,
and they are printed as they are. A short form is NOT written out again: a look-alike
address (same first and last characters, which is what address poisoning produces)
would be indistinguishable from the wallet it imitates, and the file would print the
wrong one. The file says so, and the wallet table resolves every wallet of the case.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .. import fx
from .. import provenance as P
from ..attribute.rules import TIER_WEIGHT, RuleConfig
from ..trace import TraceConfig
from . import fmt
from .case_narrative import CHAIN_NAMES
from .flow import ROLE_WORDS, layout, wallet_id, wallet_index

ROOT = Path(__file__).resolve().parents[2]
ABSTAIN_DIR = ROOT / "artifacts" / "abstain_v1"

OUTCOME_WORDS = {
    "ATTRIBUTED": "Exchange named",
    "INSUFFICIENT_EVIDENCE": "Insufficient evidence: no exchange is named",
    "SANCTIONED_OR_MIXER_REACHED": "Sanctioned or mixing address reached",
}
FUNDS_WORDS = {
    "vasp": "Reached an exchange or custodian", "sanctioned": "Reached a sanctioned address",
    "mixer": "Reached a mixer", "bridge": "Went into a bridge (left this chain)",
    "other_label": "Reached another labelled party",
    "hub": "Stopped at a high-activity wallet (not followed)",
    "beyond_hop_limit": "Moved on past the hop limit", "not_moved": "Has not moved on",
    "not_followed": "Not followed (too small, or the listing could not be read to the end)",
    "returned": "Came back to the traced wallet",
    "fee": "Paid to miners as network fees along the trail",
    "bridge_fee": "Kept by a bridge as the cost of crossing",
}
FLAG_WORDS = {
    "peel_chain": "Peel chain", "fan_out": "Fan-out", "fan_in": "Fan-in",
    "rapid_forwarding": "Rapid forwarding", "round_amounts": "Round amounts",
    "bridge_hop": "Bridge", "mixer_contact": "Mixer contact",
    "sanctioned_contact": "Sanctioned contact", "deposit_like": "Lead",
    "coinjoin_shape": "CoinJoin-shaped transaction",
}
EVIDENCE_WORDS = {"label": "Label", "path": "Route", "sweep": "Sweep", "gas_payer": "Gas payer",
                  "model": "Model", "counterfactual": "Without its label"}
DEMO_NOTICE = ("Demonstration case. This is a real public wallet, chosen because its "
               "on-chain history shows a pattern the tool should handle. Nothing here "
               "alleges wrongdoing by whoever controls it, and the case reference is not a "
               "real complaint.")

SHORT_NOTE = ("In the sentences of this file a long address is written as its first six and "
              "last six characters. Every wallet of this case is listed in full under 'Flow "
              "of funds'. A short address that matches none of them is a wallet outside "
              "this case; two addresses can share those twelve characters, so check the "
              "full address before acting on it.")


class NotReady(ValueError):
    """The case has no result to put in a file (queued, running or failed)."""


# ------------------------------------------------------------------ small helpers
def _amount(value, asset) -> str:
    """The amount, with rupees at the reference rate beside it when it is in dollars."""
    if value is None:
        return "-"
    return fmt.amount(Decimal(str(value)), asset) + fx.beside(value, asset)


def when(value) -> str:
    """23 Jul 2024, 08:44:12 UTC"""
    if not value:
        return "-"
    t = value if isinstance(value, datetime) else \
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return f"{t.day} {t:%b %Y, %H:%M:%S} UTC"


def bar_check_for(chain: str, directory: Path | str = ABSTAIN_DIR) -> dict | None:
    """How the naming bar was measured on this chain (`make abstain-eval`), or None."""
    from ..eval.abstain import abstain_info, read_validation
    validation = read_validation(directory, chain)
    if validation:
        return abstain_info(validation)
    return benchmark_row_for(chain)


def benchmark_row_for(chain: str, directory: Path | str | None = None) -> dict | None:
    """The chain's row of the benchmark (`make benchmark`) when it traced any wallet
    there, as {"benchmark": row}; else None."""
    from ..eval.benchmark import read_summary
    summary = read_summary(directory or ABSTAIN_DIR.parent / "benchmark_v1")
    row = next((r for r in (summary or {}).get("chains", [])
                if r["chain"] == chain and r.get("measured") and r.get("wallets")), None)
    return {"benchmark": row, "bar": summary["bar"]} if row else None


def _confidence_words(c: dict) -> str:
    if c.get("confidence_interval"):
        return f"{fmt.prob(c['confidence'])} ({fmt.prob_range(*c['confidence_interval'])})"
    return f"{fmt.prob(c['confidence'])} (rule confidence)"


# ------------------------------------------------------------------ the sections
def _header(case: dict) -> list[dict]:
    chain = CHAIN_NAMES.get(case["chain"], case["chain"].capitalize())
    prov = case["provenance"]
    hops = (prov.get("input") or {}).get("max_hops")
    since = (prov.get("input") or {}).get("since")
    rows = [("Case reference", case.get("case_ref") or "-"),
            ("Complaint number", case.get("complaint_no") or "-"),
            ("Wallet traced", case["address"]),
            ("Chain", chain + ("; followed onto " + ", ".join(
                fmt.chain_name(c) for c in case["chains"][1:])
                if len(case.get("chains") or []) > 1 else "")),
            ("Asset followed", case.get("asset") or "none"),
            ("Traced on", when(case["created_at"])),
            ("Case id", case["id"])]
    if hops is not None:
        rows.append(("Hop limit", str(hops)))
    if since:
        rows.append(("Transfers from", when(since)))
    if case.get("amount_lost_inr") is not None:
        rows.append(("Amount reported lost", f"Rs {fmt.amount(Decimal(str(case['amount_lost_inr'])))}"))
    out = [{"t": "title", "text": "Case file",
            "sub": "Nearest-exchange attribution of a crypto wallet"}]
    if case.get("demo"):
        out.append({"t": "note", "text": DEMO_NOTICE})
    out.append({"t": "kv", "rows": rows})
    return out


def _nearest(case: dict, bar: float) -> list[str]:
    """The lines that name the nearest exchange, or [] when the case names none."""
    name = case.get("top_vasp")
    if not name:
        return []
    outbound = [c for c in case["candidates"] if c["direction"] == "outbound"]
    top = next((c for c in outbound if c["vasp"] == name), None)
    if top is None:                       # named, but its candidate is not in the case
        return [f"Nearest exchange: {name}."]
    lines = [f"Nearest exchange: {top['vasp']}. Confidence {_confidence_words(top)}."]
    if top["hops"] == 0:
        lines.append(f"The traced wallet itself is labelled {top['vasp']} "
                     f"({fmt.tier_words(top['label_tier'])}): it is one of the exchange's "
                     f"own addresses, not a wallet that paid into it.")
    else:
        lines.append(
            f"{fmt.pct(top['share_of_funds'])} of the funds "
            f"({_amount(top.get('amount'), case.get('asset'))}) reached it in "
            f"{fmt.hops(top['hops'])}, at {top['deposit_address']} "
            f"({fmt.tier_words(top['label_tier'])}).")
    others = [c for c in outbound if c is not top and c["confidence"] >= bar]
    if others:
        lines.append("Also named: " + "; ".join(
            f"{c['vasp']}, confidence {_confidence_words(c)}, "
            f"{fmt.pct(c['share_of_funds'])} of the funds in {fmt.hops(c['hops'])}"
            for c in others) + ".")
    return lines


def _result(case: dict, bar: float) -> list[dict]:
    nearest = _nearest(case, bar)
    if case["outcome"] == "SANCTIONED_OR_MIXER_REACHED":
        # the nearest exchange is still named when there is one: both are findings
        alerts = [f["text"] for f in case["typology_flags"] if f["severity"] == "high"]
        lines = ["The funds reached a sanctioned or mixing address.", *alerts[:2],
                 *(nearest or ["No exchange is named."])]
    elif nearest:
        lines = nearest
    else:
        lines = ["No exchange is named."]
        if case.get("abstain_reason"):
            lines.append(case["abstain_reason"])
    return [{"t": "h", "text": "Result"},
            {"t": "result", "outcome": OUTCOME_WORDS[case["outcome"]], "lines": lines}]


def _funds(case: dict) -> list[dict]:
    asset = case.get("asset")
    rows = [[fmt.pct(s["share"]), _amount(s["amount"], asset),
             FUNDS_WORDS[s["kind"]] + (f": {s['name']}" if s.get("name") else "")]
            for s in case["where_funds_went"]]
    if not rows:
        return []
    rows.append(["100%", _amount(case.get("total_sent"), asset), "Sent by the traced wallet"])
    return [{"t": "h", "text": "Where the funds went"},
            {"t": "table", "head": ["Share", "Amount", "Where"], "rows": rows,
             "widths": [14, 32, 54], "total": True}]


def _flow(case: dict, index: list[dict]) -> list[dict]:
    if not case["graph"]["nodes"]:
        return []
    lay = layout(case, index)
    asset = case.get("asset")
    caption = (f"{lay['wallets']} wallets, {lay['transfers']} transfers. Each box is one wallet "
               f"(its number is in the table below) with the traced funds that reached it.")
    if lay["omitted"]:
        caption += (" 1 smaller wallet is not drawn; it is in the table." if lay["omitted"] == 1
                    else f" {lay['omitted']} smaller wallets are not drawn; they are in the "
                         f"table.")
    rows = [[f"W{r['n']}", r["plain"],
             ROLE_WORDS[r["role"]] + (f": {r['entity']}" if r["entity"] else "")
             + (f", on {fmt.chain_name(r['chain'])}" if r["chain"] != case["chain"] else ""),
             "funded it" if r["col"] < 0 else "-" if r["col"] == 0 else str(r["col"]),
             _amount(r["amount"], r["asset"] or asset)] for r in index]
    # what the trace read against what is drawn, in the same words as on the screen
    seen = (case.get("trace_summary") or {}).get("text")
    return [{"t": "h", "text": "Flow of funds"},
            *([{"t": "p", "text": seen}] if seen else []),
            {"t": "flow", "layout": lay, "caption": caption},
            {"t": "table", "head": ["No.", "Address", "What it is", "Hop", "Traced funds"],
             "rows": rows, "widths": [7, 45, 25, 8, 15], "mono": [1]}]


def _candidates(case: dict, bar: float, number: dict[str, int]) -> list[dict]:
    asset = case.get("asset")
    cands = case["candidates"]
    if not cands:
        return [{"t": "h", "text": "Exchanges reached"},
                {"t": "p", "text": "The traced funds reached no labelled exchange or custodian."}]
    rows = []
    for c in cands:
        if c["direction"] == "inbound":
            standing = "funded the wallet"
        elif c["hops"] == 0:
            standing = "the traced wallet itself"
        else:
            standing = "named" if c["confidence"] >= bar else f"under {bar:.2f}: not named"
        rows.append([str(c["proximity_rank"]), c["vasp"], standing, _confidence_words(c),
                     str(c["hops"]), fmt.pct(c["share_of_funds"]),
                     _amount(c.get("amount"), asset), fmt.tier_words(c["label_tier"])])
    out = [{"t": "h", "text": "Exchanges reached"},
           {"t": "p", "text": "Proximity rank and confidence are two separate numbers. Rank "
            "orders the exchanges by hops, then share of the funds, then time. Confidence is "
            "how far the evidence supports that the address the funds reached belongs to "
            "that exchange."},
           {"t": "table", "head": ["Rank", "Exchange", "Standing", "Confidence", "Hops",
                                   "Share", "Amount", "Label tier"],
            "rows": rows, "widths": [6, 14, 16, 20, 6, 8, 15, 15]}]
    for c in cands:
        direction = "funded the traced wallet" if c["direction"] == "inbound" else \
            f"rank {c['proximity_rank']}"
        out.append({"t": "h2", "text": f"{c['vasp']} ({direction})"})
        out.append({"t": "kv", "rows": [
            ("Address reached", c["deposit_address"]
             + (f" on {fmt.chain_name(c['chain'])}" if c.get("chain") not in (None, case["chain"])
                else "")),
            ("Route", "  ->  ".join(
                f"W{number[w]}" if w in number else a for a, w in zip(c["path"], (
                    wallet_id(case, a, ch) for a, ch in zip(
                        c["path"], c.get("path_chains") or [None] * len(c["path"])))))),
            ("Time to reach", fmt.duration(c["time_to_reach_s"])
             if c.get("time_to_reach_s") is not None else "-")]})
        for ev in c["evidence"]:
            weight = ""
            if ev.get("weight") is not None:
                weight = (f" [SHAP {ev['weight']:+.2f}]" if ev["kind"] == "model"
                          else f" [weight {ev['weight']:.2f}]")
            out.append({"t": "evidence", "kind": EVIDENCE_WORDS[ev["kind"]],
                        "text": ev["text"] + weight,
                        "hashes": ev["tx_hashes"]})
    return out


def _rail(case: dict, number: dict[str, int]) -> list[dict]:
    if not case["hop_rail"]:
        return []
    asset = case.get("asset")
    rows = []
    for h in case["hop_rail"]:
        rows.append([str(h["index"]),
                     "W{} -> W{}".format(
                         number.get(wallet_id(case, h["from_address"], h.get("from_chain")), "?"),
                         number.get(wallet_id(case, h["to_address"], h.get("to_chain")), "?"))
                     + (f" (over the {h['bridge']['bridge']} bridge, "
                        f"{fmt.chain_name(h['from_chain'])} to {fmt.chain_name(h['to_chain'])})"
                        if h.get("bridge") else ""),
                     _amount(h.get("traced_amount") if h.get("traced_amount") is not None
                             else h["amount"], h["asset"] or asset),
                     when(h["block_time"]),
                     "-" if h.get("elapsed_s") is None else fmt.duration(h["elapsed_s"]),
                     h["tx_hash"]])
    title = "Path to the named exchange" if case["top_vasp"] else "Main path of the funds"
    return [{"t": "h", "text": title},
            {"t": "table", "head": ["Hop", "From -> to", "Traced funds", "Time",
                                    "After", "Transaction"],
             "rows": rows, "widths": [5, 12, 15, 18, 9, 41], "mono": [5]}]


def _flags(case: dict) -> list[dict]:
    flags = [f for f in case["typology_flags"] if f["code"] != "deposit_like"]
    leads = [f for f in case["typology_flags"] if f["code"] == "deposit_like"]
    out: list[dict] = []
    if flags:
        out.append({"t": "h", "text": "Patterns seen"})
        out.append({"t": "p", "text": "Patterns in the traced funds. They describe how the "
                    "money moved and never decide the result."})
        for f in flags:
            out.append({"t": "evidence", "kind": f"{FLAG_WORDS[f['code']]} ({f['severity']})",
                        "text": f"{f['wallet']}: {f['text']}", "hashes": f["tx_hashes"]})
    if leads:
        out.append({"t": "h", "text": "Leads to check"})
        out.append({"t": "p", "text": "Unlabelled wallets that behave like an exchange deposit "
                    "address. A lead is not a finding and does not change the result."})
        for f in leads:
            out.append({"t": "evidence", "kind": "Lead",
                        "text": f"{f['wallet']}: {f['text']}", "hashes": f["tx_hashes"]})
    return out


def _confidence(case: dict, rules: RuleConfig, bar_check: dict | None) -> list[dict]:
    w = TIER_WEIGHT
    paras = [
        "Confidence = share factor x the average, over the traced funds, of (label weight x "
        f"{rules.hop_decay:.2f} for each hop after the first).",
        f"Label weight: {w['published_por']:.2f} for an address the exchange published "
        f"itself, {w['curated']:.2f} for a curated list, {w['explorer_tag']:.2f} for an "
        "explorer tag. A deposit address derived by VASP-FUSION weighs its own confidence: "
        "the weight of the exchange wallet it sweeps into x the deposit-address model's "
        "probability, where the model confirmed it.",
        f"Share factor: 1 when {fmt.pct(rules.share_full)} or more of the funds reached the "
        "exchange, and smaller in proportion below that.",
        f"An exchange is named only at {rules.attribute_min:.2f} or more. Below that the "
        "result is 'insufficient evidence', with what would change it.",
        "What is calibrated: only the deposit-address model's probability (the range shown "
        "beside a confidence is its Venn-Abers range carried through the formula). The label "
        "weights, the hop decay, the share factor and the bar are set by rule. A confidence "
        "marked 'rule confidence' has no calibrated part. Confidence is not the probability "
        "that the named exchange is right.",
    ]
    if case["chain"] == "bitcoin":
        from ..cluster import CO_SPEND
        paras.insert(2, (
            "On Bitcoin an address with no label of its own takes the label of its wallet "
            "cluster when it was spent together with a labelled address of one exchange (the "
            "inputs of one transaction are signed by one owner). Its weight is the weight of "
            f"that labelled address x {CO_SPEND:.2f} for having been spent together; the "
            f"{CO_SPEND:.2f} is set by rule, not measured."))
    if bar_check and bar_check.get("benchmark"):
        row = bar_check["benchmark"]
        chain = CHAIN_NAMES.get(row["chain"], row["chain"])
        said = (f"The {bar_check['bar']:.2f} bar was checked on {row['wallets']} real {chain} "
                "wallets that paid a labelled exchange address, traced with the labels one hop "
                "away hidden: ")
        if row["named"]:
            said += (f"an exchange was named for {row['named']} wallets and the name was "
                     f"wrong for {row['wrong']} ({row['error'] * 100:.1f}%; upper bound "
                     f"{row['error_upper_95'] * 100:.1f}%); {row['not_named']} got "
                     "\"insufficient evidence\".")
        else:
            said += (f"no exchange was named for any of them, so no error rate could be "
                     "measured on this chain.")
        paras.append(said + " That is a check on a label hold-out, not a calibration.")
    elif bar_check:
        used = next((b for b in bar_check["bars"]
                     if abs(b["threshold"] - bar_check["current_threshold"]) < 1e-9), None)
        if used:
            chain = CHAIN_NAMES.get(bar_check["chain"], bar_check["chain"])
            paras.append(
                f"The bar was checked on {bar_check['wallets']} real {chain} wallets, traced "
                f"with the derived labels hidden: at {used['threshold']:.2f} an exchange was "
                f"named for {used['wallets_named']} wallets and the name was wrong for "
                f"{used['wallets_wrong']} ({used['risk'] * 100:.1f}%; upper bound "
                f"{used['risk_upper_bound'] * 100:.1f}%). That is a check on a label hold-out, "
                "not a calibration.")
    else:
        paras.append("The bar has not been measured on this chain.")
    return [{"t": "h", "text": "How the confidence was worked out"},
            *({"t": "p", "text": p} for p in paras)]


CROSSING_WORDS = {"followed": "Followed", "not_traced": "Matched, not followed",
                  "unresolved": "Not matched"}


def _bridges(case: dict) -> list[dict]:
    """Every bridge deposit the traced money made: what went in, where it came out, and
    who says the two transactions belong together."""
    legs = case.get("crossings") or []
    if not legs:
        return []
    out = [{"t": "h", "text": "Bridges"},
           {"t": "p", "text": "A bridge takes money in on one chain and pays it out on "
            "another, in two transactions that do not refer to each other. The match below "
            "is the bridge's own public index, asked by the deposit transaction. The amount "
            "paid out is read from the payout transaction on the destination chain, not "
            "from the bridge; the difference is what the crossing cost."}]
    for x in legs:
        rows = [("Bridge", f"{x['bridge']} ({x['bridge_address']}, "
                           f"{fmt.chain_name(x['source_chain'])})"),
                ("Result", CROSSING_WORDS[x["status"]]
                 + (f": {x['reason']}" if x.get("reason") else "")),
                ("Went in", f"{_amount(x['traced_in'], x['asset_in'])}"
                 + ("" if abs(x["traced_in"] - x["amount_in"]) < 1e-9 else
                    f" of a deposit of {_amount(x['amount_in'], x['asset_in'])}")
                 + (f", {when(x['deposited_at'])}" if x.get("deposited_at") else "")),
                ("Deposit transaction", x["source_tx"])]
        if x.get("recipient"):
            rows += [("Came out on", x["dest_name"]),
                     ("Recipient", x["recipient"]),
                     ("Payout transaction", x["payout_tx"])]
        if x.get("amount_out") is not None:
            rows.append(("Paid out", _amount(x["amount_out"], x["asset_out"])
                         + (f", {fmt.duration(x['seconds'])} after the deposit"
                            if x.get("seconds") is not None else "")))
        if x.get("fee") is not None:
            rows.append(("Cost of crossing", _amount(x["fee"], x["asset_in"])))
        if x.get("matched_by"):
            rows.append(("Matched by", x["matched_by"]))
        out.append({"t": "kv", "rows": rows})
    return out


def _lists(case: dict) -> list[dict]:
    out = []
    for title, key in (("What would change this", "what_would_change"),
                       ("Next steps", "next_steps")):
        if case.get(key):
            out += [{"t": "h", "text": title},
                    {"t": "list", "items": list(case[key])}]
    return out


def limitations(case: dict, trace: TraceConfig = TraceConfig()) -> list[str]:
    asset = case.get("asset") or "one asset"
    hops = (case["provenance"].get("input") or {}).get("max_hops") or trace.max_hops
    wallets = (case["provenance"].get("input") or {}).get("max_wallets") or trace.max_nodes
    budget = case["provenance"].get("budget") or {}
    # said only when the budget, not the evidence, is what ended the trace
    ended = [budget["text"]] if budget.get("ended_by") else []
    bitcoin = case["chain"] == "bitcoin"
    utxo = [
        "A Bitcoin transaction has many inputs and many outputs and does not record which "
        "input paid which output. An address's coins are followed through a transaction "
        "only where that has one answer: the address is the transaction's only funding "
        "address, or everything goes to one destination. Where several addresses fund a "
        "transaction that pays several destinations, the coins are counted as not followed "
        "at that point. The traced wallet's own transactions are the exception: the "
        "addresses it is spent with are taken to be its own, and each destination gets its "
        "share in proportion to what the address put in. Change is not guessed: an output "
        "to another address is followed like a payment. Miner fees are counted under 'Where "
        "the funds went'.",
        "Addresses spent together in one transaction are treated as one owner. That is not "
        "true of a CoinJoin or another joint payment: a transaction with that shape is not "
        "used for a wallet cluster and is not followed. The shape test is a rule; it can "
        "miss a joint transaction or take an ordinary payment for one.",
    ] if bitcoin else []
    matching = (
        "Money that entered an address is matched to that address's next outgoing "
        "transactions in time order. Bitcoin does record which coin each transaction "
        "spent; this tool does not read that yet, so where an address held other coins too "
        "the matching is a convention."
        if bitcoin else
        "Money that entered a wallet is matched to that wallet's next outgoing transfers in "
        "time order. Where a wallet held other money too, that matching is a convention, "
        "not a fact recorded on the chain.")
    return [
        "This file reads public blockchain records and address labels. It does not identify "
        "a person. Only the exchange's own customer records (KYC) can say who holds the "
        "account an address belongs to.",
        "A label can be wrong or out of date. Each label's tier is stated. A label 'derived "
        "by VASP-FUSION' was inferred from on-chain behaviour; it is not a statement by the "
        "exchange.",
        f"Only {asset} was followed. Anything the wallet moved in other assets is not in "
        "this file.",
        f"The trace stops at any labelled address, at a wallet with {trace.hub_degree} or more "
        f"counterparties (too busy to follow one person's money through), after {hops} "
        f"hops, at shares under {fmt.pct(trace.min_share)}, and after {wallets} "
        "wallets. Funds beyond those points are counted under 'Where the funds went' and "
        "not followed.",
        *ended,
        matching,
        *utxo,
        "Flags and leads describe patterns. They never decide the result.",
        "All times are UTC. Amounts are in the asset followed; no exchange rate is applied.",
        "The result is as of the chain responses listed in the receipt. Transfers made "
        "after they were fetched are not in this file.",
    ]


def _receipt(case: dict) -> list[dict]:
    r = P.receipt(case)
    if r is None:
        return [{"t": "h", "text": "Provenance receipt"},
                {"t": "p", "text": "This case carries no receipt: it was stored before "
                 "receipts existed. Trace it again to get one."}]
    commit = r["git_commit"] or "not recorded"
    if r["git_dirty"]:
        commit += " (with uncommitted changes)"
    rows = [("Findings fingerprint", r["findings_sha256"]),
            ("Input", f"{r['input']['chain']} {r['input']['address']}, hop limit "
                      f"{r['input']['max_hops']}"
                      + (f", from {when(r['input']['since'])}" if r["input"].get("since") else "")
                      + (f", budget {r['input']['max_wallets']} wallets"
                         if r["input"].get("max_wallets") else "")
                      + (f", time budget {r['input']['max_seconds']:g} s"
                         if r["input"].get("max_seconds") else "")),
            ("Input SHA-256", r["input_sha256"]),
            ("Chain responses", f"{r['pages']} read from " + ", ".join(
                s for s in r["data_sources"] if s != "label store")),
            ("Responses SHA-256", r["responses_sha256"]),
            ("Label database SHA-256", r["label_db_sha256"] or "not recorded"),
            ("Model", f"{r['model_version']}, SHA-256 {r['model_sha256']}"
             if r["model_version"] else "not used in this case"),
            ("Code", f"{r['code_version']}, commit {commit}"),
            ("Seed", str(r["seed"])),
            ("Fetched", when(r["fetched_at"]) if r["fetched_at"]
             else "replayed from the cache (no network)"),
            ("Content SHA-256", r.get("content_sha256") or "not recorded"),
            ("Receipt SHA-256", r["receipt_sha256"])]
    return [{"t": "h", "text": "Provenance receipt"},
            {"t": "p", "text": "What this case was computed from. The fingerprint covers "
             "every figure, address, time and transaction hash of the result and none of "
             "its wording; the content digest covers the wording too. Neither covers the "
             "case reference, complaint number or amount reported lost: those are the "
             "officer's entries. To check it, trace the wallet again from the same "
             f"responses: python -m vaspfusion.cli verify {case['id']}"},
            {"t": "kv", "rows": rows},
            {"t": "h2", "text": "Chain responses read"},
            {"t": "pages", "rows": [(p["sha256"], p["query"]) for p in r["responses"]]}]


def _risk(case: dict) -> list[dict]:
    """The risk indicators (risk.py). Worked out from this case's own flags, labels and
    slices when the file is made; the score says what it is in the same paragraph."""
    from ..risk import CLASSES, case_risk
    risk = case_risk(case)
    if risk is None:
        return []
    out: list[dict] = [
        {"t": "h", "text": "Risk indicators"},
        {"t": "p", "text": f"Risk class: {risk['risk_class'].capitalize()} "
                           f"(score {risk['score']} of 100). {risk['basis']} The indicator "
                           f"list follows {risk['source']}; the points are this tool's."}]
    if not risk["indicators"]:
        out.append({"t": "p", "text": "No indicator is present in the traced funds."})
    for i in risk["indicators"]:
        out.append({"t": "evidence", "kind": f"{i['name']} (+{i['points']})",
                    "text": i["text"], "hashes": i["tx_hashes"]})
    counts = {c: sum(1 for f in risk["flows"] if f["risk_class"] == c) for c in CLASSES}
    above = [f"{counts[c]} {c.capitalize()}" for c in reversed(CLASSES) if counts[c]]
    total = len(case["graph"]["edges"])
    flows = (f"Of the {total} transfers read, {', '.join(above)}; the rest are Low."
             if above else f"All {total} transfers read are Low.")
    if risk["path_class"]:
        flows += f" The path shown above is {risk['path_class'].capitalize()}."
    out.append({"t": "p", "text": "Transaction flows: " + flows})
    return out


# ------------------------------------------------------------------ the document
def case_file(case: dict, *, rules: RuleConfig = RuleConfig(),
              bar_check: dict | None = None) -> list[dict]:
    if case.get("status") != "done" or case.get("outcome") is None:
        raise NotReady(f"Case {case.get('id')} has no result yet (status "
                       f"{case.get('status')}).")
    index = wallet_index(case)
    number = {r["address"]: r["n"] for r in index}
    blocks = _header(case)
    blocks += _result(case, rules.attribute_min)
    blocks += [{"t": "h", "text": "Summary"}, {"t": "p", "text": case["narrative"]},
               {"t": "small", "text": SHORT_NOTE}]
    blocks += _funds(case)
    blocks += _flow(case, index)
    blocks += _candidates(case, rules.attribute_min, number)
    blocks += _rail(case, number)
    blocks += _bridges(case)
    blocks += _flags(case)
    blocks += _risk(case)
    blocks += _confidence(case, rules, bar_check)
    blocks += _lists(case)
    blocks += [{"t": "h", "text": "Limitations"}, {"t": "list", "items": limitations(case)}]
    blocks += _receipt(case)
    return blocks


def reference(case: dict) -> str:
    return case.get("case_ref") or case["id"]


# ------------------------------------------------------------------ as text
def _wrap(text: str, width: int = 96, indent: str = "") -> list[str]:
    import textwrap
    return textwrap.wrap(text, width=width, initial_indent=indent,
                         subsequent_indent=" " * len(indent),
                         break_long_words=False, break_on_hyphens=False) or [indent.rstrip()]


def _end(wallet: str) -> str:
    """An arrow's end in words: `chain:address` (another chain's wallet) says its chain."""
    chain, sep, address = wallet.partition(":")
    return f"{address} ({fmt.chain_name(chain)})" if sep else wallet


def blocks_text(blocks: list[dict]) -> str:
    out: list[str] = []
    for b in blocks:
        t = b["t"]
        if t == "title":
            out += [b["text"].upper(), b["sub"], ""]
        elif t == "h":
            out += ["", b["text"].upper(), "-" * len(b["text"])]
        elif t == "h2":
            out += ["", f"  {b['text']}"]
        elif t in ("p", "note", "small"):
            out += _wrap(b["text"]) + [""]
        elif t == "result":
            out += [b["outcome"].upper()] + [ln for line in b["lines"] for ln in _wrap(line)] + [""]
        elif t == "kv":
            pad = max(len(k) for k, _ in b["rows"]) + 2
            out += [f"  {k:<{pad}}{v}" for k, v in b["rows"]]
        elif t == "table":
            out.append("  " + " | ".join(b["head"]))
            out += ["  " + " | ".join(row) for row in b["rows"]]
        elif t == "list":
            for item in b["items"]:
                out += _wrap(item, indent="  - ")
        elif t == "evidence":
            out += _wrap(f"[{b['kind']}] {b['text']}", indent="    ")
            out += [f"        tx {h}" for h in b["hashes"]]
        elif t == "flow":
            lay = b["layout"]
            out.append("  " + b["caption"])
            for box in lay["boxes"]:
                out.append(f"    W{box['n']}  column {lay['columns'][box['col']]}, "
                           f"row {box['row'] + 1}: {box['title']}")
            for a in lay["arrows"]:
                out.append(f"    arrow {_end(a['source'])} -> {_end(a['target'])} "
                           f"({a['direction']}, "
                           f"{a['transfers']} transfer{'s' if a['transfers'] != 1 else ''}, "
                           f"{_amount(a['amount'], a.get('asset') or lay['asset'])})")
        elif t == "pages":
            out += [f"    {sha}  {query}" for sha, query in b["rows"]]
        else:
            raise ValueError(f"unknown block {t}")
    return "\n".join(line.rstrip() for line in out).strip() + "\n"


def case_file_text(case: dict, **kw) -> str:
    kw.setdefault("bar_check", bar_check_for(case["chain"]))
    return blocks_text(case_file(case, **kw))
