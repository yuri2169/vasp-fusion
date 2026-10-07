"""The API contract shared by the backend (B-track) and the UI (U-track).

This module is the single source of truth. `docs/api_contract.md` describes it,
`mocks/*.json` are validated against it, and `ui/src/api/types.ts` is generated
from the OpenAPI schema FastAPI derives from it (`make types`). Change a model
here and regenerate; never hand-edit the TypeScript.

Two rules are encoded in the types, not just in the docs:
  * proximity and confidence are separate fields - never blended into one score;
  * a case can end in INSUFFICIENT_EVIDENCE, and then it says why and what
    evidence would change the answer, instead of guessing a VASP.
"""
from __future__ import annotations

import json
from pathlib import Path

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

# ------------------------------------------------------------------ enums
TraceChain = Literal["tron", "ethereum", "bsc", "polygon", "arbitrum", "base",
                     "optimism", "avalanche", "bitcoin", "solana"]
Category = Literal["exchange", "custodial_wallet", "swap_service", "sanctioned", "scam",
                   "mixer", "bridge", "defi", "entity"]
Kind = Literal["hot", "cold", "deposit", "reserve", "unknown"]
Tier = Literal["published_por", "curated", "explorer_tag", "derived"]
Outcome = Literal["ATTRIBUTED", "INSUFFICIENT_EVIDENCE", "SANCTIONED_OR_MIXER_REACHED"]
CaseStatus = Literal["queued", "running", "done", "failed"]
NodeRole = Literal["suspect", "intermediary", "exchange_hot", "exchange_deposit",
                   "exchange", "custodial_wallet", "swap_service", "bridge", "mixer",
                   "sanctioned", "hub", "unknown"]
TypologyCode = Literal["peel_chain", "fan_out", "fan_in", "rapid_forwarding",
                       "round_amounts", "bridge_hop", "mixer_contact", "sanctioned_contact",
                       "threat_contact",   # a link to a threat-tagged address (G3)
                       "deposit_like",
                       "coinjoin_shape"]   # Bitcoin: a pattern, never an alert (B5)
Severity = Literal["info", "warn", "high"]
Threat = Literal["terrorism_financing", "ransomware", "darknet_market", "fraud",
                 "sanctioned_other"]
EvidenceKind = Literal["label", "path", "sweep", "gas_payer", "model", "counterfactual"]
RequestStatus = Literal["drafted", "approved", "sent", "acknowledged", "answered",
                        "freeze_confirmed", "refused", "withdrawn"]
Ask = Literal["kyc", "transactions", "freeze", "preservation"]
FollowUpKind = Literal["reply_overdue", "freeze_lapsing", "preservation_closing"]
Direction = Literal["outbound", "inbound"]
RiskClass = Literal["low", "medium", "high", "severe"]


def _risk_basis() -> str:
    """What the risk score is, in the sentence that travels with it. The figures are read
    from the tracked measurement (artifacts/risk_validation_v1/results.json, `make
    risk-validation`), so the sentence cannot say more than was measured."""
    start = "An indicator score from published red-flag rules. Not a probability"
    path = Path(__file__).resolve().parents[2] / "artifacts" / "risk_validation_v1" / "results.json"
    try:
        m = json.loads(path.read_text())
        view = m["views"][m["main_view"]]
        p, c = view["arms"]["positive"], view["arms"]["control"]
        p_n, c_n = p["wallets"] - p["could_not_be_read"], c["wallets"] - c["could_not_be_read"]
        linked, better = view["positives_high_with_list_link"], view["rules_firing_more_on_positives"]
    except (OSError, ValueError, KeyError):
        return start + ", and not measured against known outcomes."
    rules = ("No pattern rule fired more often on the listed wallets than on the ordinary ones"
             if not better else
             f"{len(better)} of the pattern rules fired more often on the listed wallets")
    how = "all of those" if linked == p["high_or_above"] else \
        f"{linked} of those {p['high_or_above']}"
    return (f"{start}. Checked on {p_n} wallets that public sources list as illicit and {c_n} "
            f"with a documented ordinary purpose, each with its own label hidden: "
            f"{p['high_or_above']} of {p_n} and {c['high_or_above']} of {c_n} scored High or "
            f"above, {how} through a link to another listed address. {rules}. The points were not fitted to these wallets, which are not a "
            "sample of real complaints.")


RISK_BASIS = _risk_basis()
FundsKind = Literal["vasp", "sanctioned", "mixer", "bridge", "other_label", "hub",
                    "beyond_hop_limit", "not_moved", "not_followed", "returned",
                    "fee",   # Bitcoin only: miner fees paid along the trail (B5)
                    "bridge_fee"]   # what a followed bridge crossing cost (G4)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ labels
class ModelReason(_M):
    feature: str = Field(description="The model feature, as a stable key")
    text: str = Field(description="What the address did, in plain English")
    weight: float = Field(description="SHAP value in log-odds: above 0 speaks for a deposit "
                                      "address, below 0 against")


class ModelScore(_M):
    """What the deposit-address model said about one address (B6)."""
    p: float = Field(ge=0, le=1, description="Calibrated probability that an address "
                     "behaving like this is an exchange deposit address")
    low: float = Field(ge=0, le=1, description="Venn-Abers range of p")
    high: float = Field(ge=0, le=1)
    basis: Literal["model", "rule"] = Field(description=(
        "model: the label's confidence is the model's value. rule: the model did not "
        "raise it, and the discovery rules' confidence is kept"))
    scored_by: str | None = Field(None, description="Which cross-fit model scored it; "
                                  "never one that trained on this address")
    reasons: list[ModelReason] = Field([], description="Strongest reasons, strongest first")


class ThreatTag(_M):
    """What a public source says an address belongs to (config/threats.yaml has the rule
    that produced it). Never an inference of this tool."""
    threat: Threat = Field(description=(
        "sanctioned_other: on the OFAC SDN list under a programme that names none of the "
        "other four"))
    entity: str | None = Field(None, description="Who the source names: a ransomware family, "
                                                 "a market, a listed person or organisation")
    source: str | None = Field(None, description="ofac-sdn-xml, ransomwhere, "
                                                 "graphsense-tagpack:<pack>, or a scam list")
    url: str | None = None
    evidence: str | None = Field(None, description="The source's own words: list entry, "
                                                   "programme codes, pack fields")


class LabelOut(_M):
    address: str
    chain: str = Field(description="Chain slug as stored; 'evm' = any EVM chain")
    entity: str
    category: Category
    kind: Kind
    tier: Tier
    source: str
    source_url: str | None = None
    label: str | None = Field(None, description="The upstream name tag, verbatim")
    confidence: float | None = Field(None, ge=0, le=1, description=(
        "tier=derived only. With confidence_low/high set: the weight of the exchange wallet's "
        "label x the deposit-address model's calibrated probability (B6). Without them: the "
        "discovery rules' hand-set confidence, not calibrated"))
    evidence: str | None = Field(None, description=(
        "tier=derived only: what the sweep and gas-payer rules saw, and what the model said, "
        "in plain English"))
    confidence_low: float | None = Field(None, ge=0, le=1, description=(
        "Model-scored labels only: low end of the calibrated range (Venn-Abers)"))
    confidence_high: float | None = Field(None, ge=0, le=1)
    model: ModelScore | None = Field(None, description=(
        "Labels the deposit-address model scored: its own probability, range and reasons, "
        "whether or not the label's confidence is based on it"))
    threat: Threat | None = Field(None, description=(
        "Set when a public source ties the address to a threat ecosystem. Sits beside "
        "`category`; the four fields below say who, per which source, in its own words"))
    threat_entity: str | None = None
    threat_source: str | None = None
    threat_url: str | None = None
    threat_evidence: str | None = None


class LabelSearch(_M):
    query: str
    total: int
    limit: int
    offset: int
    items: list[LabelOut]


# ------------------------------------------------------------------ cases
class CaseCreate(_M):
    address: str
    chain: TraceChain | None = Field(None, description="Omit to auto-detect")
    case_ref: str | None = None
    complaint_no: str | None = Field(None, description="1930 / NCRP complaint number")
    amount_lost_inr: float | None = Field(None, ge=0)
    incident_date: date | None = None
    max_hops: int = Field(3, ge=1, le=5)
    max_wallets: int = Field(40, ge=1, le=2000, description=(
        "Trace budget: wallets read per direction. The largest shares are read first"))
    max_seconds: float | None = Field(None, ge=1, le=3600, description=(
        "Trace budget: stop reading new wallets after this many seconds"))


# ------------------------------------------------------------------ batch intake (G5)
class BatchWallet(_M):
    address: str
    chain: str | None = Field(None, description="Omit to auto-detect")
    case_ref: str | None = None


class BatchCreate(_M):
    """Many wallets at once: `rows`, or the text of a CSV file in `csv` (columns address,
    chain, case_ref; a header line is optional). At most 2,000 rows."""
    name: str | None = Field(None, max_length=120, description="What the officer calls it")
    rows: list[BatchWallet] | None = None
    csv: str | None = Field(None, description="The CSV file's text")
    max_hops: int = Field(3, ge=1, le=5)
    max_wallets: int = Field(40, ge=1, le=2000)
    max_seconds: float | None = Field(None, ge=1, le=3600)


class BatchRow(_M):
    """One uploaded row and what became of it."""
    row: int = Field(description="Its number in the upload (a CSV's line number)")
    address: str
    chain: str | None = None
    case_ref: str | None = None
    accepted: bool
    error: str | None = Field(None, description="Why the row was refused, or why its "
                                               "trace failed")
    duplicate_of: int | None = Field(None, description="The earlier row with the same wallet")
    case_id: str | None = None
    case_url: str | None = None
    status: CaseStatus | None = None
    outcome: Outcome | None = None
    top_vasp: str | None = Field(None, description="The exchange the case names")
    hops: int | None = Field(None, description="Proximity: hops to that exchange")
    proximity_rank: int | None = None
    share_of_funds: float | None = None
    confidence: float | None = None
    risk_class: RiskClass | None = None
    budget_ended: bool = Field(False, description="The trace budget, not the evidence, "
                                                 "ended this wallet's trace")


class BatchProgress(_M):
    total: int = Field(description="Rows uploaded")
    accepted: int = Field(description="Wallets with a case (each wallet once)")
    duplicates: int
    refused: int
    queued: int
    running: int
    done: int
    failed: int
    by_outcome: dict[str, int] = {}
    finished: bool


class BatchSummary(_M):
    id: str
    name: str | None = None
    created_at: datetime
    created_by: str | None = None
    max_hops: int
    max_wallets: int
    max_seconds: float | None = None
    progress: BatchProgress
    workers: int = Field(description="Worker processes tracing the queue; 0 = traced one "
                                     "at a time in the server process")
    results_csv: str = Field(description="Where the result table downloads from")


class BatchDetail(BatchSummary):
    rows: list[BatchRow]


class BatchList(_M):
    total: int
    items: list[BatchSummary]


class ScaleRun(_M):
    workers: int
    cases: int
    seconds: float
    cases_per_minute: float
    median_seconds_per_case: float
    p95_seconds_per_case: float
    transfers_per_second: float
    peak_memory_mb: float | None = Field(None, description="Sum of every worker's peak")
    speedup: float = Field(description="Cases per minute over the one-worker run's")
    median_trace_seconds: float | None = Field(None, description=(
        "Median time a worker spent tracing one case, without the storing"))
    transfers_analysed: int | None = None
    chain_responses_read: int | None = None
    peak_memory_mb_per_worker: float | None = None
    workers_that_traced: int | None = None
    cases_per_worker: list[int] = []
    worker_startup_seconds: float | None = None
    golden_fingerprints_reproduced: str | None = Field(None, description=(
        "How many of the run's cases have the findings fingerprint the repository records"))


class ScaleMetrics(_M):
    """Measured throughput (`make bench-scale`, artifacts/scale/metrics.json)."""
    status: Literal["measured", "not_measured"]
    measured_on: str | None = None
    machine: str | None = None
    chain_data: str | None = Field(None, description="Where the chain responses came from")
    wallets: int | None = Field(None, description="Distinct recorded wallets replayed")
    rounds: int | None = Field(None, description="Times each wallet was replayed per run")
    runs: list[ScaleRun] = []
    one_process: dict | None = Field(None, description=(
        "The same cases in one process, in order, and where one case's time goes"))
    baseline: dict | None = Field(None, description="The same replay before the queue and "
                                                    "the worker pool existed")
    intake: dict | None = Field(None, description="Batch upload through the API, timed")
    limits: list[str] = []
    notes: list[str] = []


class Screening(_M):
    """The check of the case's own address against the threat tags, made when the case
    is opened and before the trace starts."""
    hit: bool
    text: str = Field(description="One sentence to show as it is")
    tag: ThreatTag | None = None


class DocumentedSource(_M):
    name: str
    url: str


class DocumentedCase(_M):
    """A recorded case whose address comes from a publicly documented incident."""
    title: str
    what_happened: str = Field(description="The incident, as the cited sources state it")
    statement: str = Field(description="What the trace shows, and what it does not")
    sources: list[DocumentedSource]


class CaseSummary(_M):
    id: str
    address: str
    chain: TraceChain
    status: CaseStatus
    outcome: Outcome | None = None
    top_vasp: str | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    case_ref: str | None = None
    complaint_no: str | None = None
    amount_lost_inr: float | None = None
    created_at: datetime
    demo: bool = False
    error: str | None = Field(None, description="Set when status is 'failed': what went "
                                                "wrong, in plain English")
    screening: Screening | None = Field(None, description=(
        "Present from the moment the case is opened (also while queued or running). null "
        "on a case stored before screening existed"))
    threats: list[Threat] = Field([], description=(
        "The distinct threats the case touches: its own address's tag and every flagged "
        "link. While the trace runs it holds the screening hit only"))
    risk_class: RiskClass | None = Field(None, description=(
        "Of a finished case (risk.py). Worked out when the case is read, never stored"))
    risk_score: int | None = Field(None, ge=0, le=100, description=RISK_BASIS)
    sahyog_complaint_ref: str | None = Field(None, description=(
        "Set when the case was opened by a complaint filed through the SAHYOG intake API: "
        "show 'Reported through SAHYOG' with this reference"))
    documented: DocumentedCase | None = Field(None, description=(
        "Set on a recorded case that is a publicly documented incident (demo/cases.json): "
        "show the statement and the sources wherever the case is offered"))


class CaseList(_M):
    total: int
    items: list[CaseSummary]


CrossingStatus = Literal["followed", "not_traced", "unresolved"]


class Crossing(_M):
    """One deposit into a bridge and what became of it (G4).

    `followed`: the bridge's index matched the deposit to a payout, the payout was read
    on the destination chain and the trace goes on from the recipient. `not_traced`:
    matched (chain, recipient and payout transaction are set), but the trace could not go
    on there; `reason` says why. `unresolved`: no match; the trail ends at the bridge."""
    bridge: str = Field(description="The bridge, as its label names it")
    bridge_address: str = Field(description="The bridge wallet the deposit went into")
    status: CrossingStatus
    reason: str | None = Field(None, description="Why it was not followed")
    source_chain: TraceChain
    source_tx: str = Field(description="The deposit transaction, on source_chain")
    asset_in: str
    amount_in: float = Field(description="The whole deposit")
    traced_in: float = Field(description="The part of it that is the suspect wallet's money")
    dest_chain: TraceChain | None = Field(None, description=(
        "Set when the money came out on a chain this tool reads"))
    dest_name: str | None = Field(None, description="The destination as it is said")
    recipient: str | None = None
    payout_tx: str | None = Field(None, description="On the destination chain")
    paid_by: str | None = Field(None, description=(
        "The address that paid the recipient in payout_tx (a contract of the bridge)"))
    asset_out: str | None = None
    amount_out: float | None = Field(None, description=(
        "What the recipient received in payout_tx, read on the destination chain. It can "
        "be less than the bridge quotes"))
    traced_out: float | None = Field(None, description="The followed part of amount_out")
    fee: float | None = Field(None, description=(
        "traced_in - traced_out: what the crossing cost. Counted as a fee in "
        "where_funds_went, never as missing money"))
    seconds: int | None = Field(None, description="From the deposit to the payout")
    deposited_at: datetime | None = None
    paid_at: datetime | None = None
    matched_by: str | None = Field(None, description=(
        "Who says the two transactions belong together: the host of the bridge's index"))


class Hop(_M):
    """One step on the Hop Rail: money moved from `from_address` to `to_address`. On a
    cross-chain step `bridge` is set: `from_address` is the bridge wallet on `from_chain`,
    `to_address` the recipient on `to_chain`, and `tx_hash` the payout transaction."""
    index: int = Field(ge=1)
    from_address: str
    to_address: str
    from_chain: TraceChain | None = Field(None, description="null on cases stored before G4")
    to_chain: TraceChain | None = None
    bridge: Crossing | None = None
    tx_hash: str
    asset: str
    amount: float
    amount_usd: float | None = None
    traced_amount: float | None = Field(None, description="The part of `amount` that is the "
                                                           "suspect wallet's money")
    block_time: datetime
    elapsed_s: int | None = Field(None, description="Seconds since the previous hop")


class GraphNode(_M):
    id: str = Field(description=(
        "The address; for a wallet the money reached on another chain, `chain:address` "
        "(an EVM address is the same string on every EVM chain)"))
    address: str | None = Field(None, description=(
        "The plain address. null on cases stored before G4, where it equals id"))
    chain: TraceChain
    role: NodeRole
    hop: int = Field(ge=0, description="0 = the suspect wallet")
    label: LabelOut | None = None
    cluster: str | None = Field(None, description="VASP name when collapsible into one node")
    is_hub: bool = False


class GraphEdge(_M):
    id: str
    source: str
    target: str
    tx_hash: str
    asset: str
    amount: float
    amount_usd: float | None = None
    traced_amount: float | None = Field(None, description="The part of `amount` that is the "
                                                           "suspect wallet's money")
    block_time: datetime
    direction: Direction = "outbound"
    chain: TraceChain | None = Field(None, description=(
        "The chain tx_hash is on. null on cases stored before G4: the case's chain"))
    bridge: Crossing | None = Field(None, description=(
        "Set on a cross-chain edge: source is the bridge wallet, target the recipient on "
        "the destination chain, tx_hash the payout transaction"))


class CaseGraph(_M):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class EvidenceItem(_M):
    kind: EvidenceKind
    text: str = Field(description="Plain English, investigator's words")
    tier: Tier | None = None
    tx_hashes: list[str] = []
    weight: float | None = Field(None, description="Signed contribution (SHAP or rule)")


class RequestWallet(_M):
    address: str = Field(description=(
        "A labelled deposit address; or the unlabelled wallet that passed everything it "
        "got on to the VASP's wallet in paid_into; or the VASP's own labelled wallet"))
    amount: float = Field(description="Traced funds through this wallet, in `asset`")
    asset: str | None = Field(None, description=(
        "The asset that reached address. null on cases stored before G4: the case's asset. "
        "Over a bridge it can differ from the case's (USDT in, USDC out)"))
    paid_into: str | None = Field(None, description=(
        "Set when address carries no label: the VASP's labelled wallet it paid into"))
    tier: Tier = Field(description="Of the label that names the VASP")
    kind: Kind
    label: str | None = None
    chain: TraceChain | None = Field(None, description=(
        "The chain address is on, when the money reached it over a bridge. null: the "
        "case's chain"))
    reached_at: datetime = Field(description="When the traced funds first reached address")
    tx_hashes: list[str] = Field(description=(
        "The transfers that brought the funds to address and, for a pass-through wallet, "
        "on into the VASP's wallet; in time order"))


class Candidate(_M):
    vasp: str
    category: Category
    proximity_rank: int = Field(ge=1, description="1 = nearest; hops, share, time")
    confidence: float = Field(ge=0, le=1, description=(
        "Separate from proximity. Label weight x hop decay x share factor. The label weight "
        "is the deposit-address model's calibrated probability where confidence_interval is "
        "set; otherwise every factor is rule-set"))
    confidence_interval: tuple[float, float] | None = Field(None, description=(
        "Set when the money reached a model-scored deposit address: the model's calibrated "
        "range, carried through the same formula. null = rule confidence only"))
    direction: Direction = Field("outbound", description="outbound = the wallet's money went "
                                 "there; inbound = it funded the wallet")
    hops: int = Field(ge=0, description="0 = the wallet itself is a labelled VASP address")
    share_of_funds: float = Field(ge=0, le=1)
    time_to_reach_s: int | None = None
    label_tier: Tier
    deposit_address: str
    chain: TraceChain | None = Field(None, description=(
        "The chain deposit_address is on. null on cases stored before G4: the case's chain"))
    path: list[str] = Field(description="Addresses from the suspect to deposit_address")
    path_chains: list[TraceChain] | None = Field(None, description=(
        "The chain of each address in path"))
    evidence: list[EvidenceItem]
    counterfactual: str | None = Field(None, description=(
        "Named candidates only: what happens to this answer when the label on "
        "deposit_address (its strongest evidence) is hidden and the wallet is traced again"),
        examples=["Still CoinDCX without the label on TCw8j3…LLcoV5: 58% of the funds reach "
                  "CoinDCX at TU7BbA…vZbsFs (curated list) in 2 hops, confidence 0.72 "
                  "(was 0.85)."])
    counterfactual_holds: bool | None = Field(None, description=(
        "true: the same VASP is still named without that label. false: it falls under the "
        "bar or is not reached. null: not checked (the candidate was not named)"))
    # what a request to this VASP is built from (B8)
    amount: float | None = Field(None, description=(
        "In the case's asset: the traced funds that reached this VASP (exact; "
        "share_of_funds is rounded)"))
    request_wallets: list[RequestWallet] | None = Field(None, description=(
        "The wallets a request to this VASP lists, largest first; their amounts add up to "
        "`amount`. Empty for an inbound candidate and for the VASP's own wallet (hops 0). "
        "null in a case stored before B8: trace it again to route it to the desk"))


class TypologyFlag(_M):
    code: TypologyCode = Field(description=(
        "deposit_like is a lead from the deposit-address model on an unlabelled wallet "
        "(figures: p, low, high, share, amount); it never changes the outcome"))
    severity: Severity
    wallet: str
    chain: TraceChain | None = Field(None, description=(
        "The chain wallet is on. null: the case's chain"))
    text: str
    figures: dict[str, float] = {}
    tx_hashes: list[str] = []
    threat: ThreatTag | None = Field(None, description=(
        "The tag of the flagged address: always on threat_contact, and on a "
        "sanctioned_contact or mixer_contact whose address also carries one"))


class CaseInput(_M):
    """The question a case answers (everything else a trace depends on is code)."""
    address: str
    chain: str
    max_hops: int
    since: datetime | None = None
    max_wallets: int | None = Field(None, description=(
        "The wallet budget, present only when it was not the default of 40"))
    max_seconds: float | None = Field(None, description="The time budget, when one was set")
    stopped_after: list[int | None] | None = Field(None, description=(
        "When the time budget ended the trace: how many wallets it had asked for by then, "
        "[outbound, inbound]. `verify` replays the trace to exactly there"))

    @model_serializer(mode="wrap")
    def _only_a_changed_budget(self, handler):
        """A case traced with the default budget keeps the four-field input (and so the
        input digest) it has always had."""
        out = handler(self)
        for key in ("max_wallets", "max_seconds", "stopped_after"):
            if out.get(key) is None:
                out.pop(key, None)
        return out


class TraceBudget(_M):
    """What the trace was allowed to read and whether that, not the evidence, ended it."""
    max_wallets: int = Field(description="Wallets it may read per direction")
    max_hops: int
    max_seconds: float | None = None
    ended_by: Literal["wallets", "time"] | None = Field(None, description=(
        "Set when the budget stopped the walk; null when the evidence did"))
    ended_side: Literal["outbound", "inbound"] | None = None
    wallets_read: int = Field(description="Wallets read on the way out")
    share_not_followed: float = Field(ge=0, le=1, description=(
        "Share of the funds in wallets the budget left unread"))
    text: str = Field(description="One sentence to show as it is")


NotFollowedReason = Literal["small", "dust", "hub", "labelled", "depth_limit", "budget",
                            "unreadable", "other_chain"]


class NotFollowed(_M):
    """Wallets the trace did not follow, for one reason."""
    reason: NotFollowedReason = Field(description=(
        "small: holds under the share of the funds a trace follows; dust: only on transfers "
        "below the dust limit; hub: a high-activity wallet (commingled funds); labelled: a "
        "named party, where the trail ends by design; depth_limit: at the hop limit; budget: "
        "not read before the wallet or time budget ran out; unreadable: its transfers could "
        "not be read, or not to the end; other_chain: paid by a bridge on a chain no "
        "adapter reads"))
    count: int = Field(ge=1, description="How many wallets, all of them")
    wallet_ids: list[str] = Field(description=(
        "Their ids as in `graph.nodes` (a dust or other-chain wallet is not on the graph), "
        "sorted; at most 200 are listed"))
    text: str = Field(description="The count in words, to show as it is")


class TraceSummary(_M):
    """What the trace read and what it followed. Every figure is counted by the trace
    where it makes the decision; none is estimated afterwards."""
    transfers_seen: int = Field(ge=0, description=(
        "Every transfer in every listing the trace read, each once"))
    transfers_followed: int = Field(ge=0, description=(
        "Of those, the ones that carry the wallet's money: the transfers on the graph"))
    transfers_dust: int = Field(ge=0, description="Of those seen, dropped as below the dust limit")
    wallets_seen: int = Field(ge=0, description="Distinct wallets on any transfer seen")
    wallets_read: int = Field(ge=0, description="Wallets whose transfers were listed")
    wallets_followed: int = Field(ge=0, description=(
        "Wallets read and followed on, the case's own wallet included"))
    wallets_not_followed: int = Field(ge=0, description="The sum of `not_followed[].count`")
    not_followed: list[NotFollowed] = Field(description=(
        "Each wallet the money reached that was not followed, under exactly one reason; "
        "reasons with no wallet are left out"))
    text: str = Field(description="One line to show as it is")


class PageDigest(_M):
    query: str = Field(description="The chain API request, API keys removed")
    sha256: str = Field(description="SHA-256 of the response body as it was received")


class Provenance(_M):
    seed: int
    code_version: str
    label_db_sha256: str | None = None
    fetched_at: datetime | None = None
    offline_replay: bool = False
    data_sources: list[str] = []
    notes: list[str] = Field([], description="What this run did or could not do, e.g. how "
                             "many unlabelled wallets the deposit-address model scored")
    # the receipt (B9): null in a case stored before it existed
    input: CaseInput | None = None
    input_sha256: str | None = None
    responses: list[PageDigest] | None = Field(None, description=(
        "Every chain API response this run read, each once, sorted by request"))
    responses_sha256: str | None = Field(None, description="One digest over `responses`")
    pages: int | None = None
    findings_sha256: str | None = Field(None, description=(
        "The findings fingerprint: every figure, address and transaction hash of the "
        "result, none of its wording. `verify` must reproduce it"))
    content_sha256: str | None = Field(None, description=(
        "Digest of the whole result as stored, wording included: any edit to a stored case "
        "shows against it"))
    model_version: str | None = Field(None, description="Set when the deposit-address model "
                                      "scored a wallet in this run, e.g. model_v1/tron")
    model_sha256: str | None = None
    git_commit: str | None = None
    git_dirty: bool | None = Field(None, description="true: the code had uncommitted changes")
    budget: TraceBudget | None = Field(None, description=(
        "The trace budget and whether it ended the trace; null in a case stored before "
        "budgets could be changed"))


class FundsSlice(_M):
    """One part of the answer to "where did the wallet's money end up?"."""
    kind: FundsKind
    name: str | None = Field(None, description="The VASP or labelled party, when there is one")
    share: float = Field(ge=0, le=1)
    amount: float


class ProgressReached(_M):
    entity: str
    category: Category
    hop: int


class CaseProgress(_M):
    """What a trace that is still running has read so far. Counts only: a trace does not
    know how much is left, so there is no percentage."""
    phase: Literal["reading", "outbound", "inbound", "checking"] = Field(description=(
        "reading: the wallet's own transfers are being read. outbound: the money is being "
        "followed. inbound: the wallet's funders are being read. checking: the trace is "
        "done; each exchange that would be named is traced again without its label, and "
        "unlabelled wallets are scored"))
    asset: str | None = Field(None, description="The asset being followed, once chosen")
    hop: int = Field(description="How many hops out the trace has gone")
    wallets_read: int
    transfers_read: int
    reached: list[ProgressReached] = Field([], description=(
        "Labelled wallets the money has reached so far, each owner once, in the order "
        "found. Not a result: what is named is decided when the trace is done"))
    message: str = Field(description="The same, as one sentence to show as it is")


class RiskIndicator(_M):
    """One red-flag indicator that is present, with its points and what it rests on."""
    code: str
    name: str
    points: int = Field(ge=0, le=100)
    text: str = Field(description="The sentence to show as it is")
    fatf_category: str | None = Field(None, description=(
        "The category of the FATF red-flag report this indicator is filed under "
        "(config/risk.yaml); the filing is this project's"))
    wallet: str | None = None
    case_id: str | None = None
    tx_hashes: list[str] = []


class FlowRisk(_M):
    """The class of one traced transfer (an edge of the case's graph), by the indicators
    on it. Only transfers above Low are listed."""
    edge_id: str
    tx_hash: str
    risk_class: RiskClass
    reasons: list[str]


class RiskInfo(_M):
    score: int | None = Field(None, ge=0, le=100, description=(
        "The sum of the points of the indicators present, capped at 100. " + RISK_BASIS
        + " null: not assessed"))
    risk_class: RiskClass | None = Field(None, description=(
        "low 0-24, medium 25-49, high 50-74, severe 75-100 (config/risk.yaml). null: not "
        "assessed (a wallet that is unlabelled and in no case; a case with no result)"))
    indicators: list[RiskIndicator] = Field([], description="Largest first")
    reasons: list[str] = Field([], description="The indicators' sentences, in the same order")
    flows: list[FlowRisk] = Field([], description="A case only: its transfers above Low")
    path_class: RiskClass | None = Field(None, description=(
        "A case only: the class of the path the Hop Rail shows"))
    basis: str = RISK_BASIS
    source: str | None = Field(None, description="The published list the indicators follow")


class CaseDetail(CaseSummary):
    risk: RiskInfo | None = Field(None, description=(
        "Wallet and flow risk of a finished case. Worked out when the case is read from "
        "its stored flags, labels and transfers; never stored, so it is not part of the "
        "case's digests"))
    progress: CaseProgress | None = Field(None, description=(
        "Set only while status is queued or running and this server is tracing the case: "
        "poll the case to watch it. Never stored; null on a finished case"))
    asset: str | None = Field(None, description="The asset that was traced, e.g. USDT")
    total_sent: float | None = Field(None, description="What the wallet sent, in `asset`")
    total_received: float | None = None
    where_funds_went: list[FundsSlice] = Field([], description="Adds up to the whole of "
                                               "`total_sent`; largest first")
    chains: list[TraceChain] = Field([], description=(
        "The chains the traced money was followed on, in the order it crossed. One entry "
        "(the case's chain) unless a bridge deposit was followed"))
    crossings: list[Crossing] = Field([], description=(
        "Every bridge deposit the traced money made, followed or not, in time order"))
    tx_chains: dict[str, TraceChain] = Field({}, description=(
        "Transaction hash -> chain, for every transaction of this case that is not on the "
        "case's own chain (a payout, and the transfers after it)"))
    trace_summary: TraceSummary | None = Field(None, description=(
        "How much the trace saw, how much of it is on the graph, and why the other wallets "
        "were not followed. Null on a case with no result, and on one stored before this "
        "was counted"))
    hop_rail: list[Hop]
    graph: CaseGraph
    candidates: list[Candidate] = Field(description="Sorted by proximity_rank")
    typology_flags: list[TypologyFlag]
    narrative: str
    abstain_reason: str | None = Field(None, description="Set when INSUFFICIENT_EVIDENCE")
    what_would_change: list[str] = Field([], description="Evidence that would change "
                                                         "an abstain")
    next_steps: list[str] = []
    provenance: Provenance


class ContextNode(_M):
    id: str = Field(description="As in `graph.nodes`: the address, or `chain:address`")
    address: str
    chain: TraceChain
    on_graph: bool = Field(description="The wallet is one of the case's `graph.nodes`")
    label: LabelOut | None = None


class ContextEdge(_M):
    """One transfer the trace read and did not follow. Not the wallet's money."""
    id: str
    tx_hash: str
    source: str
    target: str
    asset: str
    amount: float
    amount_usd: float | None = None
    block_time: datetime
    chain: TraceChain
    why: Literal["dust", "other_asset", "not_traced"] = Field(description=(
        "dust: below the dust limit; other_asset: in an asset the trace did not follow; "
        "not_traced: none of the traced money was assigned to it (it left before the money "
        "arrived, or the money had already moved on)"))


class CaseContext(_M):
    """The transfers a case's trace read and did not follow: context to draw greyed
    beside the trail. It is never part of the attribution, the Hop Rail, a share of the
    funds or the risk class, and reading it changes nothing about the case."""
    case_id: str
    wallet: str | None = Field(None, description="Set when one wallet's context was asked for")
    recorded: bool = Field(description=(
        "False when `wallet` was not read by the trace and the server could not read it "
        "now (offline, or the chain refused): `reason` says which, and there are no edges"))
    live: bool = Field(False, description="The wallet's transfers were fetched for this answer")
    reason: str | None = None
    transfers: int = Field(ge=0, description="How many there are, cut or not")
    truncated: bool = Field(False, description="More than the limit: `edges` is the first part")
    nodes: list[ContextNode]
    edges: list[ContextEdge]
    text: str = Field(description="One line to show as it is")


# ------------------------------------------------------------------ wallets
class FlowSummary(_M):
    tx_count: int
    total_usd: float | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    top_counterparties: list[str] = []
    total: float | None = Field(None, description="In `asset`; null when the transfers "
                                                   "are in more than one asset")
    asset: str | None = None
    counterparties: int | None = None


class WalletCaseRef(_M):
    case_id: str
    role: NodeRole
    hop: int


class WalletDetail(_M):
    address: str
    chain: TraceChain
    labels: list[LabelOut]
    risk: RiskInfo
    cases: list[WalletCaseRef]
    inbound: FlowSummary | None = None
    outbound: FlowSummary | None = None
    flows_from_cases: int = Field(0, description=(
        "How many stored cases `inbound` and `outbound` were read from. They are the "
        "transfers those traces read, not the wallet's whole history"))
    watched: bool = False


# ------------------------------------------------------------------ desk / requests
class FollowUp(_M):
    kind: FollowUpKind
    vasp: str
    request_id: str
    due: date
    text: str


class DeskRow(_M):
    vasp: str
    category: Category
    wallet_count: int
    total_usd: float
    case_ids: list[str]
    status: RequestStatus | Literal["not_requested"]
    next_action: str
    last_request_id: str | None = None
    unrequested_wallets: int = Field(0, description=(
        "Routed wallets of this VASP that no request asks about yet"))


class Desk(_M):
    follow_ups: list[FollowUp]
    rows: list[DeskRow]


class DirectorySource(_M):
    field: str = Field(description="The directory field this source was read for")
    title: str
    publisher: str | None = None
    kind: Literal["official", "exchange", "news"] = Field("official", description=(
        "official: a government or regulator document. exchange: the exchange's own "
        "page. news: a press report. Show it: a self-reported fact is weaker"))
    url: str
    published: date | None = None
    accessed: date


class VaspDirectoryEntry(_M):
    """`data/vasp_directory.yaml`: only facts with a source. A blank field means no
    source was found, not "no"."""
    name: str
    legal_name: str | None = None
    fiu_ind_registered: bool | None = Field(None, description=(
        "true: a source states it is registered with FIU-IND. false: FIU-IND named it as "
        "operating unregistered. null: no usable source. Always show with fiu_ind_as_of"))
    fiu_ind_as_of: date | None = Field(None, description="The date that source speaks for")
    jurisdiction: str | None = None
    le_request_channel: str | None = Field(None, description=(
        "The exchange's own published channel for law-enforcement requests (URL or email)"))
    notes: list[str] = Field([], description="Cited remarks; show them verbatim")
    sources: list[DirectorySource] = []
    source_urls: list[str] = []


class VaspWallet(_M):
    address: str
    chain: str
    case_id: str | None = None
    direction: Direction = "outbound"
    amount_usd: float | None = None
    tier: Tier
    confidence: float | None = Field(None, ge=0, le=1)
    routable: bool = Field(True, description=(
        "false: shown for context only (under the bar, or the VASP funded the wallet); "
        "no request can be drafted on it"))


class StatusEvent(_M):
    status: RequestStatus
    at: datetime
    note: str | None = None
    by: str | None = Field(None, description="User name of the signed-in officer who made "
                                             "this change; null when no login was in force")
    via: Literal["sahyog"] | None = Field(None, description=(
        "sahyog: the exchange's reply arrived through the SAHYOG gateway, not typed in"))


class RequestSummary(_M):
    id: str
    reference: str
    vasp: str
    status: RequestStatus
    case_ids: list[str]
    created_at: datetime
    due: date | None = None


class VaspDetail(_M):
    directory: VaspDirectoryEntry
    label_counts: dict[str, int] = Field(description="Labelled wallets by chain")
    wallets: list[VaspWallet]
    requests: list[RequestSummary]


class RequestCreate(_M):
    vasp: str
    case_ids: list[str] = Field(min_length=1)
    wallets: list[str] | None = Field(None, description="Default: every wallet of this "
                                                        "VASP in the cases")
    asks: list[Ask] = Field(min_length=1)
    officer: str


class RequestPatch(_M):
    status: RequestStatus
    note: str | None = None


class LetterWallet(_M):
    address: str = Field(description="The wallet the VASP is asked about, in full")
    chain: str
    amount_usd: float | None = None
    tier: Tier = Field(description="Evidence tier of the label that names the VASP")
    first_seen: datetime | None = Field(None, description=(
        "When the traced funds first reached this wallet"))
    tx_hashes: list[str] = []
    case_id: str | None = None
    case_ref: str | None = None
    asset: str | None = None
    amount: float | None = Field(None, description="Traced funds, in `asset`")
    confidence: float | None = Field(None, ge=0, le=1)
    paid_into: str | None = Field(None, description=(
        "Set when `address` is not itself labelled: the VASP's labelled wallet it passed "
        "everything on to"))
    label: str | None = Field(None, description="The label text behind the attribution")


class LetterCase(_M):
    case_id: str
    case_ref: str | None = None
    complaint_no: str | None = None
    wallet: str = Field(description="The wallet under investigation")
    chain: str


class LegalCitation(_M):
    section: str
    act: str
    heading: str
    url: str


class RequestLetter(_M):
    reference: str
    date: date
    to: str
    subject: str
    paragraphs: list[str]
    wallets: list[LetterWallet]
    asks: list[Ask]
    legal_basis: str
    officer: str
    watermark: str | None = Field("Draft - officer review required",
                                  description="null once approved")
    cases: list[LetterCase] = []
    legal_citations: list[LegalCitation] = []
    channel: str | None = Field(None, description=(
        "The VASP's own published law-enforcement channel, from the directory"))
    review_notes: list[str] = Field([], description=(
        "For the reviewing officer, not part of the request: what to check before "
        "approving. Printed on the draft PDF only"))


class GatewayReceipt(_M):
    gateway: str = Field(description="`mock-outbox` until a real SAHYOG connection exists")
    receipt_id: str
    submitted_at: datetime
    location: str = Field(description="Where the submission went (the outbox file)")
    payload_sha256: str


class RequestDetail(RequestSummary):
    status_history: list[StatusEvent]
    letter: RequestLetter
    pdf_url: str
    payload: dict = Field(description="SAHYOG JSON payload (docs/sahyog_contract.md, B8)")
    allowed_next: list[RequestStatus] = Field([], description=(
        "The statuses a PATCH may move this request to now"))
    receipt: GatewayReceipt | None = Field(None, description="Set once sent")


class RequestList(_M):
    """The requests register: every request, newest first, withdrawn ones included."""
    items: list[RequestDetail]


# ------------------------------------------------------------------ dashboard / model
class DashboardCounts(_M):
    cases_total: int
    open_cases: int = Field(description=(
        "Cases being traced, plus cases with a wallet routed to an exchange that has not "
        "replied yet (or has not been asked)"))
    wallets_attributed: int = Field(description="Cases whose outcome is ATTRIBUTED")
    requests_awaiting_reply: int = Field(description="Requests sent or acknowledged")
    tracing: int = 0
    failed: int = 0
    awaiting_request: int = Field(0, description=(
        "Exchanges with a routed wallet that no request asks about yet"))
    watched: int = 0


class VaspCount(_M):
    vasp: str
    cases: int
    total_usd: float


class ChainCount(_M):
    chain: TraceChain
    cases: int


class Alert(_M):
    wallet: str
    chain: TraceChain
    severity: Severity
    text: str
    at: datetime
    case_id: str | None = None
    threat: ThreatTag | None = Field(None, description="Why the wallet is high-risk, when "
                                                       "the alert rests on a threat tag")


class LabelSource(_M):
    source: str
    name: str
    obtained_from: str | None = None
    licence: str | None = Field(None, description=(
        "The licence on record for the set these rows were obtained from; null = not "
        "recorded in this project (show 'Not recorded', never a guess)"))
    url: str | None = None
    labels: int
    tiers: dict[str, int]


class LabelCoverage(_M):
    total: int
    by_category: dict[str, int]
    by_tier: dict[str, int]
    by_chain: dict[str, int]
    by_source: list[LabelSource] = []
    by_threat: dict[str, int] = Field({}, description="Tagged labels per threat")
    traceable_total: int | None = Field(None, description=(
        "Labels on the chains a trace can run on today: the figure to show as a headline. "
        "`total` also counts labels on chains the tool cannot trace"))
    traceable_chains: list[str] = []


class Dashboard(_M):
    counts: DashboardCounts
    outcomes: dict[Outcome, int]
    top_vasps: list[VaspCount]
    chain_mix: list[ChainCount]
    median_time_to_attribution_s: float | None = Field(None, description=(
        "Median, over the cases that name an exchange, of the time the funds took to "
        "reach it (`time_to_reach_s` of the named candidate). null with no such case"))
    attribution_times_n: int = 0
    recent_alerts: list[Alert]
    label_coverage: LabelCoverage
    risk_classes: dict[RiskClass, int] = Field({}, description=(
        "Finished cases by risk class. " + RISK_BASIS))


# ------------------------------------------------------------------ watchlist (U4)
WatchState = Literal["not_traced", "checking", "unchanged", "changed", "failed"]


class WatchCreate(_M):
    address: str = Field(min_length=20, max_length=128)
    chain: TraceChain | None = None
    note: str | None = Field(None, max_length=200)


class WatchChange(_M):
    kind: Literal["new_activity", "new_exchange", "new_alert", "new_threat_link",
                  "risk_raised"] = Field(
        description="new_threat_link: a re-check found a link to a threat-tagged address "
                    "that the baseline did not have. risk_raised: the wallet's risk class "
                    "is higher than at the baseline")
    severity: Severity
    text: str
    at: datetime
    threat: ThreatTag | None = None


class WatchItem(_M):
    """A watched wallet, compared with its baseline: the trace it had when it was added
    or when its changes were last marked as seen."""
    id: str
    chain: TraceChain
    address: str
    note: str | None = None
    added_at: datetime
    added_by: str | None = None
    case_id: str | None = None
    state: WatchState
    last_checked_at: datetime | None = None
    baseline_at: datetime | None = None
    changes: list[WatchChange] = []
    error: str | None = None
    label: LabelOut | None = None
    risk_class: RiskClass | None = Field(None, description="Of the wallet's case as it is now")


class WatchList(_M):
    items: list[WatchItem]


class ReliabilityBin(_M):
    bin_mid: float
    observed: float
    count: int
    predicted: float | None = Field(None, description="Mean predicted probability in the bin")


class RiskCoveragePoint(_M):
    coverage: float
    accuracy: float


class FeatureImportance(_M):
    feature: str
    importance: float


class ModelMetrics(_M):
    pr_auc: float | None = None
    ece: float | None = None
    brier: float | None = None
    accuracy_when_answering: float | None = None
    coverage: float | None = None
    n_test: int | None = None


class ExchangeFold(_M):
    """One row of the leave-one-exchange-out table: the model never saw this exchange."""
    exchange: str
    n: int
    n_positive: int
    pr_auc: float | None = None
    roc_auc: float | None = None
    brier: float | None = None
    ece: float | None = None
    precision: float | None = Field(None, description="At probability 0.5")
    recall: float | None = Field(None, description="At probability 0.5")


class LookAlikes(_M):
    """The hard negatives: wallets that are not deposit addresses but forward as much."""
    forwarding_at_least: float
    negatives: int
    flagged: int = Field(description="How many of them the model calls a deposit address")
    false_positive_rate: float | None = None


class RuleBaseline(_M):
    """What one rule alone scores on the test addresses: the bar the model must clear."""
    rule: str
    precision: float | None = None
    recall: float | None = None
    accuracy: float | None = None


class AbstainBar(_M):
    """One candidate bar: what naming an exchange only at or above it does on the
    validation wallets."""
    threshold: float
    claims_answered: int = Field(description="Claims made through unlabelled wallets")
    claims_wrong: int
    wallets_named: int = Field(description="Wallets that get an exchange named at this bar")
    wallets_wrong: int
    wallets_abstained: int
    risk: float | None = Field(None, description="wallets_wrong / wallets_named")
    risk_upper_bound: float | None = Field(None, description=(
        "One-sided Clopper-Pearson bound on that risk, over wallets, corrected for the "
        "number of bars tried"))


class AbstainInfo(_M):
    """How the abstain bar was measured (B7): real exchange customers traced with the
    derived labels hidden. Not a calibration; read `notes`."""
    chain: str
    wallets: int
    claims: int = Field(description="Exchanges named through unlabelled wallets")
    current_threshold: float = Field(description="The bar the cases use")
    measured_threshold: float | None = Field(None, description=(
        "Lowest bar whose wallet-level risk bound stays under target_risk; null when no bar "
        "on the grid does"))
    target_risk: float
    delta: float
    bars: list[AbstainBar]
    risk_coverage: list[RiskCoveragePoint] = []
    notes: list[str] = []


class BenchmarkHops(_M):
    hops: int
    named: int
    wrong: int


class BenchmarkRow(_M):
    """One chain of the benchmark: real wallets that paid a labelled exchange address,
    traced again with the labels one hop away hidden."""
    chain: str
    measured: bool
    wallets: int | None = Field(None, description="Wallets traced (the sample size)")
    exchanges: int | None = None
    named: int | None = Field(None, description="Wallets the tool named an exchange for")
    wrong: int | None = None
    error: float | None = Field(None, description="wrong / named")
    error_upper_95: float | None = Field(None, description=(
        "One-sided 95% Clopper-Pearson bound on the error among the named"))
    not_named: int | None = Field(None, description="Wallets answered 'insufficient evidence'")
    by_hops: list[BenchmarkHops] = []
    baseline_named: int | None = Field(None, description=(
        "Named by the baseline: the nearest labelled exchange reached, never abstaining"))
    baseline_wrong: int | None = None
    baseline_error: float | None = None
    baseline_error_upper_95: float | None = None
    median_seconds: float | None = Field(None, description="Per trace, fetched live")
    median_requests: int | None = None
    calibration_brier: float | None = None
    confidence_informative: bool | None = None
    hidden: str | None = Field(None, description="Exactly which labels were hidden")


class ModelGate(_M):
    """Whether a chain's deposit-address model is used when tracing, and the held-out
    figures the fixed rule decided it by."""
    chain: str
    switch_on: bool
    because: str
    rule: str
    lead_bar: float
    reference_upper: float
    min_flagged: int
    held_out: int
    deposit_addresses: int
    flagged: int
    flagged_wrong: int
    error: float | None = None
    error_upper_95: float | None = None
    deposit_addresses_found: float | None = None


class BenchmarkInfo(_M):
    """Attribution measured on every chain beside a naive baseline (`make benchmark`)."""
    version: str
    seed: int
    bar: float
    chains: list[BenchmarkRow]
    notes: list[str] = []
    model_gates: list[ModelGate] = []


class RiskValidationView(_M):
    view: Literal["as_shown", "own_hidden", "entity_hidden"]
    words: str
    positives_scored: int
    positives_high_or_above: int
    positives_interval: list[float] | None = Field(None, description="95% Clopper-Pearson")
    positives_nothing_to_trace: int
    positives_classes: dict[str, int]
    controls_scored: int
    controls_high_or_above: int
    controls_interval: list[float] | None = None
    controls_nothing_to_trace: int
    controls_classes: dict[str, int]
    positives_high_with_list_link: int = Field(description=(
        "Of the listed wallets at High or above, those with a link to an address on a list"))
    rules_firing_more_on_positives: list[str] = Field(description=(
        "Pattern rules that fired on a larger share of the listed wallets (p < 0.05)"))
    p_fisher: float | None = Field(None, description="Fisher's exact test on the two shares")
    auc_score: float | None = Field(None, description=(
        "The chance a positive outscores a control, ties counting half"))
    auc_behaviour_score: float | None = Field(None, description=(
        "The same for the points of the behaviour indicators alone (no list is read)"))


class RiskRuleCheck(_M):
    code: str
    positive: int
    positive_of: int
    positive_share: float | None = None
    control: int
    control_of: int
    control_share: float | None = None
    p_fisher: float | None = None


class RiskValidation(_M):
    """The risk score measured on real wallets (`make risk-validation`). Show the notes."""
    version: str
    seed: int
    positives: int = Field(description="Wallets a public source lists as illicit")
    controls: int = Field(description="Wallets with a documented ordinary purpose")
    main_view: str = Field(description="The view to quote: the wallet's own label hidden")
    views: list[RiskValidationView]
    rules: list[RiskRuleCheck] = Field(description=(
        "Each pattern rule: the wallets it fired on, in the main view"))
    notes: list[str]


class ModelInfo(_M):
    status: Literal["not_measured", "measured"]
    version: str | None = None
    trained_at: datetime | None = None
    split: str | None = Field(None, description="e.g. 'by exchange and time'")
    metrics: ModelMetrics
    reliability: list[ReliabilityBin] = []
    risk_coverage: list[RiskCoveragePoint] = []
    feature_importance: list[FeatureImportance] = []
    leave_one_exchange_out: list[ExchangeFold] = []
    look_alikes: LookAlikes | None = None
    baseline: RuleBaseline | None = None
    chain: str | None = Field(None, description="The chain the model was trained on")
    notes: list[str] = []
    abstain: AbstainInfo | None = Field(None, description=(
        "How the bar below which no exchange is named was measured on this chain; null "
        "when it was not"))
    benchmark: BenchmarkInfo | None = Field(None, description=(
        "The benchmark table for every chain (the same whichever chain was asked for); "
        "null when `make benchmark` has not been run"))
    risk_validation: RiskValidation | None = Field(None, description=(
        "What the risk score and the pattern rules did on real listed and ordinary wallets "
        "(the same for every chain); null when it was not measured"))


# ------------------------------------------------------------------ receipt / verify (B9)
class Receipt(_M):
    """What a case was computed from, as digests anyone can recompute. The same document
    is the last page of the case file."""
    schema_: str = Field(alias="schema", description="vaspfusion-receipt/1")
    case_id: str
    case_ref: str | None = None
    outcome: Outcome
    top_vasp: str | None = None
    confidence: float | None = None
    created_at: datetime
    demo: bool = False
    seed: int
    code_version: str
    git_commit: str | None = None
    git_dirty: bool | None = None
    input: CaseInput
    input_sha256: str
    pages: int
    responses_sha256: str
    label_db_sha256: str | None = None
    model_version: str | None = None
    model_sha256: str | None = None
    findings_sha256: str
    content_sha256: str | None = None
    fetched_at: datetime | None = None
    offline_replay: bool = False
    data_sources: list[str] = []
    responses: list[PageDigest]
    receipt_sha256: str = Field(description="SHA-256 of every other field of this document")


VerifyOutcome = Literal["same", "different", "not_checked"]


class VerifyCheck(_M):
    name: Literal["stored_case", "replay", "responses", "findings", "content", "labels",
                  "model", "code"]
    result: VerifyOutcome
    detail: str = Field(description="Plain English")
    stored: str | None = None
    now: str | None = None


class VerifyResult(_M):
    """A stored case traced again from the cached chain responses only, and compared."""
    case_id: str
    matches: bool = Field(description=(
        "true only when the stored case still has its receipt's digests, the same "
        "responses were read, the new findings have the same fingerprint, and the new "
        "result has the same text (unless the code or the label database changed since)"))
    summary: str
    checked_at: datetime
    checks: list[VerifyCheck]


# ------------------------------------------------------------------ login / audit (B9)
class Login(_M):
    username: str = Field(max_length=200)
    password: str = Field(max_length=1000)


class OfficerOut(_M):
    username: str
    name: str
    post: str | None = None


class LoginResult(_M):
    token: str = Field(description="Send as `Authorization: Bearer <token>`. The same token "
                                   "is set as an HttpOnly session cookie")
    token_type: Literal["bearer"]
    expires_at: datetime
    officer: OfficerOut


class Me(_M):
    auth_required: bool = Field(description="false: no officer account exists (or login is "
                                            "switched off), so every route answers without one")
    officer: OfficerOut | None = None


class Ok(_M):
    ok: Literal[True]


AuditAction = Literal[
    "case.open", "case.list", "case.view", "case.export", "case.receipt", "case.verify",
    "case.context",
    "wallet.view", "label.search", "desk.view", "vasp.view", "request.draft", "request.view",
    "request.status", "request.export", "dashboard.view", "model.view", "fx.view", "audit.view",
    "watch.list", "watch.add", "watch.check", "watch.seen", "watch.remove", "label.coverage",
    "coverage.view", "sahyog.complaint", "sahyog.status", "sahyog.reply", "sim.view",
    "sim.complaint", "sim.reply",
    "batch.upload", "batch.list", "batch.view", "batch.export", "scale.view",
    "auth.login", "auth.logout", "api.other"]


class AuditEntry(_M):
    """One request to the API: who, what, on which case / wallet / exchange / request."""
    seq: int
    at: datetime
    officer: str | None = Field(None, description="User name; null = not signed in")
    action: AuditAction
    target: str | None = Field(None, description=(
        "case id, `chain:address`, exchange name, request id, search text or user name, "
        "by action"))
    method: str
    path: str
    status: int = Field(description="HTTP status of the reply (401 = refused, not signed in)")
    client: str | None = None
    detail: dict | None = None
    prev_hash: str
    hash: str = Field(description="SHA-256 over this row and prev_hash")


class AuditHead(_M):
    seq: int
    hash: str
    at: datetime | None = None


class ChainCheck(_M):
    ok: bool
    rows: int
    broken_at: int | None = None
    reason: str | None = None
    head: AuditHead


class AuditPage(_M):
    total: int
    limit: int
    offset: int
    items: list[AuditEntry] = Field(description="Newest first")
    chain: ChainCheck | None = Field(None, description="With `?verify=true`: every hash "
                                     "recomputed")


class FxRate(_M):
    """The one reference rate rupee amounts are shown at (config/fx.yaml). Never estimated."""
    rate: float = Field(gt=0, description="Rupees per 1 US dollar")
    as_of: date = Field(description="The day the rate is for")
    name: str = Field(description="What the rate is called on screen, e.g. 'RBI reference rate'")
    basis: str = Field(description="The sentence to show once per screen and in a PDF footer")
    source_title: str
    source_publisher: str | None = None
    source_url: str
    published: date | None = None
    accessed: date | None = None


class Health(_M):
    status: Literal["ok"]
    version: str
    label_db: bool
    data_mode: Literal["mock", "live", "mixed"]
    auth_required: bool = False
    offline: bool = Field(False, description="OFFLINE=1: chain data comes from the cache only")
    git_commit: str | None = None


# ------------------------------------------------------------------ SAHYOG, both directions (G2)
COMPLAINT_REF = r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$"
FraudCategory = Literal["investment_fraud", "job_fraud", "impersonation", "phishing",
                        "ransomware", "extortion", "loan_app", "other"]
ReplyStatus = Literal["acknowledged", "answered", "freeze_confirmed", "refused"]


class ComplaintWalletIn(_M):
    address: str = Field(min_length=1, max_length=128)
    chain: TraceChain | None = Field(None, description="Omit to have it read from the address")


class ComplaintCreate(_M):
    """A complaint as the portal would send it (docs/sahyog_contract.md)."""
    complaint_ref: str = Field(pattern=COMPLAINT_REF, description=(
        "The NCRP / 1930 acknowledgement number. Letters, digits, dot, dash, underscore"))
    agency: str = Field(min_length=1, max_length=200, description="The reporting agency")
    officer: str = Field(min_length=1, max_length=200)
    wallets: list[ComplaintWalletIn] = Field(min_length=1, max_length=50)
    amount_lost_inr: float | None = Field(None, ge=0)
    incident_date: date | None = None
    category: FraudCategory = Field("other", description=(
        "This project's own short list; the portal's categories would replace it"))
    note: str | None = Field(None, max_length=2000)
    callback_url: str | None = Field(None, max_length=500, description=(
        "Where the portal wants the result sent. Recorded and passed to the gateway; the "
        "mock gateway never calls it"))


class ExchangeNamed(_M):
    vasp: str
    direction: Direction
    proximity_rank: int
    hops: int
    confidence: float = Field(ge=0, le=1)


class ComplaintWallet(_M):
    address: str
    chain: TraceChain | None = None
    accepted: bool
    error: str | None = Field(None, description="Why the address was refused, as a sentence")
    case_id: str | None = None
    status: Literal["refused", "received", "tracing", "result", "failed"]
    outcome: Outcome | None = None
    top_vasp: str | None = None
    confidence: float | None = None
    exchanges: list[ExchangeNamed] = Field([], description=(
        "Every exchange the trace reached, nearest first, with proximity and confidence "
        "apart. Only `top_vasp` is named"))
    risk_class: RiskClass | None = None
    risk_score: int | None = Field(None, description=RISK_BASIS)
    report_pdf: str | None = Field(None, description="The case file, once there is a result")
    request_ids: list[str] = Field([], description="Requests drafted from this case")
    result_sent_at: datetime | None = Field(None, description=(
        "When the result was handed to the gateway"))
    case_error: str | None = None


class ComplaintStatus(_M):
    complaint_ref: str
    agency: str
    officer: str
    category: FraudCategory
    note: str | None = None
    amount_lost_inr: float | None = None
    incident_date: date | None = None
    callback_url: str | None = None
    received_at: datetime
    status: Literal["received", "tracing", "result"] = Field(description=(
        "received: nothing traced yet. tracing: at least one wallet is still queued or "
        "being traced. result: every accepted wallet has a result or has failed"))
    wallets: list[ComplaintWallet]
    status_url: str


class ReplyIn(_M):
    """An exchange's reply to a request, as it arrives through the gateway."""
    status: ReplyStatus
    note: str | None = Field(None, max_length=500)
    reply_ref: str | None = Field(None, max_length=100, description="The exchange's own reference")


class ReplyAck(_M):
    request_id: str
    status: RequestStatus
    recorded_at: datetime
    location: str | None = Field(None, description="Where the gateway kept the reply")


class SimRequest(_M):
    """A sent request as the portal's side would see it."""
    id: str
    reference: str
    vasp: str
    status: RequestStatus
    asks: list[Ask]
    wallets: int
    sent_at: datetime | None = None
    allowed_replies: list[ReplyStatus]
    last_note: str | None = None


class SahyogSim(_M):
    """Everything the simulator screen shows. A simulator for demonstration, not the
    SAHYOG portal."""
    enabled: bool = Field(description="false until an intake key exists (the demo set-up "
                                      "creates one)")
    notice: str
    why_disabled: str | None = None
    categories: list[str] = []
    complaints: list[ComplaintStatus] = Field([], description="Newest first")
    requests: list[SimRequest] = Field([], description="Newest first")


# ------------------------------------------------------------------ problem-statement coverage (G2)
CoverageStatus = Literal["built", "partly", "planned"]


class CoverageRow(_M):
    id: str
    section: str
    text: str = Field(description="The line of the problem statement, word for word")
    status: CoverageStatus
    what: str
    where: str = Field(description="A screen of the interface")
    evidence_kind: Literal["test", "make"]
    evidence: str
    gap: str | None = Field(None, description="What is missing; set unless status is built")
    computed: bool = Field(False, description="Worked out from the chains that trace today")


class PsCoverage(_M):
    rows: list[CoverageRow]
    counts: dict[CoverageStatus, int]
    total: int
    traceable_chains: list[str]
    source: str
