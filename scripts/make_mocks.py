"""Generate mocks/*.json - the fixtures the UI track builds against until the
backend phases land. `make mocks` (needs `make labels` first).

What is real and what is demo, precisely:
  * REAL: every *labelled* address (OKX, HTX, CoinDCX, ChangeNOW, OFAC rows) and
    its entity/tier/source, read from data/labels.duckdb; label-search results and
    label coverage counts.
  * DEMO: suspect and intermediate wallets, deposit addresses, tx hashes, amounts,
    times and confidences. The addresses are valid in format (Tron base58check,
    EVM hex) but derived from sha256("vaspfusion-demo:<n>"), so they are
    unlabelled and belong to nobody we know of. Every file carries `"_demo": true`.
  * NOT INVENTED: model metrics. model.json is the measured Tron model from
    artifacts/model_v1/tron/metrics.json (real numbers), or `not_measured` without it.

Seeded (SEED) and deterministic: rerunning produces byte-identical files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vaspfusion.api.main import MOCKS, mock_model_for  # noqa: E402
from vaspfusion.labels.lookup import DEFAULT_DB, LabelStore  # noqa: E402

SEED = 26182
NOTICE = ("DEMO FIXTURE. Labelled addresses are real (research/data label sets); "
          "suspect/hop addresses, tx hashes, amounts and confidences are synthetic "
          "placeholders for UI development. Not evidence.")
T0 = datetime(2026, 9, 14, 10, 2, 11, tzinfo=timezone.utc)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _h(tag: str) -> bytes:
    return hashlib.sha256(f"vaspfusion-demo:{SEED}:{tag}".encode()).digest()


def _b58(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def tron_addr(tag: str) -> str:
    payload = b"\x41" + _h(tag)[:20]
    check = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _b58(payload + check)


def evm_addr(tag: str) -> str:
    return "0x" + _h(tag)[:20].hex()


def tron_tx(tag: str) -> str:
    return _h("tx:" + tag).hex()


def evm_tx(tag: str) -> str:
    return "0x" + _h("tx:" + tag).hex()


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ real labels
def real_labels(store: LabelStore) -> dict:
    def first(sql_where: str, params: list) -> dict:
        row = store.con.execute(
            "SELECT address, chain FROM labels WHERE " + sql_where +
            " ORDER BY address LIMIT 1", params).fetchone()
        if row is None:
            raise SystemExit(f"no label row for {sql_where} {params} - run `make labels`")
        return store.lookup(*row).as_dict()
    return {
        "okx": first("chain = 'tron' AND entity = 'OKX'", []),
        "htx": first("chain = 'tron' AND entity = 'HTX'", []),
        "coindcx": first("chain = 'tron' AND entity = 'CoinDCX'", []),
        "ofac": first("chain = 'tron' AND category = 'sanctioned'", []),
        "changenow": first("chain = 'ethereum' AND label = 'ChangeNOW: Hot Wallet 1'", []),
    }


# ------------------------------------------------------------------ cases
def node(addr, chain, role, hop, label=None, cluster=None):
    return {"id": addr, "chain": chain, "role": role, "hop": hop, "label": label,
            "cluster": cluster, "is_hub": False}


def edge(i, src, dst, tx, asset, amount, usd, minutes):
    return {"id": f"e{i}", "source": src, "target": dst, "tx_hash": tx, "asset": asset,
            "amount": amount, "amount_usd": usd, "block_time": at(minutes),
            "direction": "outbound"}


def hop(i, src, dst, tx, asset, amount, usd, minutes, prev):
    return {"index": i, "from_address": src, "to_address": dst, "tx_hash": tx,
            "asset": asset, "amount": amount, "amount_usd": usd, "block_time": at(minutes),
            "elapsed_s": None if prev is None else int((minutes - prev) * 60)}


def provenance(sources):
    return {"seed": SEED, "code_version": "b1-mock", "label_db_sha256": None,
            "fetched_at": None, "offline_replay": True, "data_sources": sources}


def case_attributed(L) -> dict:
    """Tron USDT: suspect -> 2 hops -> OKX deposit that sweeps into an OKX
    published proof-of-reserves wallet. HTX is a weaker second candidate."""
    s, h1, h2 = tron_addr("c1:suspect"), tron_addr("c1:hop1"), tron_addr("c1:hop2")
    dep, h3, dep2 = tron_addr("c1:okx-deposit"), tron_addr("c1:hop3"), tron_addr("c1:htx-dep")
    okx, htx = L["okx"], L["htx"]
    tx = {k: tron_tx(f"c1:{k}") for k in ("a", "b", "c", "sweep", "d", "e", "gas")}
    derived = {"address": dep, "chain": "tron", "entity": "OKX", "category": "exchange",
               "kind": "deposit", "tier": "derived",
               "source": "DEMO - derived by sweep pattern (computed for real in B4)",
               "source_url": None, "label": "OKX deposit (derived)"}
    nodes = [node(s, "tron", "suspect", 0), node(h1, "tron", "intermediary", 1),
             node(h2, "tron", "intermediary", 2),
             node(dep, "tron", "exchange_deposit", 3, derived, "OKX"),
             node(okx["address"], "tron", "exchange", 4, okx, "OKX"),
             node(h3, "tron", "intermediary", 2),
             node(dep2, "tron", "unknown", 3),
             node(htx["address"], "tron", "exchange", 4, htx, "HTX")]
    edges = [edge(1, s, h1, tx["a"], "USDT", 48_500.0, 48_500.0, 0),
             edge(2, h1, h2, tx["b"], "USDT", 41_200.0, 41_200.0, 7),
             edge(3, h2, dep, tx["c"], "USDT", 41_150.0, 41_150.0, 16),
             edge(4, dep, okx["address"], tx["sweep"], "USDT", 41_150.0, 41_150.0, 94),
             edge(5, h1, h3, tx["d"], "USDT", 7_300.0, 7_300.0, 9),
             edge(6, h3, dep2, tx["e"], "USDT", 7_290.0, 7_290.0, 31),
             edge(7, dep2, htx["address"], tron_tx("c1:htx-sweep"), "USDT", 7_290.0, 7_290.0,
                  210)]
    rail = [hop(1, s, h1, tx["a"], "USDT", 48_500.0, 48_500.0, 0, None),
            hop(2, h1, h2, tx["b"], "USDT", 41_200.0, 41_200.0, 7, 0),
            hop(3, h2, dep, tx["c"], "USDT", 41_150.0, 41_150.0, 16, 7)]
    cands = [
        {"vasp": "OKX", "category": "exchange", "proximity_rank": 1, "confidence": 0.91,
         "confidence_interval": [0.84, 0.95], "hops": 3, "share_of_funds": 0.85,
         "time_to_reach_s": 960, "label_tier": "published_por", "deposit_address": dep,
         "path": [s, h1, h2, dep],
         "evidence": [
             {"kind": "sweep", "tier": "published_por", "tx_hashes": [tx["sweep"]],
              "weight": 0.41,
              "text": f"{dep[:6]}… swept the full balance into an OKX wallet that OKX "
                      "itself lists in its proof of reserves"},
             {"kind": "path", "tier": None, "tx_hashes": [tx["a"], tx["b"], tx["c"]],
              "weight": 0.22, "text": "85% of the suspect's USDT reached it in 3 hops "
                                      "within 16 minutes"},
             {"kind": "gas_payer", "tier": None, "tx_hashes": [tron_tx("c1:gas")],
              "weight": 0.12, "text": "Its TRX for fees came from the same OKX wallet, "
                                      "the usual pattern for exchange deposit addresses"}],
         "counterfactual": "Still OKX (0.78) if the sweep evidence is removed"},
        {"vasp": "HTX", "category": "exchange", "proximity_rank": 2, "confidence": 0.46,
         "confidence_interval": [0.31, 0.61], "hops": 4, "share_of_funds": 0.15,
         "time_to_reach_s": 12_600, "label_tier": "published_por",
         "deposit_address": dep2, "path": [s, h1, h3, dep2],
         "evidence": [{"kind": "path", "tier": "published_por", "tx_hashes": [tx["d"], tx["e"]],
                       "weight": 0.18,
                       "text": "15% of funds reached an address that later paid an HTX "
                               "reserve wallet"}],
         "counterfactual": None}]
    flags = [{"code": "rapid_forwarding", "severity": "warn", "wallet": h1,
              "text": "Forwarded 100% of what it received within 9 minutes",
              "figures": {"minutes": 9, "share": 1.0}, "tx_hashes": [tx["b"], tx["d"]]},
             {"code": "fan_out", "severity": "info", "wallet": h1,
              "text": "Split one inflow into 2 outputs", "figures": {"outputs": 2},
              "tx_hashes": [tx["b"], tx["d"]]}]
    return {
        "id": "demo-tron-okx", "address": s, "chain": "tron", "status": "done",
        "outcome": "ATTRIBUTED", "top_vasp": "OKX", "confidence": 0.91,
        "case_ref": "DEMO/2026/001", "complaint_no": "31509260001234",
        "amount_lost_inr": 4_050_000.0, "created_at": at(-60 * 24), "demo": True,
        "hop_rail": rail, "graph": {"nodes": nodes, "edges": edges},
        "candidates": cands, "typology_flags": flags,
        "narrative": (f"Wallet {s[:6]}… sent 48,500 USDT on Tron. 41,150 USDT (85%) "
                      f"reached {dep[:6]}… in 3 hops within 16 minutes. That address swept "
                      "its balance into an OKX wallet published in OKX's proof of reserves, "
                      "so it is an OKX deposit address. Write to OKX."),
        "abstain_reason": None, "what_would_change": [],
        "next_steps": ["Draft a request to OKX for KYC and a freeze on the deposit account",
                       "Preserve the transaction records (§63 BSA certificate)"],
        "provenance": provenance(["TronGrid (demo replay)", "wallet-attribution labels"]),
    }, derived


def case_abstain(L) -> dict:
    """Ethereum: funds scatter; only 12% touches a labelled VASP (a ChangeNOW hot
    wallet, real label) and confidence stays below the bar, so no VASP is named."""
    s = evm_addr("c2:suspect")
    hs = [evm_addr(f"c2:hop{i}") for i in range(1, 5)]
    cn = L["changenow"]
    tx = {k: evm_tx(f"c2:{k}") for k in ("a", "b", "c", "d", "e", "f")}
    nodes = [node(s, "ethereum", "suspect", 0)] + \
            [node(h, "ethereum", "intermediary", i) for i, h in
             zip((1, 1, 2, 3), hs)] + \
            [node(cn["address"], "ethereum", "swap_service", 4, cn, "ChangeNOW")]
    edges = [edge(1, s, hs[0], tx["a"], "ETH", 6.2, 15_810.0, 0),
             edge(2, s, hs[1], tx["b"], "USDT", 9_900.0, 9_900.0, 3),
             edge(3, hs[0], hs[2], tx["c"], "ETH", 1.3, 3_315.0, 55),
             edge(4, hs[2], hs[3], tx["d"], "ETH", 1.25, 3_187.5, 180),
             edge(5, hs[3], cn["address"], tx["e"], "ETH", 1.22, 3_111.0, 400)]
    rail = [hop(1, s, hs[0], tx["a"], "ETH", 6.2, 15_810.0, 0, None),
            hop(2, hs[0], hs[2], tx["c"], "ETH", 1.3, 3_315.0, 55, 0),
            hop(3, hs[2], hs[3], tx["d"], "ETH", 1.25, 3_187.5, 180, 55),
            hop(4, hs[3], cn["address"], tx["e"], "ETH", 1.22, 3_111.0, 400, 180)]
    cands = [{"vasp": "ChangeNOW", "category": "swap_service", "proximity_rank": 1,
              "confidence": 0.34, "confidence_interval": [0.18, 0.52], "hops": 4,
              "share_of_funds": 0.12, "time_to_reach_s": 24_000,
              "label_tier": "explorer_tag", "deposit_address": cn["address"],
              "path": [s, hs[0], hs[2], hs[3], cn["address"]],
              "evidence": [{"kind": "label", "tier": "explorer_tag",
                            "tx_hashes": [tx["e"]], "weight": 0.09,
                            "text": "Reached a wallet Etherscan tags as a ChangeNOW hot "
                                    "wallet, but only 12% of the funds and after 4 hops"}],
              "counterfactual": None}]
    return {
        "id": "demo-eth-abstain", "address": s, "chain": "ethereum", "status": "done",
        "outcome": "INSUFFICIENT_EVIDENCE", "top_vasp": None, "confidence": None,
        "case_ref": "DEMO/2026/002", "complaint_no": None, "amount_lost_inr": 2_150_000.0,
        "created_at": at(-60 * 5), "demo": True, "hop_rail": rail,
        "graph": {"nodes": nodes, "edges": edges}, "candidates": cands,
        "typology_flags": [{"code": "peel_chain", "severity": "warn", "wallet": hs[0],
                            "text": "Peeled off small amounts over 3 hops, keeping the rest",
                            "figures": {"hops": 3}, "tx_hashes": [tx["c"], tx["d"]]}],
        "narrative": (f"Wallet {s[:6]}… split its funds across several wallets. Only 12% "
                      "reached a known VASP (a ChangeNOW hot wallet, 4 hops away). That is "
                      "not enough to name a VASP, so none is named."),
        "abstain_reason": ("Only 12% of the funds reached a labelled VASP, after 4 hops; "
                           "confidence 0.34 is below the 0.60 needed to name one."),
        "what_would_change": [
            f"Trace the 9,900 USDT still held by {hs[1][:8]}… once it moves",
            "A deposit-address link (sweep or gas payer) from the last hop to a named "
            "exchange wallet"],
        "next_steps": ["Add the suspect and its hops to the watchlist",
                       "Re-trace when new outflows appear"],
        "provenance": provenance(["Etherscan v2 (demo replay)", "wallet-attribution labels"]),
    }


def case_sanctioned(L) -> dict:
    """Tron: 1 hop into an OFAC-listed address (real label)."""
    s, h1 = tron_addr("c3:suspect"), tron_addr("c3:hop1")
    ofac, dcx = L["ofac"], L["coindcx"]
    tx = {k: tron_tx(f"c3:{k}") for k in ("a", "b", "c")}
    nodes = [node(s, "tron", "suspect", 0), node(h1, "tron", "intermediary", 1),
             node(ofac["address"], "tron", "sanctioned", 2, ofac),
             node(dcx["address"], "tron", "exchange", 2, dcx, "CoinDCX")]
    edges = [edge(1, s, h1, tx["a"], "USDT", 12_000.0, 12_000.0, 0),
             edge(2, h1, ofac["address"], tx["b"], "USDT", 11_000.0, 11_000.0, 4),
             edge(3, h1, dcx["address"], tx["c"], "USDT", 990.0, 990.0, 6)]
    rail = [hop(1, s, h1, tx["a"], "USDT", 12_000.0, 12_000.0, 0, None),
            hop(2, h1, ofac["address"], tx["b"], "USDT", 11_000.0, 11_000.0, 4, 0)]
    cands = [{"vasp": "CoinDCX", "category": "exchange", "proximity_rank": 1,
              "confidence": 0.58, "confidence_interval": [0.40, 0.74], "hops": 2,
              "share_of_funds": 0.08, "time_to_reach_s": 360, "label_tier": "curated",
              "deposit_address": dcx["address"], "path": [s, h1, dcx["address"]],
              "evidence": [{"kind": "label", "tier": "curated", "tx_hashes": [tx["c"]],
                            "weight": 0.2,
                            "text": "8% of funds went to a CoinDCX wallet listed in the "
                                    "Dune spellbook"}],
              "counterfactual": None}]
    return {
        "id": "demo-tron-sanctioned", "address": s, "chain": "tron", "status": "done",
        "outcome": "SANCTIONED_OR_MIXER_REACHED", "top_vasp": "CoinDCX", "confidence": 0.58,
        "case_ref": "DEMO/2026/003", "complaint_no": "31509260004321",
        "amount_lost_inr": 1_000_000.0, "created_at": at(-30), "demo": True,
        "hop_rail": rail, "graph": {"nodes": nodes, "edges": edges}, "candidates": cands,
        "typology_flags": [{"code": "sanctioned_contact", "severity": "high",
                            "wallet": ofac["address"],
                            "text": "92% of funds reached an address on the US OFAC SDN list",
                            "figures": {"share": 0.92}, "tx_hashes": [tx["b"]]}],
        "narrative": (f"Wallet {s[:6]}… sent 12,000 USDT; 11,000 USDT reached an OFAC "
                      "sanctioned address 2 hops away. A smaller share (8%) reached CoinDCX."),
        "abstain_reason": None, "what_would_change": [],
        "next_steps": ["Escalate: sanctioned counterparty",
                       "Request KYC from CoinDCX for the 990 USDT deposit"],
        "provenance": provenance(["TronGrid (demo replay)", "OFAC SDN (0xB10C list)"]),
    }


def summary(case: dict) -> dict:
    keys = ("id", "address", "chain", "status", "outcome", "top_vasp", "confidence",
            "case_ref", "complaint_no", "amount_lost_inr", "created_at", "demo")
    return {k: case[k] for k in keys}


# ------------------------------------------------------------------ desk + requests
LEGAL = ("Notice under Section 94 of the Bharatiya Nagarik Suraksha Sanhita, 2023. "
         "Electronic records to be furnished with a certificate under Section 63 of "
         "the Bharatiya Sakshya Adhiniyam, 2023.")


def request_okx(c1: dict) -> dict:
    cand = c1["candidates"][0]
    wallets = [{"address": cand["deposit_address"], "chain": "tron",
                "amount_usd": 41_150.0, "tier": "derived", "first_seen": at(16),
                "tx_hashes": [cand["evidence"][0]["tx_hashes"][0]]}]
    return {
        "id": "demo-req-okx-001", "reference": "DEMO/I4C/REQ/2026/001", "vasp": "OKX",
        "status": "sent", "case_ids": [c1["id"]], "created_at": at(-60 * 20),
        "due": "2026-09-21",
        "status_history": [
            {"status": "drafted", "at": at(-60 * 20), "note": None},
            {"status": "approved", "at": at(-60 * 19), "note": "Approved by SHO"},
            {"status": "sent", "at": at(-60 * 18), "note": "Sent via SAHYOG (demo)"}],
        "letter": {
            "reference": "DEMO/I4C/REQ/2026/001", "date": "2026-09-13",
            "to": "The Nodal Officer, OKX",
            "subject": "Request for KYC, transaction records and freeze of a deposit account "
                       "linked to cyber-fraud complaint DEMO/2026/001",
            "paragraphs": [
                "This office is investigating a cyber-fraud complaint registered on the "
                "National Cybercrime Reporting Portal.",
                "Blockchain analysis shows that proceeds of the fraud were deposited to the "
                "wallet listed below, which our analysis attributes to your platform.",
                "You are requested to furnish the information listed below and to freeze the "
                "account pending investigation."],
            "wallets": wallets, "asks": ["kyc", "transactions", "freeze", "preservation"],
            "legal_basis": LEGAL, "officer": "Investigating Officer (demo)",
            "watermark": None},
        "pdf_url": "/api/requests/demo-req-okx-001/pdf",
        "payload": {"schema": "sahyog-request/0-demo", "vasp": "OKX",
                    "reference": "DEMO/I4C/REQ/2026/001",
                    "wallets": [w["address"] for w in wallets],
                    "asks": ["kyc", "transactions", "freeze", "preservation"]},
    }


def desk(c1, c3, req) -> dict:
    return {
        "follow_ups": [{"kind": "reply_overdue", "vasp": "OKX", "request_id": req["id"],
                        "due": "2026-09-21",
                        "text": "OKX has not replied; the reply was due 21 Sep"}],
        "rows": [
            {"vasp": "OKX", "category": "exchange", "wallet_count": 1, "total_usd": 41_150.0,
             "case_ids": [c1["id"]], "status": "sent", "next_action": "Follow up on reply",
             "last_request_id": req["id"]},
            {"vasp": "CoinDCX", "category": "exchange", "wallet_count": 1,
             "total_usd": 990.0, "case_ids": [c3["id"]], "status": "not_requested",
             "next_action": "Draft request", "last_request_id": None}],
    }


def vasp(store: LabelStore, name: str, wallets: list[dict], requests: list[dict]) -> dict:
    counts = dict(store.con.execute(
        "SELECT chain, count(*) FROM labels WHERE entity = ? GROUP BY 1 ORDER BY 2 DESC, 1",
        [name]).fetchall())
    # Directory facts are left empty on purpose: B8 fills only what it can cite.
    return {"directory": {"name": name, "legal_name": None, "fiu_ind_registered": None,
                          "jurisdiction": None, "le_request_channel": None,
                          "source_urls": []},
            "label_counts": counts, "wallets": wallets, "requests": requests}


MODEL_NOTICE = ("UI fixture. Unlike the other mock files these figures are real: the "
                "deposit-address model's measurements, copied from "
                "artifacts/model_v1/tron/metrics.json when `make mocks` last ran. "
                "/api/model serves the current ones.")


def model_mock() -> dict:
    """The measured Tron model (`make model`), exactly as /api/model serves it. These
    numbers are real; without the metrics file the mock says so instead of inventing any."""
    from vaspfusion.api.main import MODEL_DIR
    from vaspfusion.classify.report import model_info, read_metrics
    metrics = read_metrics(MODEL_DIR, "tron")
    if metrics is None:
        return {"status": "not_measured", "version": None, "trained_at": None,
                "split": None, "metrics": {}, "reliability": [], "risk_coverage": [],
                "feature_importance": [],
                "notes": ["No model has been measured yet: run `make model`."]}
    return model_info(metrics)


def main() -> None:
    if not Path(DEFAULT_DB).exists():
        raise SystemExit("data/labels.duckdb missing - run `make labels` first")
    with LabelStore(DEFAULT_DB) as store:
        L = real_labels(store)
        c1, derived = case_attributed(L)
        c2, c3 = case_abstain(L), case_sanctioned(L)
        cases = [c1, c2, c3]
        req = request_okx(c1)
        req_summary = {k: req[k] for k in ("id", "reference", "vasp", "status", "case_ids",
                                           "created_at", "due")}
        total, found = store.search("coindcx", limit=10)
        st = store.stats()
        files = {
            "cases": {"total": 3, "items": [summary(c) for c in cases]},
            **{f"cases/{c['id']}": c for c in cases},
            f"wallets/tron/{c1['address']}": {
                "address": c1["address"], "chain": "tron", "labels": [],
                "risk": {"score": None, "reasons": [f["text"] for f in c1["typology_flags"]]},
                "cases": [{"case_id": c1["id"], "role": "suspect", "hop": 0}],
                "inbound": {"tx_count": 3, "total_usd": 48_500.0, "first_seen": at(-120),
                            "last_seen": at(-5), "top_counterparties": []},
                "outbound": {"tx_count": 1, "total_usd": 48_500.0, "first_seen": at(0),
                             "last_seen": at(0), "top_counterparties": [c1["hop_rail"][0]
                                                                        ["to_address"]]}},
            f"wallets/tron/{derived['address']}": {
                "address": derived["address"], "chain": "tron", "labels": [derived],
                "risk": {"score": None, "reasons": []},
                "cases": [{"case_id": c1["id"], "role": "exchange_deposit", "hop": 3}]},
            "labels/search": {"query": "coindcx", "total": total, "limit": 10, "offset": 0,
                              "items": [f.as_dict() for f in found]},
            "desk": desk(c1, c3, req),
            "vasps/OKX": vasp(store, "OKX", [
                {"address": derived["address"], "chain": "tron", "case_id": c1["id"],
                 "direction": "outbound", "amount_usd": 41_150.0, "tier": "derived",
                 "confidence": 0.91}], [req_summary]),
            "vasps/CoinDCX": vasp(store, "CoinDCX", [
                {"address": L["coindcx"]["address"], "chain": "tron", "case_id": c3["id"],
                 "direction": "outbound", "amount_usd": 990.0, "tier": "curated",
                 "confidence": 0.58}], []),
            f"requests/{req['id']}": req,
            "dashboard": {
                "counts": {"cases_total": 3, "open_cases": 2, "wallets_attributed": 2,
                           "requests_awaiting_reply": 1},
                "outcomes": {"ATTRIBUTED": 1, "INSUFFICIENT_EVIDENCE": 1,
                             "SANCTIONED_OR_MIXER_REACHED": 1},
                "top_vasps": [{"vasp": "OKX", "cases": 1, "total_usd": 41_150.0},
                              {"vasp": "CoinDCX", "cases": 1, "total_usd": 990.0}],
                "chain_mix": [{"chain": "tron", "cases": 2}, {"chain": "ethereum", "cases": 1}],
                "median_time_to_attribution_s": None,
                "recent_alerts": [{"wallet": c3["typology_flags"][0]["wallet"], "chain": "tron",
                                   "severity": "high", "at": at(-26), "case_id": c3["id"],
                                   "text": "Case DEMO/2026/003 reached an OFAC-sanctioned "
                                           "address"}],
                "label_coverage": {k: st[k] for k in ("total", "by_category", "by_tier",
                                                      "by_chain")}},
            "model": model_mock(),
        }

    shutil.rmtree(MOCKS, ignore_errors=True)
    for rel, body in files.items():
        mock_model_for(rel).model_validate(body)  # fail before writing anything wrong
        path = MOCKS / f"{rel}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        measured = rel == "model" and body["status"] == "measured"
        path.write_text(json.dumps({"_demo": True,
                                    "_notice": MODEL_NOTICE if measured else NOTICE, **body},
                                   indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(files)} mock files to {MOCKS.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
