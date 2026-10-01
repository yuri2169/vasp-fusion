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

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
                       "round_amounts", "bridge_hop", "mixer_contact", "sanctioned_contact"]
Severity = Literal["info", "warn", "high"]
EvidenceKind = Literal["label", "path", "sweep", "gas_payer", "model", "counterfactual"]
RequestStatus = Literal["drafted", "approved", "sent", "acknowledged", "answered",
                        "freeze_confirmed", "refused"]
Ask = Literal["kyc", "transactions", "freeze", "preservation"]
FollowUpKind = Literal["reply_overdue", "freeze_lapsing", "preservation_closing"]
Direction = Literal["outbound", "inbound"]
FundsKind = Literal["vasp", "sanctioned", "mixer", "bridge", "other_label", "hub",
                    "beyond_hop_limit", "not_moved", "not_followed", "returned"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ labels
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


class CaseList(_M):
    total: int
    items: list[CaseSummary]


class Hop(_M):
    """One step on the Hop Rail: money moved from `from_address` to `to_address`."""
    index: int = Field(ge=1)
    from_address: str
    to_address: str
    tx_hash: str
    asset: str
    amount: float
    amount_usd: float | None = None
    traced_amount: float | None = Field(None, description="The part of `amount` that is the "
                                                           "suspect wallet's money")
    block_time: datetime
    elapsed_s: int | None = Field(None, description="Seconds since the previous hop")


class GraphNode(_M):
    id: str = Field(description="The address")
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


class CaseGraph(_M):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class EvidenceItem(_M):
    kind: EvidenceKind
    text: str = Field(description="Plain English, investigator's words")
    tier: Tier | None = None
    tx_hashes: list[str] = []
    weight: float | None = Field(None, description="Signed contribution (SHAP or rule)")


class Candidate(_M):
    vasp: str
    category: Category
    proximity_rank: int = Field(ge=1, description="1 = nearest; hops, share, time")
    confidence: float = Field(ge=0, le=1, description="Calibrated; separate from proximity")
    confidence_interval: tuple[float, float] | None = None
    direction: Direction = Field("outbound", description="outbound = the wallet's money went "
                                 "there; inbound = it funded the wallet")
    hops: int = Field(ge=0, description="0 = the wallet itself is a labelled VASP address")
    share_of_funds: float = Field(ge=0, le=1)
    time_to_reach_s: int | None = None
    label_tier: Tier
    deposit_address: str
    path: list[str] = Field(description="Addresses from the suspect to deposit_address")
    evidence: list[EvidenceItem]
    counterfactual: str | None = Field(None, examples=["Still Binance if the sweep "
                                                       "evidence is removed"])


class TypologyFlag(_M):
    code: TypologyCode
    severity: Severity
    wallet: str
    text: str
    figures: dict[str, float] = {}
    tx_hashes: list[str] = []


class Provenance(_M):
    seed: int
    code_version: str
    label_db_sha256: str | None = None
    fetched_at: datetime | None = None
    offline_replay: bool = False
    data_sources: list[str] = []


class FundsSlice(_M):
    """One part of the answer to "where did the wallet's money end up?"."""
    kind: FundsKind
    name: str | None = Field(None, description="The VASP or labelled party, when there is one")
    share: float = Field(ge=0, le=1)
    amount: float


class CaseDetail(CaseSummary):
    asset: str | None = Field(None, description="The asset that was traced, e.g. USDT")
    total_sent: float | None = Field(None, description="What the wallet sent, in `asset`")
    total_received: float | None = None
    where_funds_went: list[FundsSlice] = Field([], description="Adds up to the whole of "
                                               "`total_sent`; largest first")
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


# ------------------------------------------------------------------ wallets
class FlowSummary(_M):
    tx_count: int
    total_usd: float | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    top_counterparties: list[str] = []


class RiskInfo(_M):
    score: float | None = Field(None, ge=0, le=1, description="null = not yet scored")
    reasons: list[str] = []


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


class Desk(_M):
    follow_ups: list[FollowUp]
    rows: list[DeskRow]


class VaspDirectoryEntry(_M):
    name: str
    legal_name: str | None = None
    fiu_ind_registered: bool | None = Field(None, description="Only if cited")
    jurisdiction: str | None = None
    le_request_channel: str | None = None
    source_urls: list[str] = []


class VaspWallet(_M):
    address: str
    chain: str
    case_id: str | None = None
    direction: Direction = "outbound"
    amount_usd: float | None = None
    tier: Tier
    confidence: float | None = Field(None, ge=0, le=1)


class StatusEvent(_M):
    status: RequestStatus
    at: datetime
    note: str | None = None


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
    address: str
    chain: str
    amount_usd: float | None = None
    tier: Tier
    first_seen: datetime | None = None
    tx_hashes: list[str] = []


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


class RequestDetail(RequestSummary):
    status_history: list[StatusEvent]
    letter: RequestLetter
    pdf_url: str
    payload: dict = Field(description="SAHYOG JSON payload (docs/sahyog_contract.md, B8)")


# ------------------------------------------------------------------ dashboard / model
class DashboardCounts(_M):
    cases_total: int
    open_cases: int
    wallets_attributed: int
    requests_awaiting_reply: int


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


class LabelCoverage(_M):
    total: int
    by_category: dict[str, int]
    by_tier: dict[str, int]
    by_chain: dict[str, int]


class Dashboard(_M):
    counts: DashboardCounts
    outcomes: dict[Outcome, int]
    top_vasps: list[VaspCount]
    chain_mix: list[ChainCount]
    median_time_to_attribution_s: float | None = None
    recent_alerts: list[Alert]
    label_coverage: LabelCoverage


class ReliabilityBin(_M):
    bin_mid: float
    observed: float
    count: int


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


class ModelInfo(_M):
    status: Literal["not_measured", "measured"]
    version: str | None = None
    trained_at: datetime | None = None
    split: str | None = Field(None, description="e.g. 'by exchange and time'")
    metrics: ModelMetrics
    reliability: list[ReliabilityBin] = []
    risk_coverage: list[RiskCoveragePoint] = []
    feature_importance: list[FeatureImportance] = []
    notes: list[str] = []


class Health(_M):
    status: Literal["ok"]
    version: str
    label_db: bool
    data_mode: Literal["mock", "live", "mixed"]
