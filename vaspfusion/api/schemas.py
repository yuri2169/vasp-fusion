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
                       "round_amounts", "bridge_hop", "mixer_contact", "sanctioned_contact",
                       "deposit_like",
                       "coinjoin_shape"]   # Bitcoin: a pattern, never an alert (B5)
Severity = Literal["info", "warn", "high"]
EvidenceKind = Literal["label", "path", "sweep", "gas_payer", "model", "counterfactual"]
RequestStatus = Literal["drafted", "approved", "sent", "acknowledged", "answered",
                        "freeze_confirmed", "refused", "withdrawn"]
Ask = Literal["kyc", "transactions", "freeze", "preservation"]
FollowUpKind = Literal["reply_overdue", "freeze_lapsing", "preservation_closing"]
Direction = Literal["outbound", "inbound"]
FundsKind = Literal["vasp", "sanctioned", "mixer", "bridge", "other_label", "hub",
                    "beyond_hop_limit", "not_moved", "not_followed", "returned",
                    "fee"]   # Bitcoin only: miner fees paid along the trail (B5)


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


class RequestWallet(_M):
    address: str = Field(description=(
        "A labelled deposit address; or the unlabelled wallet that passed everything it "
        "got on to the VASP's wallet in paid_into; or the VASP's own labelled wallet"))
    amount: float = Field(description="Traced funds through this wallet, in the case's asset")
    paid_into: str | None = Field(None, description=(
        "Set when address carries no label: the VASP's labelled wallet it paid into"))
    tier: Tier = Field(description="Of the label that names the VASP")
    kind: Kind
    label: str | None = None
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
    path: list[str] = Field(description="Addresses from the suspect to deposit_address")
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
    text: str
    figures: dict[str, float] = {}
    tx_hashes: list[str] = []


class CaseInput(_M):
    """The question a case answers (everything else a trace depends on is code)."""
    address: str
    chain: str
    max_hops: int
    since: datetime | None = None


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


class CaseDetail(CaseSummary):
    progress: CaseProgress | None = Field(None, description=(
        "Set only while status is queued or running and this server is tracing the case: "
        "poll the case to watch it. Never stored; null on a finished case"))
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
    "wallet.view", "label.search", "desk.view", "vasp.view", "request.draft", "request.view",
    "request.status", "request.export", "dashboard.view", "model.view", "audit.view",
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


class Health(_M):
    status: Literal["ok"]
    version: str
    label_db: bool
    data_mode: Literal["mock", "live", "mixed"]
    auth_required: bool = False
    offline: bool = Field(False, description="OFFLINE=1: chain data comes from the cache only")
    git_commit: str | None = None
