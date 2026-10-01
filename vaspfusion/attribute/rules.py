"""Rule attribution: from the labelled wallets a trace reached to ranked candidates,
a confidence and an outcome.

Two numbers per candidate, never blended:

* `proximity_rank`: 1 = nearest. Fewest hops, then largest share of the funds,
  then fastest. Outbound candidates (where the money went) rank before inbound
  ones (who funded the wallet).
* `confidence`: how far the evidence supports "this wallet's money reached that
  VASP". Rule-based and NOT calibrated; B6 replaces it with a calibrated model.

      confidence = share factor x average over the traced money of
                   (tier weight of the label it reached x hop_decay^(hops - 1))
      share factor = min(1, share / share_full)

  The share of the funds is its own field (`share_of_funds`), so it only scales
  confidence down when it is small: a wallet that splits its money between two
  exchanges has sent money to both of them, and each can be named. With
  `share_full = 1` the formula is the plain product tier weight x share x hop decay.

Outcome: SANCTIONED_OR_MIXER_REACHED when a meaningful share reached a sanctioned
or mixer label; else ATTRIBUTED when an outbound VASP candidate clears
`attribute_min` (the nearest one that does is named); else INSUFFICIENT_EVIDENCE,
with the reason and what would change it. Abstaining is a result, not a failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..explain import fmt
from ..labels.lookup import Label
from ..labels.normalize import VASP_CATEGORIES
from ..trace import ZERO, TraceEdge, TraceNode, TraceResult

TIER_WEIGHT = {"published_por": 0.95, "curated": 0.85, "explorer_tag": 0.75, "derived": 0.6}
ALERT_CATEGORIES = {"sanctioned": "sanctioned_contact", "mixer": "mixer_contact"}
UNROUTABLE = "Unidentified exchange"


@dataclass(frozen=True)
class RuleConfig:
    hop_decay: float = 0.85
    share_full: float = 0.25       # a share this large counts in full (1.0 = plain product)
    attribute_min: float = 0.60    # confidence needed to name a VASP
    alert_min_share: float = 0.01  # share at a sanctioned/mixer label that sets the outcome


@dataclass(frozen=True)
class Candidate:
    vasp: str
    category: str
    direction: str                 # "outbound" | "inbound"
    confidence: float
    hops: int
    share: Decimal
    amount: Decimal
    time_to_reach_s: int | None
    label: Label                   # of the main entry (the labelled wallet that got the most)
    deposit_address: str
    path: list[str]
    path_edges: list[TraceEdge]
    entries: list[TraceNode]
    last_hop: str | None           # last unlabelled wallet before the entry, if any
    evidence: list[dict]
    proximity_rank: int = 0
    hops_min: int = 0              # shortest and longest route the money took to this VASP;
    hops_max: int = 0              # `hops` is the route in `path` (to the main entry)
    passed_all: bool = False       # last_hop forwarded everything it got from this trail

    @property
    def label_tier(self) -> str:
        return self.label.tier


@dataclass
class Attribution:
    outcome: str
    top: Candidate | None
    candidates: list[Candidate]
    flags: list[dict] = field(default_factory=list)
    abstain_reason: str | None = None
    what_would_change: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ candidates
def _candidate(tr: TraceResult, side: str, vasp: str, entries: list[TraceNode],
               cfg: RuleConfig) -> Candidate:
    total = tr.total_out if side == "outbound" else tr.total_in
    asset = tr.asset if side == "outbound" else tr.in_asset
    amount = sum((n.received for n in entries), ZERO)
    share = amount / total
    main = max(entries, key=lambda n: (n.received, n.address))
    weighted, route_hops = 0.0, []
    for n in entries:
        for e in tr.edges_into(side, n.address):
            weighted += TIER_WEIGHT[n.label.tier] * cfg.hop_decay ** (e.hop - 1) * float(e.traced)
            route_hops.append(e.hop)
    hops_min, hops_max = min(route_hops), max(route_hops)
    confidence = min(1.0, float(share) / cfg.share_full) * weighted / float(amount)
    # hops, path, entry address, time and last hop all describe ONE route: the nearest
    # one into the entry that received the most
    edges = tr.path_to(side, main.address)
    addresses = [edges[0].transfer.from_addr] + [e.transfer.to_addr for e in edges]
    took = int((edges[-1].transfer.block_time - edges[0].transfer.block_time).total_seconds())
    hop_count = len(edges)
    last_hop = None
    if side == "outbound" and len(edges) > 1:
        last_hop = edges[-1].transfer.from_addr

    verb = "reached it" if side == "outbound" else "came from it"
    evidence = [{
        "kind": "label", "tier": main.label.tier, "tx_hashes": [],
        "weight": TIER_WEIGHT[main.label.tier],
        "text": f"{fmt.short(main.address)} is labelled {main.label.entity}"
                + (f" (\"{main.label.label}\")" if main.label.label else "")
                + f": {fmt.tier_words(main.label.tier)}, source {main.label.source}",
    }, {
        "kind": "path", "tier": None, "tx_hashes": [e.transfer.tx_hash for e in edges],
        "weight": round(confidence / TIER_WEIGHT[main.label.tier], 4),
        "text": f"{fmt.pct(share)} of the wallet's {asset} ({fmt.amount(amount, asset)}) {verb} "
                f"in {fmt.hops(hops_min, hops_max)}"
                + (f" within {fmt.duration(took)}" if len(edges) > 1 and hops_max == hops_min
                   else ""),
    }]
    passed_all = False
    if last_hop is not None:
        node = tr.nodes[(side, last_hop)]
        onward = [e for n in entries for e in tr.edges_into(side, n.address)
                  if e.transfer.from_addr == last_hop]
        passed = sum((e.traced for e in onward), ZERO)
        if node.received and passed == node.received:
            passed_all = True
            wait = int((edges[-1].transfer.block_time
                        - edges[-2].transfer.block_time).total_seconds())
            evidence.append({
                "kind": "path", "tier": None, "weight": None,
                "tx_hashes": sorted({e.transfer.tx_hash for e in onward}),
                "text": f"{fmt.short(last_hop)} passed on all {fmt.amount(passed, asset)} it "
                        f"received from this trail to {vasp}"
                        + (f", within {fmt.duration(wait)}" if len(onward) == 1 else ""),
            })
    return Candidate(vasp=vasp, category=main.label.category, direction=side,
                     confidence=round(min(1.0, confidence), 4), hops=hop_count, share=share,
                     amount=amount, time_to_reach_s=took, label=main.label,
                     deposit_address=main.address, path=addresses, path_edges=edges,
                     entries=sorted(entries, key=lambda n: (-n.received, n.address)),
                     last_hop=last_hop, evidence=evidence, hops_min=hops_min,
                     hops_max=hops_max, passed_all=passed_all)


def _self_candidate(tr: TraceResult) -> Candidate:
    lab = tr.origin_label
    return Candidate(
        vasp=lab.entity, category=lab.category, direction="outbound",
        confidence=TIER_WEIGHT[lab.tier], hops=0, share=Decimal(1), amount=ZERO,
        time_to_reach_s=None, label=lab, deposit_address=tr.address, path=[tr.address],
        path_edges=[], entries=[tr.nodes[("origin", tr.address)]], last_hop=None,
        evidence=[{"kind": "label", "tier": lab.tier, "tx_hashes": [],
                   "weight": TIER_WEIGHT[lab.tier],
                   "text": f"The address itself is labelled {lab.entity}"
                           + (f" (\"{lab.label}\")" if lab.label else "")
                           + f": {fmt.tier_words(lab.tier)}, source {lab.source}"}])


def _candidates(tr: TraceResult, cfg: RuleConfig) -> list[Candidate]:
    found: list[Candidate] = []
    if tr.origin_label is not None and tr.origin_label.category in VASP_CATEGORIES:
        found.append(_self_candidate(tr))
    for side in ("outbound", "inbound"):
        groups: dict[tuple[str, str], list[TraceNode]] = {}
        for (s, addr), node in tr.nodes.items():
            if s == side and node.label is not None and node.received > 0 \
                    and node.label.category in VASP_CATEGORIES:
                # wallets tagged "exchange" with no owner are not one exchange: keep them apart
                key = (node.label.entity, addr if node.label.entity == UNROUTABLE else "")
                groups.setdefault(key, []).append(node)
        found += [_candidate(tr, side, vasp, entries, cfg)
                  for (vasp, _), entries in groups.items()]
    found.sort(key=lambda c: (c.direction != "outbound", c.hops, -c.share,
                              c.time_to_reach_s if c.time_to_reach_s is not None else 0, c.vasp,
                              c.deposit_address))
    return [Candidate(**{**c.__dict__, "proximity_rank": i}) for i, c in enumerate(found, 1)]


# ------------------------------------------------------------------ flags
def _flags(tr: TraceResult) -> list[dict]:
    flags: list[dict] = []
    lab = tr.origin_label
    if lab is not None and lab.category in ALERT_CATEGORIES:
        flags.append({"code": ALERT_CATEGORIES[lab.category], "severity": "high",
                      "wallet": tr.address, "figures": {}, "tx_hashes": [],
                      "text": f"The wallet itself is labelled {lab.entity} ({lab.category})"})
    for (side, addr), node in tr.nodes.items():
        if side == "origin" or node.label is None or node.received <= 0:
            continue
        cat = node.label.category
        if cat not in ALERT_CATEGORIES and cat != "bridge":
            continue
        total = tr.total_out if side == "outbound" else tr.total_in
        asset = tr.asset if side == "outbound" else tr.in_asset
        share = float(node.received / total)
        what = {"sanctioned": "a sanctioned address", "mixer": "a mixer",
                "bridge": "a bridge"}[cat]
        if side == "outbound":
            text = (f"{fmt.pct(share)} of the funds ({fmt.amount(node.received, asset)}) reached "
                    f"{what}, {fmt.short(addr)} ({node.label.entity}), {fmt.hops(node.hop)} away")
        else:
            text = (f"{fmt.pct(share)} of what the wallet received "
                    f"({fmt.amount(node.received, asset)}) was funded by {what}, "
                    f"{fmt.short(addr)} ({node.label.entity})")
        flags.append({
            "code": ALERT_CATEGORIES.get(cat, "bridge_hop"),
            "severity": "high" if cat in ALERT_CATEGORIES else "warn",
            "wallet": addr, "text": text,
            "figures": {"share": round(share, 4), "amount": float(node.received),
                        "hops": float(node.hop)},
            "tx_hashes": sorted({e.transfer.tx_hash for e in tr.edges_into(side, addr)}),
        })
    order = {"high": 0, "warn": 1, "info": 2}
    flags.sort(key=lambda f: (order[f["severity"]], -f["figures"].get("share", 1.0), f["wallet"]))
    return flags


def _alert_share(tr: TraceResult) -> float:
    if not tr.total_out:
        return 0.0
    hit = sum((n.received for (side, _), n in tr.nodes.items()
               if side == "outbound" and n.label is not None
               and n.label.category in ALERT_CATEGORIES), ZERO)
    return float(hit / tr.total_out)


# ------------------------------------------------------------------ abstain
def _where_it_stopped(tr: TraceResult) -> tuple[list[str], list[str]]:
    """(sentences for the abstain reason, evidence that would change the answer)."""
    asset, total = tr.asset, tr.total_out
    said: list[str] = []
    change: list[str] = []

    def nodes(reason: str) -> list[TraceNode]:
        return sorted((n for (side, _), n in tr.nodes.items()
                       if side == "outbound" and n.holds.get(reason, ZERO) > 0),
                      key=lambda n: (-n.holds[reason], n.address))

    other: dict[str, Decimal] = {}
    for (side, _), n in tr.nodes.items():
        if side == "outbound" and n.label is not None and n.held > 0 \
                and n.label.category not in VASP_CATEGORIES:
            key = {"bridge": "a bridge", "defi": "a DeFi contract", "sanctioned":
                   "a sanctioned address", "mixer": "a mixer", "scam": "an address listed as a "
                   "scam"}.get(n.label.category, "a named wallet that is not an exchange")
            key = f"{key} ({n.label.entity})"
            other[key] = other.get(key, ZERO) + n.held
    for key, held in sorted(other.items(), key=lambda kv: (-kv[1], kv[0])):
        said.append(f"{fmt.pct(held / total)} went into {key}")
        if key.startswith("a bridge"):
            change.append(f"Following the funds across the bridge ({key[10:-1]}) onto the "
                          "destination chain")

    phrases = {
        "hub": ("stopped at unlabelled high-activity wallets, where funds from many senders mix",
                "A label for {a} (holds {p} of the funds; it pays out to many wallets and may "
                "be an exchange or payment service)"),
        "depth_limit": (f"went past the {fmt.hops(tr.config.max_hops)} that were traced",
                        "Tracing deeper than {h} from {a} ({p} of the funds)"),
        "unspent": ("has not moved on from the wallets it reached",
                    "Watching {a}: {p} of the funds is still there"),
        "truncated": ("is in wallets with more transfers than one fetch reads",
                      "A full history of {a} ({p} of the funds)"),
        "small": ("split into parts too small to follow", None),
        "budget": ("is in wallets beyond the trace budget",
                   "A larger trace budget: {a} holds {p} of the funds"),
        "error": ("is in wallets whose transfers could not be fetched",
                  "Fetching {a} again ({p} of the funds; the request failed)"),
        "returned": ("came back to the wallet itself", None),
    }
    for reason, (text, hint) in phrases.items():
        held = tr.stopped.get(reason, ZERO)
        if held <= 0:
            continue
        said.append(f"{fmt.pct(held / total)} {text}")
        if hint:
            for n in nodes(reason)[:2]:
                change.append(hint.format(a=fmt.short(n.address),
                                          p=fmt.pct(n.holds[reason] / total),
                                          h=fmt.hops(tr.config.max_hops)))
    return said, change


def _abstain(tr: TraceResult, cands: list[Candidate], cfg: RuleConfig) -> tuple[str, list[str]]:
    if tr.origin_label is not None and tr.asset is None and not tr.total_out \
            and tr.notes and "not traced" in tr.notes[0]:
        return (tr.notes[0], [])
    if tr.asset is None:
        return ("The wallet has not sent any funds that can be traced (no outgoing stablecoin "
                "or native-coin transfers above dust).",
                ["An outgoing transfer from this wallet"])
    said, change = _where_it_stopped(tr)
    out = [c for c in cands if c.direction == "outbound"]
    if out:
        best = max(out, key=lambda c: (c.confidence, -c.proximity_rank))
        reason = (f"Only {fmt.pct(best.share)} of the funds reached a labelled VASP "
                  f"({best.vasp}), {fmt.hops(best.hops)} away; rule confidence "
                  f"{best.confidence:.2f} is below the {cfg.attribute_min:.2f} needed to name one.")
        if best.share < Decimal(str(cfg.share_full)):
            change.insert(0, f"A larger part of the funds reaching {best.vasp} (now "
                             f"{fmt.pct(best.share)}; {fmt.pct(cfg.share_full)} or more counts "
                             "in full)")
        if best.label.tier != "published_por":
            change.append(f"A stronger label for {fmt.short(best.deposit_address)} "
                          f"(now: {fmt.tier_words(best.label.tier)})")
    else:
        reason = (f"None of the {fmt.amount(tr.total_out, tr.asset)} this wallet sent reached a "
                  f"labelled exchange within {fmt.hops(tr.config.max_hops)}.")
    if said:
        reason += " " + "; ".join(said) + "."
    return reason, list(dict.fromkeys(change))


def _abstain_steps(tr: TraceResult, cands: list[Candidate]) -> list[str]:
    """What an officer can do when no exchange is named."""
    steps = []
    if tr.total_out:
        hubs = sorted((n for (side, _), n in tr.nodes.items()
                       if side == "outbound" and n.holds.get("hub", ZERO) > 0),
                      key=lambda n: (-n.holds["hub"], n.address))
        for n in hubs[:2]:
            steps.append(f"Identify {fmt.short(n.address)}: {fmt.pct(n.holds['hub'] / tr.total_out)}"
                         " of the funds stopped there and it behaves like a service wallet "
                         "(check other label sources and block explorers)")
    for c in cands:
        if c.direction == "outbound" and c.hops > 0:
            steps.append(f"{c.vasp} did receive {fmt.pct(c.share)} of the funds "
                         f"({fmt.amount(c.amount, tr.asset)}) at {fmt.short(c.deposit_address)}; "
                         "a request limited to that deposit can still be drafted")
    if tr.stopped.get("depth_limit", ZERO) > 0 and tr.config.max_hops < 5:
        steps.append(f"Run the trace again with more than {fmt.hops(tr.config.max_hops)}")
    return steps


# ------------------------------------------------------------------ outcome
def attribute(tr: TraceResult, cfg: RuleConfig = RuleConfig()) -> Attribution:
    cands = _candidates(tr, cfg)
    flags = _flags(tr)
    clearing = [c for c in cands if c.direction == "outbound" and c.confidence >= cfg.attribute_min]
    top = clearing[0] if clearing else None          # candidates are in proximity order
    origin_alert = tr.origin_label is not None and tr.origin_label.category in ALERT_CATEGORIES
    alert = _alert_share(tr)

    att = Attribution(outcome="INSUFFICIENT_EVIDENCE", top=top, candidates=cands, flags=flags)
    if origin_alert or alert >= cfg.alert_min_share:
        att.outcome = "SANCTIONED_OR_MIXER_REACHED"
        att.next_steps.append(
            "Escalate: " + (flags[0]["text"][0].lower() + flags[0]["text"][1:]))
    elif top is not None:
        att.outcome = "ATTRIBUTED"
    else:
        att.abstain_reason, att.what_would_change = _abstain(tr, cands, cfg)

    for c in clearing:
        if c.vasp == UNROUTABLE:
            att.next_steps.append(
                f"{fmt.short(c.deposit_address)} is tagged as an exchange but the source names "
                "no owner; no request can be routed until the exchange is identified")
            continue
        if c.hops == 0:
            att.next_steps.append(f"This is {c.vasp}'s own wallet: ask {c.vasp} about the "
                                  "transfers of interest directly")
            continue
        # the customer's deposit wallet is the labelled deposit address itself, or else
        # the hop before the exchange wallet, but only if it forwarded everything
        where = c.last_hop if c.passed_all and c.label.kind != "deposit" else c.deposit_address
        att.next_steps.append(
            f"Draft a request to {c.vasp} for KYC and a freeze on the account behind "
            f"{fmt.short(where)}" + ("" if c is top else f" ({fmt.pct(c.share)} of the funds)"))
    if clearing:
        att.next_steps.append("Preserve the transaction records listed in the evidence")
    for c in cands:
        if c.direction == "inbound":
            att.next_steps.append(
                f"The wallet was funded from {c.vasp} ({fmt.pct(c.share)} of what it received): "
                f"ask {c.vasp} which account withdrew to it")
    if att.outcome == "INSUFFICIENT_EVIDENCE":
        att.next_steps = _abstain_steps(tr, cands) + att.next_steps
    return att
