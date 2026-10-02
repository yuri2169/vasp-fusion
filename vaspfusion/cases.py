"""A case: trace a wallet, attribute it, and shape the result as the API's CaseDetail.

`run_case` is the one function the API, the CLI and the demo runner call, so a
case looks the same whichever way it was started. Its output is validated against
the contract model before it is returned.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit

from . import provenance as P
from .api import schemas as S
from .chains import get_provider
from .attribute.counterfactual import add_counterfactuals
from .attribute.leads import add_leads
from .attribute.rules import Attribution, Candidate, RuleConfig, attribute
from .cluster import cluster_labels
from .explain.case_narrative import narrative, path_hashes
from .labels.lookup import Label
from .labels.normalize import VASP_CATEGORIES
from .provenance import case_headline, file_sha256  # noqa: F401 - re-exported
from .trace import ZERO, TraceConfig, TraceEdge, TraceNode, TraceResult, trace

SEED = 26182
CODE_VERSION = "b5-bitcoin-1"
# why traced money stopped -> the slice the UI shows
STOP_KIND = {"hub": "hub", "depth_limit": "beyond_hop_limit", "unspent": "not_moved",
             "truncated": "not_followed", "small": "not_followed", "budget": "not_followed",
             "error": "not_followed", "returned": "returned", "fee": "fee",
             "pooled": "not_followed", "coinjoin": "not_followed", "no_address": "not_followed"}


TRACE_MAX_PAGES = 5


def trace_provider(chain: str, fetcher, cfg: TraceConfig = TraceConfig(), **opts):
    """The adapter settings every trace uses. They are part of each request (and so of
    each cache key), so live runs, offline replays and recorded fixtures must agree."""
    return get_provider(chain, fetcher, page_size=cfg.fetch_limit, max_pages=TRACE_MAX_PAGES,
                        **opts)


def case_id_for(chain: str, address: str) -> str:
    return "c-" + hashlib.sha256(f"{chain}:{address}".encode()).hexdigest()[:10]


def _f(d: Decimal | None) -> float | None:
    return None if d is None else float(d)


def _role(node: TraceNode) -> str:
    if node.side == "origin":
        return "suspect"
    lab = node.label
    if lab is not None:
        if lab.category == "exchange":
            return {"hot": "exchange_hot", "deposit": "exchange_deposit"}.get(lab.kind, "exchange")
        if lab.category in ("custodial_wallet", "swap_service", "bridge", "mixer", "sanctioned"):
            return lab.category
        return "unknown"
    if node.state == "hub":
        return "hub"
    return "intermediary" if node.state == "expanded" else "unknown"


def _label(lab: Label | None) -> dict | None:
    return None if lab is None else lab.as_dict()


def _graph(tr: TraceResult) -> dict:
    by_address: dict[str, TraceNode] = {}
    for side in ("origin", "outbound", "inbound"):      # seen both ways: the outbound view wins
        for (s, addr), node in tr.nodes.items():
            if s == side:
                by_address.setdefault(addr, node)
    nodes = [{"id": addr, "chain": tr.chain, "role": _role(n), "hop": n.hop,
              "label": _label(n.label),
              "cluster": n.label.entity if n.label and n.label.category in VASP_CATEGORIES else None,
              "is_hub": n.state == "hub"}
             for addr, n in by_address.items()]
    # one on-chain transfer is one edge, even when it was drawn on twice
    merged: dict[tuple, TraceEdge] = {}
    for e in tr.edges:
        key = (e.side, e.transfer)
        old = merged.get(key)
        merged[key] = e if old is None else TraceEdge(e.transfer, e.side, old.traced + e.traced,
                                                      min(old.hop, e.hop))
    order = sorted(merged.values(), key=lambda e: (e.side != "outbound", e.hop,
                                                   e.transfer.block_time, e.transfer.tx_hash,
                                                   e.transfer.to_addr))
    edges = [{"id": f"e{i}", "source": e.transfer.from_addr, "target": e.transfer.to_addr,
              "tx_hash": e.transfer.tx_hash, "asset": e.transfer.asset,
              "amount": float(e.transfer.amount), "amount_usd": _f(e.transfer.amount_usd),
              "traced_amount": float(e.traced), "block_time": e.transfer.block_time,
              "direction": e.side}
             for i, e in enumerate(order, 1)]
    return {"nodes": nodes, "edges": edges}


def _rail_edges(tr: TraceResult, att: Attribution) -> list[TraceEdge]:
    """The path the Hop Rail shows: the named candidate; else the alert; else the nearest
    candidate; else the wallet where most of the money stopped."""
    wanted = path_hashes(tr, att)
    if att.top is not None:
        return att.top.path_edges
    if wanted:
        alert = next((f for f in att.flags if f["severity"] == "high"
                      and ("outbound", f["wallet"]) in tr.nodes), None)
        if att.outcome == "SANCTIONED_OR_MIXER_REACHED" and alert is not None:
            return tr.path_to("outbound", alert["wallet"])
        return next(c for c in att.candidates if c.direction == "outbound").path_edges
    held = [n for (side, _), n in tr.nodes.items() if side == "outbound" and n.held > 0]
    if not held:
        return []
    return tr.path_to("outbound", max(held, key=lambda n: (n.held, n.address)).address)


def _hop_rail(edges: list[TraceEdge]) -> list[dict]:
    rail, prev = [], None
    for i, e in enumerate(edges, 1):
        t = e.transfer
        rail.append({"index": i, "from_address": t.from_addr, "to_address": t.to_addr,
                     "tx_hash": t.tx_hash, "asset": t.asset, "amount": float(t.amount),
                     "amount_usd": _f(t.amount_usd), "traced_amount": float(e.traced),
                     "block_time": t.block_time,
                     "elapsed_s": None if prev is None
                     else int((t.block_time - prev).total_seconds())})
        prev = t.block_time
    return rail


def _candidate(c: Candidate) -> dict:
    return {"vasp": c.vasp, "category": c.category, "proximity_rank": c.proximity_rank,
            "confidence": c.confidence,
            "confidence_interval": list(c.confidence_interval) if c.confidence_interval else None,
            "direction": c.direction,
            "hops": c.hops, "share_of_funds": round(float(c.share), 4),
            "time_to_reach_s": c.time_to_reach_s, "label_tier": c.label_tier,
            "deposit_address": c.deposit_address, "path": c.path, "evidence": c.evidence,
            "counterfactual": c.counterfactual, "counterfactual_holds": c.counterfactual_holds,
            **_request_facts(c)}


def _request_facts(c: Candidate) -> dict:
    """What a request to this VASP is built from (B8): the exact sum, and the wallets to
    ask about, each with its own share of it (attribute/rules.py::_request_wallets)."""
    return {"amount": _f(c.amount),
            "request_wallets": [{
                **w, "amount": _f(w["amount"]),
                "reached_at": w["reached_at"].astimezone(timezone.utc)
                                             .strftime("%Y-%m-%dT%H:%M:%SZ")}
                for w in c.request_wallets]}


def _where(tr: TraceResult) -> list[dict]:
    if not tr.total_out:
        return []
    slices: dict[tuple[str, str | None], Decimal] = {}

    def add(kind: str, name: str | None, amount: Decimal) -> None:
        if amount > 0:
            slices[(kind, name)] = slices.get((kind, name), ZERO) + amount

    for (side, _), n in tr.nodes.items():
        if side != "outbound" or n.label is None:
            continue
        cat = n.label.category
        kind = "vasp" if cat in VASP_CATEGORIES else cat if cat in ("sanctioned", "mixer",
                                                                    "bridge") else "other_label"
        add(kind, n.label.entity, n.held)
    for reason, amount in tr.stopped.items():
        if reason != "labelled":
            add(STOP_KIND[reason], None, amount)
    ranked = sorted(slices.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1] or ""))
    return [{"kind": kind, "name": name, "share": round(float(amount / tr.total_out), 4),
             "amount": float(amount)} for (kind, name), amount in ranked]


def skeleton(summary: dict) -> dict:
    """A CaseDetail for a case that has no result yet (queued, running or failed)."""
    return {**summary, "hop_rail": [], "graph": {"nodes": [], "edges": []}, "candidates": [],
            "typology_flags": [], "narrative": "", "abstain_reason": None,
            "what_would_change": [], "next_steps": [],
            "provenance": {"seed": SEED, "code_version": CODE_VERSION}}


def build_case(tr: TraceResult, att: Attribution, *, case_id: str, meta: dict | None = None,
               rules: RuleConfig = RuleConfig(), now: datetime | None = None,
               demo: bool = False, provenance: dict | None = None) -> dict:
    meta = meta or {}
    top = att.top
    detail = {
        "id": case_id, "address": tr.address, "chain": tr.chain, "status": "done",
        "outcome": att.outcome, "top_vasp": top.vasp if top else None,
        "confidence": top.confidence if top else None,
        "case_ref": meta.get("case_ref"), "complaint_no": meta.get("complaint_no"),
        "amount_lost_inr": meta.get("amount_lost_inr"),
        "created_at": now or datetime.now(timezone.utc), "demo": demo, "error": None,
        "asset": tr.asset, "total_sent": float(tr.total_out) if tr.asset else None,
        "total_received": float(tr.total_in) if tr.in_asset else None,
        "where_funds_went": _where(tr),
        "hop_rail": _hop_rail(_rail_edges(tr, att)), "graph": _graph(tr),
        "candidates": [_candidate(c) for c in att.candidates],
        "typology_flags": att.flags, "narrative": narrative(tr, att, rules),
        "abstain_reason": att.abstain_reason, "what_would_change": att.what_would_change,
        "next_steps": att.next_steps,
        "provenance": {"seed": SEED, "code_version": CODE_VERSION, **(provenance or {})},
    }
    return S.CaseDetail.model_validate(detail).model_dump(mode="json")


def run_case(address: str, chain: str, provider, labels, *, case_id: str | None = None,
             meta: dict | None = None, cfg: TraceConfig = TraceConfig(),
             rules: RuleConfig = RuleConfig(), fetcher=None, label_db_sha256: str | None = None,
             now: datetime | None = None, demo: bool = False, scorer="auto") -> dict:
    """Trace `address`, attribute it, check each named exchange against the loss of its
    label, score the unlabelled wallets on the trail, and return the CaseDetail as a
    JSON-ready dict. `fetcher` (the one behind `provider`) is read for provenance, and
    the deposit-address model reads its listings through it (`scorer`: "auto" builds the
    chain's scorer on `fetcher`; None scores nothing)."""
    pages_before = len(fetcher.trail) if fetcher is not None else 0
    live_before = fetcher.stats["live"] if fetcher is not None else 0
    # Bitcoin: a wallet with no label of its own may still be an exchange's by its cluster
    labels = cluster_labels(chain, labels, provider)
    tr = trace(address, chain, provider, labels, cfg)
    att = attribute(tr, rules)
    add_counterfactuals(tr, att, provider, labels, cfg, rules)
    if scorer == "auto":
        from .classify.runtime import make_scorer
        scorer = make_scorer(chain, fetcher) if fetcher is not None else None
    notes = add_leads(tr, att, scorer, labels)
    now = now or datetime.now(timezone.utc)
    prov: dict = {"label_db_sha256": label_db_sha256, "notes": notes}
    trail = fetcher.trail[pages_before:] if fetcher is not None else []
    if fetcher is not None:
        went_live = fetcher.stats["live"] > live_before
        hosts = sorted({urlsplit(p["query"]).netloc for p in trail})
        prov.update(offline_replay=not went_live, fetched_at=now if went_live else None,
                    data_sources=hosts + ["label store"])
    prov.update(P.run_provenance(P.case_input(address, chain, cfg.max_hops, cfg.since), trail,
                                 model_dir=getattr(scorer, "model_dir", None)))
    detail = build_case(tr, att, case_id=case_id or case_id_for(chain, address), meta=meta,
                        rules=rules, now=now, demo=demo, provenance=prov)
    # the fingerprint is taken from the case as it is stored and served (JSON form)
    detail["provenance"]["findings_sha256"] = P.findings_sha256(detail)
    detail["provenance"]["content_sha256"] = P.content_sha256(detail)
    return detail


# ------------------------------------------------------------------ verify (B9)
def replay_case(case_in: dict, fetcher, labels, *, label_db_sha256: str | None = None,
                **provider_opts) -> dict:
    """Trace the wallet of a receipt's `input` again, exactly as a case run does."""
    since = case_in.get("since")
    if isinstance(since, str):
        since = datetime.fromisoformat(since.replace("Z", "+00:00"))
    cfg = TraceConfig(max_hops=case_in["max_hops"], since=since)
    chain = case_in["chain"]
    scorer = "auto"
    if provider_opts:
        from .classify.runtime import make_scorer
        scorer = make_scorer(chain, fetcher, **provider_opts)
    return run_case(case_in["address"], chain,
                    trace_provider(chain, fetcher, cfg, **provider_opts), labels, cfg=cfg,
                    fetcher=fetcher, label_db_sha256=label_db_sha256, scorer=scorer)


def _cache_only(fetcher) -> None:
    if not fetcher.offline:
        raise ValueError("verify reads the cache only: give it an offline fetcher "
                         "(chains.cache_only_fetcher())")


def verify_stored(case: dict, fetcher, labels, *, label_db_sha256: str | None = None,
                  now: datetime | None = None, **provider_opts) -> dict:
    """`provenance.verify_case` on the real pipeline. `fetcher` must be cache-only: a
    verification that fetched fresh pages would be checking the chain as it is now, not
    the responses the case was computed from."""
    _cache_only(fetcher)
    return P.verify_case(
        case, lambda case_in: replay_case(case_in, fetcher, labels,
                                          label_db_sha256=label_db_sha256, **provider_opts),
        label_db_sha256=label_db_sha256, now=now)


def verify_receipt(doc: dict, fetcher, labels, *, label_db_sha256: str | None = None,
                   now: datetime | None = None, **provider_opts) -> dict:
    _cache_only(fetcher)
    return P.verify_receipt(
        doc, lambda case_in: replay_case(case_in, fetcher, labels,
                                         label_db_sha256=label_db_sha256, **provider_opts),
        label_db_sha256=label_db_sha256, now=now)
