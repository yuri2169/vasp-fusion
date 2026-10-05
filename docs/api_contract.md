# VASP-FUSION API contract

**Source of truth:** `vaspfusion/api/schemas.py` (Pydantic v2). The chain from there:

```
schemas.py ──(FastAPI)──▶ docs/openapi.json ──(openapi-typescript)──▶ ui/src/api/types.ts
     └──(validated by tests + make mocks)──▶ mocks/**/*.json
```

- Change a model in `schemas.py`, then run `make mocks types`. **Never hand-edit `types.ts`.**
- `tests/api/test_api.py` fails if `docs/openapi.json` drifts from the schemas, or if any mock stops validating.
- All models forbid extra fields. The top-level `_demo` / `_notice` keys in mock files are stripped before validation.

## Conventions
- Base path `/api`. JSON in and out. Times are ISO-8601 UTC (`Z`); dates are `YYYY-MM-DD`.
- **Every response carries `X-Data-Source`: `mock` | `live` | `mixed`.** The UI can show a "demo data" ribbon whenever it isn't `live`.
- **`VASPFUSION_DEMO_MODE` (U5).** Off, which is the default: every answer comes from the stores and is `live`. An empty store gives an empty answer (`/api/cases`, `/api/desk`, `/api/requests`, `/api/dashboard` with zero counts, `/api/model` with `status: "not_measured"`), an unknown id a 404 whose `detail` is a sentence, a missing label database a 503 on the label routes. Set to `1`, the fixtures in `mocks/` stand in as described below (the three `demo-…` cases, the fixture desk, dashboard, request and model); everything this document says about `mock` and `mixed` answers applies only then. `GET /api/health` reports `data_mode: "live"` or `"mixed"`.
- Errors come back as `{"detail": "<plain-English sentence saying what happened and what to do>"}`. Codes used: 401 (not signed in, when a login is required), 404 (unknown id), 409 (not allowed now), 422 (bad input; `detail` is a string for our own checks, and a list for Pydantic validation errors), 403 (cross-origin write refused), 429 (account locked), 503 (label database missing, or the audit log could not be written).
- Addresses are returned exactly as stored. EVM addresses are lowercase; Tron and BTC keep their case.
- **Proximity and confidence are separate fields and are never blended.** `proximity_rank` (1 = nearest: hops, share of funds, time) and `confidence` (0–1; rule-based in B3, calibrated from B6).
- Outcomes: `ATTRIBUTED` · `INSUFFICIENT_EVIDENCE` (then `abstain_reason` + `what_would_change` are set, and `top_vasp` is null) · `SANCTIONED_OR_MIXER_REACHED`.
- Label tiers, strongest first: `published_por` (exchange's own proof-of-reserves list) › `curated` (OFAC, cex-list, MEW scam list, Dune spellbook, operator statements) › `explorer_tag` (Etherscan-style tags) › `derived` (inferred by VASP-FUSION, e.g. B4 sweep/gas-payer). UI names: *Published by exchange*, *Curated list*, *Explorer tag*, *Derived by VASP-FUSION*.
- Categories: `exchange`, `custodial_wallet`, `swap_service` (all three are VASPs), plus `sanctioned`, `scam`, `mixer`, `bridge`, `defi`, `entity`.
- An `entity` of `Unidentified exchange` means the source tags the address as an exchange but names no owner. It counts as a VASP hit, but no request can be routed to it.

## Endpoints

| Method | Path | Request | Response model | Mock file | Status | Owner |
|---|---|---|---|---|---|---|
| GET | `/api/health` | – | `Health` (now with `auth_required`, `offline`, `git_commit`) | – | live, never needs a login | B1/B9 |
| POST | `/api/auth/login` | `Login` | `LoginResult` (+ session cookie) | – | **live** | B9 |
| POST | `/api/auth/logout` | – | `Ok` | – | **live** | B9 |
| GET | `/api/auth/me` | – | `Me` | `auth/me.json` | **live**, never needs a login | B9 |
| GET | `/api/audit?limit=&offset=&officer=&action=&target=&verify=` | – | `AuditPage` | `audit.json` | **live** | B9 |
| POST | `/api/cases?refresh=` | `CaseCreate` | `CaseSummary` (202) | returns a mock demo case if the address is one of theirs | **live** | B3 |
| GET | `/api/cases?outcome=&status=` | – | `CaseList` | `cases.json` (listed after the live cases) | **live** + mock | B3 |
| GET | `/api/cases/{id}` | – | `CaseDetail` (with `progress` while it is being traced) | `cases/{id}.json` (only for the mock ids) | **live** | B3 (B4, B7 fill evidence/flags; U2 progress) |
| GET | `/api/cases/{id}/pdf` (also `/api/cases/{id}.pdf`) | – | `application/pdf` | the mock case, marked "Demo fixture - not evidence" | **live** | B9 |
| GET | `/api/cases/{id}/receipt` | – | `Receipt` | `cases/{id}/receipt.json` | **live** | B9 |
| POST | `/api/cases/{id}/verify` | – | `VerifyResult` | 422 for a mock id | **live** | B9 |
| GET | `/api/wallets/{chain}/{address}` | – | `WalletDetail` | `wallets/{chain}/{address}.json` (a demo wallet, until a real case reads it) | **live** | B3/B6/U4 |
| GET | `/api/labels/search?q=&chain=&category=&tier=&limit=&offset=` | – | `LabelSearch` | `labels/search.json` (fallback) | **live** | B1 |
| GET | `/api/desk` | – | `Desk` | `desk.json` (until a finished case names an exchange) | **live** | B8 |
| GET | `/api/vasps/{name}` | – | `VaspDetail` | `vasps/{name}.json` (only while no live case or request touches it) | **live** | B8 |
| POST | `/api/requests` | `RequestCreate` | `RequestDetail` (201) | the demo request, if every case id is a mock demo id | **live** | B8 |
| GET | `/api/requests?vasp=&status=` | – | `RequestList` (`items: RequestDetail[]`, newest first, withdrawn ones included) | `requests.json` (only while the desk itself is the mock) | **live** | U3 |
| GET | `/api/requests/{id}` | – | `RequestDetail` (letter JSON + `pdf_url`) | `requests/{id}.json` (only for the mock id) | **live** | B8 |
| PATCH | `/api/requests/{id}` | `RequestPatch` | `RequestDetail` | applied to the mock, not persisted (mock id only) | **live** | B8 |
| GET | `/api/requests/{id}/pdf` (also `/api/requests/{id}.pdf`) | – | `application/pdf` | the mock request, marked "Demo fixture - not evidence" | **live** | B8 |
| GET | `/api/dashboard` | – | `Dashboard` | `dashboard.json` (only while no case is stored) | **live** | U4 |
| GET | `/api/labels/coverage` | – | `LabelCoverage` | `labels/coverage.json` (fallback) | **live** | U4 |
| GET | `/api/watchlist` | – | `WatchList` | `watchlist.json` (empty) | **live** | U4 |
| POST | `/api/watchlist` | `WatchCreate` | `WatchItem` (201) | – | **live** | U4 |
| POST | `/api/watchlist/{id}/check` | – | `WatchItem` (202) | – | **live** | U4 |
| POST | `/api/watchlist/{id}/seen` | – | `WatchItem` | – | **live** | U4 |
| DELETE | `/api/watchlist/{id}` | – | `Ok` | – | **live** | U4 |
| GET | `/api/fx` | – | `FxRate` | – | **live** from `config/fx.yaml` (the same answer in demo mode) | U7 |
| GET | `/api/model` | `?chain=tron` (default) or `ethereum` | `ModelInfo` | `model.json` (the measured Tron model) | **live** from `artifacts/model_v1/<chain>/metrics.json` | B6 |
| GET | `/api/coverage` | – | `PsCoverage` | `coverage.json` | **live** | G2 |
| POST | `/api/sahyog/complaints` | `ComplaintCreate` + `X-SAHYOG-Key` | `ComplaintStatus` (202) | – | **live**; its own API key, no officer login (`docs/sahyog_contract.md`) | G2 |
| GET | `/api/sahyog/complaints/{complaint_ref}` | `X-SAHYOG-Key` | `ComplaintStatus` | – | **live** | G2 |
| POST | `/api/sahyog/requests/{request_id}/replies` | `ReplyIn` + `X-SAHYOG-Key` | `ReplyAck` | – | **live** | G2 |
| GET | `/api/sahyog-sim` | – | `SahyogSim` | `sahyog-sim.json` | **live**; the simulator screen, behind the officer login | G2 |
| POST | `/api/sahyog-sim/complaints` | `ComplaintCreate` | `ComplaintStatus` (202) | – | **live**; the same intake | G2 |
| POST | `/api/sahyog-sim/requests/{request_id}/reply` | `ReplyIn` | `ReplyAck` | – | **live**; the same reply leg | G2 |

### Cases are live (B3)
- `POST /api/cases` validates the address (base58check / EIP-55 / bech32), stores the case as `queued`, answers 202 at once, then traces in the background: `queued → running → done | failed`. **Poll `GET /api/cases/{id}`** until the status is `done` or `failed`. A real trace takes about 1–10 s live, and well under a second from the cache.
- `chain` is optional: Tron, Bitcoin and Solana addresses are unambiguous, and an EVM address is taken as `ethereum` unless the officer picks another chain. EVM addresses are stored lowercase.
- 422 with a plain-English `detail` when: the chain can't be told from the address; the address is not valid on the chosen chain; or the chain can't be traced yet (traceable today: tron, bitcoin, solana, ethereum, bsc, polygon, arbitrum, base, optimism; `bsc` needs `ANKR_API_KEY` and `solana` needs `HELIUS_API_KEY` on the server for a live trace, and without it the case ends `failed` with a sentence naming the key).
- Posting a wallet that already has a finished case returns that case (same `id`, no second trace), **even if `max_hops` or `incident_date` differ: send `?refresh=true` to trace again.** A `failed` case, and one left `queued`/`running` by a server restart, is always run again.
- During a refresh the case keeps showing the previous result with status `queued`/`running`. If the refresh fails, the previous result stays, status goes back to `done`, and `error` says "Refresh failed (…)". The case reference, complaint number and amount are kept unless the refresh sends new ones.
- A `failed` case has `error` set (for example `CacheMiss: OFFLINE=1 and not cached: …`) and empty lists.
- `max_hops` (1–5, default 3) is the outbound depth. `incident_date`, when given, limits the trace to the wallet's transfers from that day on.
- Case ids are `c-` + 10 hex characters (stable per chain + address). The three mock cases keep their `demo-…` ids and are listed after the live ones; the list's `X-Data-Source` is `mixed` once a live case exists.
- **Real demo cases:** `make demo` runs the six wallets in `demo/cases.json` into the store with ids `tron-coindcx`, `eth-bitget`, `tron-ofac`, `tron-htx-coindcx`, `tron-abstain`, `eth-abstain` and `demo: true`.

### Fields added in B3 (all optional, so the mocks are unchanged)
- `CaseSummary.error`.
- `CaseDetail.asset`, `total_sent`, `total_received`: what was traced, in the traced asset.
- `CaseDetail.where_funds_went: FundsSlice[]` (`kind`, `name`, `share`, `amount`), largest first, adding up to the whole of `total_sent`. Kinds: `vasp`, `sanctioned`, `mixer`, `bridge`, `other_label`, `hub`, `beyond_hop_limit`, `not_moved`, `not_followed`, `returned`. Meant for a single stacked bar: "where did the money end up?".
- `Candidate.direction`: `outbound` (the wallet's money went there) or `inbound` (that VASP funded the wallet). Inbound candidates rank after outbound ones and never decide the outcome.
- `Candidate.hops` may be `0`: the wallet itself is a labelled VASP address.
- `Hop.traced_amount` and `GraphEdge.traced_amount`: the part of the on-chain `amount` that is the suspect wallet's money (a transfer of 11,000 may carry 5,800 of it).

### What B3 fills, and what waits
- `confidence` is **rule-based, not calibrated**, and `confidence_interval` and `counterfactual` are `null` until B6/B7. Show it as "rule confidence".
- `top_vasp` is the nearest candidate (lowest `proximity_rank`) whose confidence is 0.60 or more. It can differ from the highest-confidence candidate; both numbers are on every candidate.
- `deposit_address` is the labelled address the money entered the VASP by. On Tron that is usually a hot wallet; the customer's own deposit address is the hop before it (`path[-2]`), named in the evidence and the next steps. B4 turns that into a `derived` label.
- `evidence` kinds used: `label`, `path`. `typology_flags` codes used: `sanctioned_contact`, `mixer_contact`, `bridge_hop`. The rest arrive with B4 and B7.
- `where_funds_went` kind `not_followed` covers money in wallets the trace could not read to the end (more transfers than one fetch returns), parts under 1%, and wallets past the trace budget. `not_moved` is only used when the wallet's listing was read whole.
- Node roles: an unlabelled wallet the trace walked through is `intermediary`; one it did not expand is `unknown`; `hub` is a high-activity wallet where the trail stops. A node seen both as a funder and as a destination appears once.

### Derived deposit addresses (B4)
- A label with `tier: "derived"` is a deposit address found by VASP-FUSION's own rules (`make discover`), never by an outside source. Its `kind` is `deposit`, its `source` is `vaspfusion-discover`.
- Two fields were added to every label (`LabelOut`), both `null` unless the tier is `derived`:
  - `confidence`: the **rule confidence** of the discovery rules, 0 to 1. Not calibrated. Show it as "rule confidence", like a case's.
  - `evidence`: one plain-English paragraph of what the two rules saw (share forwarded, number of senders and sweeps, typical delay, who paid the gas, whether the rules agree). Show it verbatim under the label.
- In a case, a derived deposit address is where the trace stops, so `Candidate.deposit_address` is now the customer's own deposit address when one is known, `Candidate.label_tier` is `derived`, and the first `evidence` item carries the same paragraph. Its weight in the case confidence is the label's own `confidence` (not the flat 0.60 the tier had before).
- `label_coverage.by_tier` on the dashboard now has a `derived` count.
- Conflicts (the two rules name different exchanges, or the address already has another label) are kept in `derived/<run>.csv` with `status: conflict`. They are not labels and the API does not serve them yet.

### The deposit-address model (B6)
All additive; `make mocks types` has been run.
- **What the model is.** LightGBM on 14 behaviour features of one address (how much it forwards, to how many wallets, how fast, who pays its fees, whether the wallet it pays most forwards everything on). It answers "is this an exchange deposit address?" and reads no label. Its probability is calibrated with Venn-Abers, which also gives a range. On Tron the truth it was trained and measured on is the discovery rules' verdict; `?chain=ethereum` is the same model family measured on explorer tags.
- **Labels (`LabelOut`).** A derived label the model scored has three more fields; they are `null` on every other label:
  - `model: ModelScore`: what the model said about the address. `p`, `low`, `high` (its calibrated probability that an address behaving like this is an exchange deposit address, and the range), `basis` (`model` or `rule`, see below), `scored_by`, and `reasons: ModelReason[]`, strongest first. Each reason has `feature` (a stable key), `text` (plain English, e.g. "forwards 100% of what it receives to one wallet") and `weight` (SHAP, in log-odds: above 0 speaks for a deposit address, below 0 against).
  - `confidence_low`, `confidence_high`: the range of the label's `confidence`. Set only when `model.basis` is `model`.
  - **`basis: "model"`** (5,249 of the 5,497 derived labels): the model confirms the label. `confidence` is `weight of the exchange wallet's label × model.p`. Show it as "confidence 0.85" with its range.
  - **`basis: "rule"`** (248): the model's value would be lower than what the discovery rules gave, so B4's rule confidence is kept and there is no range. Show it as "rule confidence", and show `model.p` next to it as the model's own view. The model reads behaviour only and cannot see the sweep into a labelled exchange wallet, so it never lowers a label.
  - `evidence` ends with the model's sentence in both cases.
  - Never print a probability as 1.00: `model.p` can round to it. The backend writes "over 0.99" and "range narrower than 0.01" in its own texts.
- **Cases (`Candidate`).**
  - `confidence_interval: [low, high]` is set when the money reached a model-scored deposit address; `null` otherwise. **`null` means "rule confidence", a range means the label behind it was scored by the model.**
  - `evidence` gains items of `kind: "model"` right after the label item: first the model's probability and range (`weight: null`), then one per reason. There `weight` is the signed SHAP value and `text` starts "Deposit-address model, for: …" or "…, against: …". Draw the reasons as signed bars.
  - The narrative says "confidence 0.83 (range 0.80 to 0.85)" for such a case, and still says "rule confidence … (rule-based, not calibrated)" for the others.
  - Only the model's probability is calibrated. The weight of the exchange wallet's label (0.95 published by the exchange, 0.85 curated), the hop decay (0.85 per hop) and the share factor are still rule-set, so a case confidence is not a calibrated probability end to end. Say so wherever the number is shown.
- **`GET /api/model`** is live (`X-Data-Source: live`): `status: "measured"`, `version`, `trained_at`, `chain`, `split`, and
  - `metrics`: PR-AUC, ECE, Brier and `n_test` on the latest 20% of addresses; `coverage` and `accuracy_when_answering` are the share of addresses the model is sure about (probability at least 0.9 either way) and how often it is right on those.
  - `reliability[]`: `bin_mid`, `predicted`, `observed`, `count` (plot `observed` against `predicted`, with the diagonal).
  - `risk_coverage[]`: accuracy when only the surest share (`coverage`) of addresses is answered.
  - `feature_importance[]`: `feature` is already a plain-English name; `importance` sums to 1.
  - `leave_one_exchange_out[]`: one row per exchange the model never saw (`exchange`, `n`, `n_positive`, `pr_auc`, `roc_auc`, `brier`, `ece`, `precision`, `recall`).
  - `baseline`: what the single rule "forwards 90% or more to one wallet" scores on the same test addresses (`rule`, `precision`, `recall`, `accuracy`). Show it next to the model's figures: it is the bar, not chance.
  - `look_alikes`: the hard negatives, i.e. wallets that are not deposit addresses but forward as much (`negatives`, `flagged`, `false_positive_rate`).
  - `notes[]`: sentences that say what the numbers are and are not. Show them; they are part of the result.
- Ready-made plots (SVG, light and dark): `artifacts/model_v1/<chain>/reliability.svg`, `reliability_by_exchange.svg`, `reliability_labels.svg`, `importance.svg`.

### Flags, counterfactual, leads, the abstain bar (B7)
All additive; `make mocks types` has been run. `provenance.code_version` is `b7-decide-1`.
- **Ranking (unchanged, now final).** `candidates[]` is sorted by `proximity_rank` (hops, then share of the funds, then time). `confidence` is its own number. Show both; never merge them. `top_vasp` is the nearest candidate at or above the bar, not the most confident one.
- **`typology_flags[]`** now carries every code. Each flag has `wallet`, `text`, `tx_hashes` (always from the case's graph) and `figures`:

  | code | severity | figures | raised when |
  |---|---|---|---|
  | `sanctioned_contact`, `mixer_contact` | high | `share`, `amount`, `hops` | traced money reached (or the wallet was funded by) such a label |
  | `bridge_hop` | warn | `share`, `amount`, `hops` | traced money reached a bridge label |
  | `peel_chain` | warn | `wallets`, `amount`, `peeled` | 2+ consecutive wallets each sent 70%+ on to one wallet and the rest to others |
  | `rapid_forwarding` | warn | `share`, `amount`, `seconds` | an unlabelled wallet passed on 90%+ of what reached it, each part within 10 minutes |
  | `fan_out` | info | `recipients`, `amount`, `hours` | one wallet paid the money to 5+ wallets inside 24 hours |
  | `fan_in` | info | `senders`, `amount` | the wallet was funded by 5+ senders, or split money merged again at one wallet (3+ senders) |
  | `round_amounts` | info | `round_transfers`, `transfers`, `amount` | 3+ and at least half of the wallet's stablecoin payments are whole hundreds |

  `rapid_forwarding` times each part from the oldest arrival it drew on; `peel_chain` needs two peeling wallets after the traced wallet.
  | **`deposit_like`** (new code) | info | `p`, `low`, `high`, `transfers_read`, `share`, `amount` | a lead, see below |

  Flags read the traced money only. None of them decides the outcome, except that money at a sanctioned or mixer label sets `SANCTIONED_OR_MIXER_REACHED` (as since B3). Order: severity, then the table's order, then share and amount.
- **Counterfactual (`Candidate`).** For every named candidate (outbound, at or above the bar) the label on its `deposit_address` is hidden and the wallet is traced again:
  - `counterfactual`: the sentence, e.g. "Still CoinDCX without the label on TCw8j3…LLcoV5: 58% of the funds reach CoinDCX at TU7BbA…vZbsFs (curated list) in 2 hops, confidence 0.72 (was 0.85)."
  - `counterfactual_holds` (new): `true` the same VASP is still named; `false` it falls under the bar or is not reached ("rests on that one label"); `null` not checked: the candidate was not named, is inbound, is an exchange tag with no owner, or (with a sentence starting "Not checked:") the second trace could not follow the money behind the hidden label.
  - `evidence` ends with an item of `kind: "counterfactual"`; its `weight` is the change in confidence (negative), its `tx_hashes` the path of the second trace.
  - A tick or a warning next to the confidence is enough; the sentence is the tooltip.
- **Leads (`deposit_like`).** On Tron, up to five unlabelled wallets that received 5% or more of the funds (hubs excluded) are scored by the deposit-address model. At 0.90 or more the case gets a `deposit_like` flag: "behaves like an exchange deposit address … Neither it nor <collector>, the wallet it sweeps into, is labelled, so the exchange cannot be named. A lead to check, not a finding …".
  - **A lead never changes `outcome`, `candidates` or any confidence.** Show it apart from the answer, as something to look into.
  - `what_would_change` (abstain) and `next_steps` gain "A label for <collector> …" / "Identify <collector> …". When the collector is a labelled exchange wallet the text says "it may be a deposit address of <exchange> that the discovery rules have not derived". A wallet that pays a bridge, a mixer or any other named non-exchange is not a lead.
  - Ethereum wallets are not scored (the model did not carry over to unseen exchanges there).
  - `provenance.notes[]` (new) says how many wallets were scored, or why none were.
- **Bridges.** A bridge label stops the trace, the node's `role` is `bridge`, it is never a candidate, `where_funds_went` has a `bridge` slice, and `next_steps` says to follow the funds on the destination chain and lists the bridge transactions. Demo case `eth-bridge` shows it.
- **`GET /api/model` gains `abstain`** (`null` when not measured for that chain): how the 0.60 bar was checked on real wallets.
  - `wallets`, `claims`, `current_threshold`, `measured_threshold` (lowest bar that keeps the risk under `target_risk` with confidence 1 − `delta`; `null` if none does), `bars[]` (per candidate bar: `wallets_named`, `wallets_wrong`, `wallets_abstained`, `risk` = wrong / named, `risk_upper_bound` over wallets, and `claims_answered`, `claims_wrong`), `risk_coverage[]` (`coverage`, `accuracy`), `notes[]`.
  - **It is a label hold-out, not a calibration.** Show `notes`; they say how the set was built and what it does not measure.
  - Plot: `artifacts/abstain_v1/tron/risk_coverage.svg`.
- The demo set has a 7th wallet, `eth-bridge`.

## Key shapes (see `types.ts` for every field)

**`CaseDetail`** = `CaseSummary` plus:
- `hop_rail: Hop[]`: the path to the top candidate, one ticket stub per hop (`from_address → to_address`, `amount`, `asset`, `amount_usd`, `block_time`, `elapsed_s`).
- `graph: {nodes: GraphNode[], edges: GraphEdge[]}`
  - nodes: `role` (`suspect` · `intermediary` · `exchange_hot` · `exchange_deposit` · `exchange` · `custodial_wallet` · `swap_service` · `bridge` · `mixer` · `sanctioned` · `hub` · `unknown`), `hop`, `label` (a `LabelOut` with `tier`), and `cluster` (the VASP name; collapse nodes that share it).
  - edges: `tx_hash`, `amount`, `amount_usd`, `block_time`.
- `candidates: Candidate[]`, sorted by `proximity_rank`. Each has `vasp`, `category`, `confidence` + `confidence_interval`, `hops`, `share_of_funds`, `time_to_reach_s`, `label_tier`, `deposit_address`, `path`, `evidence: EvidenceItem[]` (`kind`: label/path/sweep/gas_payer/model/counterfactual; `text`; `tier`; `tx_hashes`; signed `weight`), and `counterfactual`.
- `typology_flags: TypologyFlag[]`: `code` (peel_chain, fan_out, fan_in, rapid_forwarding, round_amounts, bridge_hop, mixer_contact, sanctioned_contact), `severity`, `wallet`, `text`, `figures`, `tx_hashes`.
- `narrative`, `abstain_reason`, `what_would_change[]`, `next_steps[]`, `provenance` (seed, code version, label DB hash, offline replay flag, data sources).

**`RequestDetail`**: `status` (drafted → approved → sent → acknowledged → answered | freeze_confirmed | refused; or withdrawn), `status_history[]`, `allowed_next[]`, `letter` (reference, date, to, subject, numbered `paragraphs`, `cases`, `wallets` table with tier, `asks` (kyc, transactions, freeze, preservation), `legal_basis` + `legal_citations` (§94 BNSS 2023 notice; §63 BSA 2023 certificate; §106 BNSS when a freeze is asked), `officer`, `channel`, `review_notes`, `watermark` (the draft watermark text; null once approved)), `pdf_url`, `receipt` (once sent) and `payload` (the SAHYOG JSON, specified in `docs/sahyog_contract.md`). See "The request desk is live (B8)".

### The request desk is live (B8)
The unit of work is an exchange, not a complaint. Everything is read from finished cases in the case store; no route here touches a chain.

- **Which wallets reach the desk.** For each finished case, every candidate that is outbound, at least one hop away, at or above the bar (0.60) and names an owner. Never: a candidate under the bar, an inbound one ("this exchange funded the wallet"), the exchange's own wallet (hops 0: ask it directly), an `Unidentified exchange`. So `tron-abstain` gives no row.
- **`Candidate.request_wallets[]`** (new, with `Candidate.amount`, the exact sum): the wallets a request to that exchange lists, **each with its own amount**; together they add up to `amount`. One row is `address`, `amount`, `paid_into`, `tier`, `kind`, `label`, `reached_at`, `tx_hashes[]`. A row names a labelled deposit address; or the unlabelled wallet that passed on everything it got to the exchange's wallet in `paid_into`; or else the exchange's own labelled wallet. It is `null` in a case stored before B8: **such a case is not routed until it is traced again** (`POST /api/cases?refresh=true`); the VASP page still shows it, as `routable: false`.
- **`Desk.rows[]`**, one per exchange, largest sum first: `wallet_count`, `total_usd` (US-dollar stablecoins only; other assets add 0), `case_ids`, `status` (of the newest request that is not withdrawn, or `not_requested`), `next_action` (a sentence), `last_request_id`, and **`unrequested_wallets`** (new): routed wallets no request asks about yet. When it is above 0 and a request exists, `next_action` says "Draft a request for N wallets not yet requested". Two label spellings of one exchange ("Coinswitch", "CoinSwitch") are one row, under the directory's name.
- **`Desk.follow_ups[]`**: only `reply_overdue` is produced, from the day after `due` while the request is `sent` or `acknowledged`. `due` is set when a request is sent: 7 days later (`DeskConfig.reply_days`, an office reminder, not a period set by law). `freeze_lapsing` and `preservation_closing` stay in the enum but are never produced: no period we could cite fixes them.
- **`VaspDetail.directory`** (`data/vasp_directory.yaml`, cited facts only): `legal_name`, `fiu_ind_registered` (true / false / null), **`fiu_ind_as_of`** (always show it with the registration: "registered, as of 4 Dec 2023"), `jurisdiction`, `le_request_channel`, **`notes[]`** (show verbatim), **`sources[]`** (`field`, `title`, `publisher`, **`kind`**: `official` | `exchange` | `news`, `url`, `published`, `accessed`: link each fact to its source, and show when a registration is only the exchange's own statement), `source_urls[]`. **null means "no source found", never "no".** An exchange the file does not list comes back with only its name.
- **`VaspDetail.wallets[]`**: every case wallet that touches the exchange, with **`routable`** (new). `routable: false` rows are context (under the bar, the exchange's own wallet, the exchange funded the wallet, or a case from before B8): show them, but offer no "draft request" on them. An inbound row has no `amount_usd`.
- **`POST /api/requests`** drafts one consolidated request: `vasp` (name or alias, any case), `case_ids`, `asks`, `officer` (Latin letters), optional `wallets` (addresses). Without `wallets` it takes every routed wallet of that exchange in those cases **that no open request asks about yet**. 201 with the request in status `drafted`. Errors come as a sentence in `detail`: **404** unknown case, **409** case still tracing, or the wallets are already asked about (the sentence names the request), **422** the case does not support a request to that exchange (with the reason: under the bar, only funded the wallet, the exchange's own wallet, not reached, no named owner, unknown wallet, a case from before B8).
- **`GET /api/requests`** (added in U3, for the register) lists every request, newest first, each as `GET /api/requests/{id}` gives it; `vasp` (name or alias) and `status` narrow it. With no live request it answers the demo request only while `GET /api/desk` is itself the mock; once a finished case names an exchange it answers `{"items": []}`.
- **`PATCH /api/requests/{id}`** moves it: `drafted → approved → sent → acknowledged → answered | freeze_confirmed | refused`. Also `approved → drafted` (send it back), `answered → freeze_confirmed`, and **`drafted | approved → withdrawn`** (new status: a draft made by mistake; its wallets can be drafted again, and so can the wallets of a `refused` request). **`allowed_next[]`** on every request says which statuses the buttons may offer now. A step that is not allowed is **409**. A draft cannot be sent: it has to be approved first.
  - `approved` and `sent` first check that every wallet in the letter is still what its case says. If a case was traced again with a different result, or removed, the step is **409** ("Withdraw this request and draft a new one").
  - `approved` clears `letter.watermark` and sets `payload.draft` to false.
  - `sent` hands the payload and the letter PDF to the gateway (a local outbox: nothing leaves the machine), sets `due`, fills **`receipt`** (`gateway`, `receipt_id`, `submitted_at`, `location`, `payload_sha256`) and `payload.documents[0].sha256` (the letter's SHA-256). **502** if the gateway fails; the request stays `approved` and can be sent again.
- **The letter** (`RequestDetail.letter`) is fixed when drafted. New fields: `cases[]` (`case_id`, `case_ref`, `complaint_no`, `wallet`, `chain`), `legal_citations[]` (`section`, `act`, `heading`, `url`), `channel`, and **`review_notes[]`**: what the officer should check before approving (an unlabelled wallet named because it passed everything on; the exchange's own wallet rather than a customer's; a naming that rests on one label; a label derived by our own rules; how the FIU-IND registration is known and as of when; no channel or legal name on file). Show them beside the letter, not in it. Each `LetterWallet` also has `case_id`, `case_ref`, `asset`, `amount`, `confidence`, `paid_into`, `label`. Addresses and hashes in a letter are always in full.
- **`GET /api/requests/{id}/pdf`** (or `.pdf`): A4, `Content-Disposition: inline`. A draft carries a banner on every page, a diagonal watermark and a last sheet of review notes; an approved letter has none of them. The same request always gives the same bytes, and once sent the bytes served are the ones that were submitted.
- The mock demo request follows the same rules: `POST` with a demo case answers only for the exchange that demo case names (else 422), and `PATCH` on it refuses a step that is not allowed (409).
- CLI: `make desk`, `make letter VASP=CoinDCX OFFICER="…" [CASES=a,b] [SEND=1]`.

### Case file, receipt, login, audit (B9)
All additive. `make mocks types` has been run; the three mock cases now carry the receipt fields too.

**The receipt.** `CaseDetail.provenance` gained (all null in a case stored before B9: trace it again):
- `input` (`address`, `chain`, `max_hops`, `since`) and `input_sha256`: the question asked.
- `responses[]` (`query`, `sha256`): every chain API response the run read, each once, API keys removed; `responses_sha256` is one digest over the list; `pages` is its length.
- `findings_sha256`: **the findings fingerprint**. It covers every figure, address, time and transaction hash of the result (outcome, candidates, confidences, shares, the wallets and their labels, every transfer with its time, the evidence hashes and weights, the wallets a request would list, the flags) and none of the wording. Floats are rounded to six places before hashing.
- `content_sha256`: the whole result as stored, wording included (narrative, evidence sentences, next steps). Any edit to a stored case shows against it.
- **Neither digest covers** `case_ref`, `complaint_no`, `amount_lost_inr`, `created_at`, `demo`, `status`: those are the officer's entries and the case's state, not findings. The digests are not keyed: what makes a case checkable is `verify`, which computes it again.
- `model_version` / `model_sha256` (set only when the deposit-address model scored a wallet in the run), `git_commit`, `git_dirty`, beside the existing `label_db_sha256`, `seed`, `code_version`.
- `GET /api/cases/{id}/receipt` gives the same as one document (`schema: "vaspfusion-receipt/1"`) with the headline (`outcome`, `top_vasp`, `confidence`) and `receipt_sha256` over all of it. **409** while the case has no result or carries no receipt.

**Verify.** `POST /api/cases/{id}/verify` traces the wallet again **from the cached chain responses only** (it never fetches, whatever `OFFLINE` says) and answers `VerifyResult`: `matches`, a one-line `summary`, and `checks[]`, each `name`, `result` (`same` | `different` | `not_checked`), `detail` (a sentence), `stored`, `now`.
- `matches` is true only when these checks are `same`: `stored_case` (the stored case still has its own fingerprint and content digest, and its receipt agrees with itself: nobody edited it), `responses` (the same pages, byte for byte), `findings` (the new run has the same fingerprint).
- `content`: whether the new run gives the same text too. A difference fails the check, **unless** `code` or `labels` is `different`: then the wording may honestly differ, and the sentence says so.
- `labels`, `model` and `code` are reported beside them. A changed label database is the usual reason for `findings` to differ; it is shown, and it does not by itself fail the check.
- A page missing from the cache gives one `replay` check with `not_checked`, and `matches: false`.
- Takes about as long as the trace did from cache (a second or two). Show a tick, or the sentence in `summary`.
- CLI: `python -m vaspfusion.cli verify <id>` / `--all` / `--receipt file.json` (exit 1 on a mismatch).

**The case file.** `GET /api/cases/{id}/pdf` (or `.pdf`): A4, `Content-Disposition: inline; filename="case-<id>.pdf"`. Sections: result, summary, where the funds went, flow diagram with a numbered wallet table, exchanges reached (each with its evidence and full transaction hashes), the path, patterns, leads, how the confidence was worked out (what is calibrated and what is not, and how the 0.60 bar was checked), what would change it, next steps, limitations, and the receipt with every response digest. **The same case always gives the same bytes.** Every page's footer carries the fingerprint. **409** until the case is `done`. A demo wallet's file opens with a notice that it alleges nothing; a mock fixture is watermarked. CLI: `make case-pdf CASE=<id>` writes `data/exports/case-<id>.pdf` and `.receipt.json`.

**Login.**
- **A login is required once an officer account exists** (`python -m vaspfusion.cli officer add <user> --name "Insp. A. Rao"`; a disabled account still counts, so disabling the last officer does not open the tool), or when `VASPFUSION_AUTH=required`. With no account every route answers as before. `VASPFUSION_AUTH=off` switches it off. **`GET /api/auth/me`** (always open) says which: `{"auth_required": true|false, "officer": {username, name, post} | null}`. Start there: show the sign-in screen when `auth_required` is true and `officer` is null.
- `POST /api/auth/login` `{username, password}` → `{token, token_type: "bearer", expires_at, officer}` and sets the cookie `vf_session` (HttpOnly, SameSite=Strict, Path=/api, 8 hours). **Either works on later requests**: the cookie (nothing to do in a same-origin UI, and a PDF opened in a new tab is signed in too) or `Authorization: Bearer <token>`.
- **401** `{"detail": "Sign in to continue."}` on every `/api` route except `health`, `auth/me`, `auth/login`, `auth/logout` when not signed in: send the user to the sign-in screen. Login itself answers **401** "Wrong user name or password." (the same words for both) and **429** while a user name is locked (five wrong passwords, five minutes; a name with no account locks the same way).
- `POST /api/auth/logout` clears the cookie. A token already handed out stays valid until it expires or its account is disabled.
- `RequestDetail.status_history[].by` (new): the user name of the signed-in officer who drafted, approved or sent it; absent when no login was in force. `RequestCreate.officer` is still the name printed on the letter.

**Audit.** Every `/api` request except `health` and `auth/me` leaves one row, signed in or not (a refused request is a row with status 401). `GET /api/audit` → `AuditPage`: `total`, `items[]` newest first, and with `?verify=true` a `chain` block (`ok`, `rows`, `broken_at`, `reason`, `head`).
- `AuditEntry`: `seq`, `at`, `officer` (null = not signed in), `action`, `target`, `method`, `path`, `status`, `client`, `detail`, `prev_hash`, `hash`.
- Actions and their targets: `case.open` / `case.view` / `case.export` / `case.receipt` / `case.verify` (the case id; `case.open` also has `detail.address`, `detail.chain`), `case.list`, `wallet.view` (`chain:address`), `label.search` (the search text), `desk.view`, `vasp.view` (the name), `request.draft` (the request id; `detail.vasp`, `detail.cases`), `request.view`, `request.status` (`detail.status`), `request.export`, `dashboard.view`, `model.view`, `audit.view`, `auth.login` (the user name when it is an account's, else `(unknown user name)`: a password typed into the wrong box is never logged), `auth.logout`, `api.other`.
- **For a case page's Audit tab: `GET /api/audit?target=<case id>`.** `?action=case` matches the whole family, `?action=case.view` one action.
- The same read by the same officer from the same address with the same result within 30 seconds is one row (a page polling a running trace); writes are never folded. A request body is never logged. A request that breaks the server is a row with status 500, and the reply is `{"detail": "The server could not answer this request. It has been logged."}`.
- Rows are hash-chained: `hash` is an HMAC-SHA256, under the audit key, of the row and `prev_hash`. An edited, removed or reordered row breaks the chain from there, and `chain.broken_at` names it; without the key the log cannot be rewritten and rehashed. The key is `VASPFUSION_AUDIT_KEY`, or a file beside the log. Whoever holds both the log and the key can rewrite it, and rows cut off the end leave a valid chain: both are only caught against a `head` noted somewhere else.
- Every `/api` reply carries `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.

### Progress of a running trace (U2)
Additive; `make mocks types` has been run (the mocks did not change).
- **`CaseDetail.progress`** (`CaseProgress | null`): what the trace has read so far. Set only while `status` is `queued` or `running` **and this server is tracing the case**; `null` on a finished or failed case, on a case that is still waiting to start, and on one left `running` by a restart. Poll `GET /api/cases/{id}` (the interface asks twice a second) to watch it.
  - `phase`: `reading` (the wallet's own transfers) → `outbound` (the money is being followed) → `inbound` (who funded the wallet) → `checking` (the trace is done: each exchange that would be named is traced again without its label, and unlabelled wallets are scored; on a wallet with leads this is the longest part).
  - `asset` (the asset being followed, once chosen), `hop` (how many hops out so far), `wallets_read`, `transfers_read` (transfers returned by the listings read; they only grow).
  - `reached[]`: `entity`, `category`, `hop` of the labelled wallets the money has reached, each owner once, in the order found. **It is not a result**: which exchange is named, if any, is decided when the trace is done.
  - `message`: the same as one sentence, to show as it is, e.g. "Following the money on Tron: 320 USDT transfers of 10 wallets read, 2 hops out. Reached so far: CoinDCX."
- There is no percentage: a trace does not know how much is left.
- **Progress is never stored and is in no digest** (`provenance.NOT_CONTENT`): a stored case is a result. It lives in the server process, like the list of cases being traced, so one server process is assumed, as everywhere else. A case traced before this field existed verifies as before.
- During a refresh the case keeps showing the previous result with `status` `queued`/`running`, and `progress` beside it.
- There is still no route to cancel a trace.
- Also fixed with it: a refresh (`POST /api/cases?refresh=true`) of a demo wallet's case keeps `demo: true` (it was reset to false).
- In code: `trace(..., on_progress=)` and `run_case(..., on_progress=)` take a callback and call it with each snapshot; it changes nothing about the result, and a callback that fails does not fail the trace. `vaspfusion/explain/progress.py` writes the sentence.

### Dashboard, wallet page, label sources, watchlist (U4)
Everything here is counted from stored records (cases, requests, labels, the watchlist). Nothing reads a chain except a watchlist check, which is a trace.

- **`GET /api/dashboard`** is live once the case store holds a case (`X-Data-Source: live`); with none it answers the demo fixture with live label counts (`mixed`). Mock demo cases are never counted.
  - `counts.cases_total`; `counts.tracing` (queued or running), `counts.failed`; `counts.wallets_attributed` = cases whose outcome is ATTRIBUTED; `counts.requests_awaiting_reply` = requests sent or acknowledged; `counts.awaiting_request` = exchanges on the desk with a routed wallet in no request; `counts.watched`.
  - `counts.open_cases` = cases being traced, plus cases with a wallet routed to an exchange whose newest request is not answered, freeze-confirmed or refused (or that has not been asked). A case that names no exchange is not open: there is nobody to write to.
  - `outcomes`: all three keys, over finished cases. `chain_mix`: every stored case. `top_vasps`: the desk's rows (`cases`, `total_usd` in US-dollar stablecoins; other assets add 0).
  - `median_time_to_attribution_s`: the median, over the `attribution_times_n` cases that name an exchange, of `time_to_reach_s` of the named candidate: how long the funds took to reach the exchange's address, on the chain. 0 means the wallet paid that address directly. It is not how long a trace takes. null with no such case.
  - `recent_alerts` (12 at most, newest first): one per high-severity flag of a finished case (`text` is "Case <ref>: " and the flag's own sentence), and one per change of a watched wallet (`text` starts "Watched wallet: ", `severity` high for a new alert, warn for a new exchange, info for new transfers).
- **`GET /api/wallets/{chain}/{address}`**:
  - `inbound` / `outbound` (`FlowSummary`: `tx_count`, `total` in `asset` or null when the transfers are in several assets, `total_usd`, `first_seen`, `last_seen`, `counterparties`, `top_counterparties` by amount): **the transfers of this address that the stored finished cases read**, each counted once. `flows_from_cases` says how many cases that is. It is not the wallet's history; say so beside it.
  - `risk` (`RiskInfo`): see "Risk, SAHYOG and coverage (G2)". `risk.risk_class` is null for an address that is unlabelled and in no finished case (not assessed).
  - `watched`: whether the address is on the watchlist.
- **`LabelCoverage.by_source[]`** (on the dashboard and at `GET /api/labels/coverage`): `source` (a family: the first named source of a merged row; every `graphsense-tagpack:*` pack is one family), `name`, `obtained_from`, `licence`, `url`, `labels`, `tiers`. The rows add up to `total`. **`licence` is what this project has on record** (`vaspfusion/labels/sources.py`): GraphSense TagPacks are MIT; OFAC SDN is US-government public record; the wallet-attribution set releases its code under MIT and leaves each upstream source's data under that source's own licence, which is not recorded here, so those read null. Show null as "Not recorded".
- **The watchlist.** A watched wallet has a **baseline**: a snapshot of its case (the wallet's own transfers, the exchanges among its candidates, its high-severity flags) taken when it was added, or when its changes were last marked as seen. A wallet added before it had a finished case takes its first finished trace as the baseline.
  - `WatchItem.state`: `not_traced`, `checking` (its case is queued or running), `unchanged`, `changed`, `failed` (the last trace failed; `error` has the sentence). `changes[]` (`kind`: `new_alert` | `new_exchange` | `new_activity`; `severity`; `text`; `at`) is what the case shows now that the baseline did not.
  - `POST /api/watchlist` `{address, chain?, note?}`: 201; **409** already watched; **422** as `POST /api/cases` (not an address, chain not traceable). `id` is `<chain>-<address>`.
  - `POST /api/watchlist/{id}/check` traces the wallet again exactly as `POST /api/cases?refresh=true` does (same hop limit as its last trace) and answers 202 with the item `checking`. **Poll `GET /api/watchlist`** (the interface asks once a second while an item is checking). Nothing checks a wallet in the background.
  - `POST /api/watchlist/{id}/seen` makes the current trace the baseline (409 with no finished trace). `DELETE /api/watchlist/{id}` stops watching.
  - Stored in `data/watch.duckdb` (`VASPFUSION_WATCH_DB`). Audit actions: `watch.list`, `watch.add`, `watch.check`, `watch.seen`, `watch.remove`, `label.coverage`.

### Bitcoin (B5)
`POST /api/cases` accepts a Bitcoin address (the chain is detected; bech32 is stored lowercase). The case has the same shape as any other. What is different, all additive:
- **`where_funds_went[].kind` has a new value, `fee`**: miner fees paid along the trail (Bitcoin only). Show it as its own small slice ("network fees"); the slices still add up to the whole.
- **A label with `source: "vaspfusion-cluster"`** (`tier: "derived"`, `kind: "unknown"`, `confidence` set, `model` null): the address has no label of its own and was spent in one transaction together with a labelled address of that exchange. `evidence` is the paragraph to show verbatim ("cluster of N addresses, M labelled …", the labelled address in full, the transaction with both among its inputs). `Candidate.confidence_interval` is null: call it "rule confidence". The graph node's role is `exchange` (the exchange controls it; whether it is a customer's deposit address is not known), and `request_wallets[]` names that address itself.
- **`TypologyCode` has a new value, `coinjoin_shape`** (severity `warn`): traced money entered, or the wallet was paid out of, a transaction with the shape of a CoinJoin. Figures: `share`, `amount`, `hops`; `tx_hashes` are the transactions. It is a pattern, not an alert: it never sets the outcome, and the text says "a rule, not a proof". `mixer_contact` is still only raised by a labelled mixer.
- **Every graph node is an address.** Money that went into a transaction it cannot be followed through (several funders and several destinations; a CoinJoin shape; an output with no address form) stops at the wallet that spent it and is in `where_funds_went` as `not_followed`; `abstain_reason` and `what_would_change` say which. Nothing new to render.
- `asset` is `BTC` and every `amount_usd` is null (no price feed). `time_to_reach_s` is 0 for a one-hop route.
- `provenance.data_sources` names the backend (`blockstream.info`).
- An edge's `amount` is the wallet's share of a transaction output, so it can be smaller than the output on a block explorer when several addresses funded the transaction (a sweep into one address); `tx_hash` is the transaction.
- Leads (`deposit_like`) are not produced on Bitcoin; `provenance.notes[]` says so when there were wallets to score. What the cluster step could not settle ("two owners in one cluster", "spent together with a sanctioned address", "could not be read") is a sentence in `narrative`.
- A new live demo case: **`btc-htx`** (eight demo cases now).

**`ModelInfo`**: `status: "measured"` once `make model` has run (see "The deposit-address model (B6)"). With no `metrics.json` for the chain the route answers `status: "not_measured"`: every metric is null and the lists are empty, and the UI shows "not yet measured". Every number is measured; there are no placeholders.

### Rupees beside dollars (U7)
- `GET /api/fx` returns the one USD→INR reference rate in `config/fx.yaml`: `rate` (rupees per dollar), `as_of`, `name`, the `source_*` fields, and `basis`, the sentence shown once per screen and in every PDF footer ("₹ at 1 USD = ₹95.79, RBI reference rate, 18 Sep 2026"). The rate is read from the file and is never estimated; a file without a date or a source is refused when it is read.
- No amount field changed. Rupee amounts are computed where they are shown (`usd × rate`, rounded to the rupee, Indian digit grouping), from fields that are already US dollars: `amount_usd`, `total_usd`, and amounts in the dollar stablecoins.
- The request letter and the case file print the rupee amount beside each dollar amount and the basis in the footer.

### BNB Chain and Solana (G1)
No schema changed: `bsc` and `solana` were already in the chain enum, and a case on them has the same shape as any other.
- `POST /api/cases` and `POST /api/watchlist` accept both. A Solana address is unambiguous; an EVM address is `bsc` only when the officer picks it.
- Solana addresses are case-sensitive and stored as given. `Candidate.deposit_address`, graph nodes and hops hold the **owning wallet**, never a token account. `asset` is `USDT`, `USDC` or `SOL`.
- On BNB Chain USDT and USDC have 18 decimals; amounts are already in whole units, as everywhere.
- **Confidence on chains without a measured model.** The deposit-address model scores Tron only, and the naming bar was measured on Tron only (`GET /api/model?chain=tron`, `abstain`). On every other chain `confidence_interval` is null (show "rule confidence"), `provenance.notes[]` says unlabelled wallets were not scored, and the case file says "The bar has not been measured on this chain." A client must not show the Tron error figures under a case on another chain: check `abstain.chain`.
- Three more recorded demo cases (eleven now): **`bnb-coindcx`**, **`sol-okx`**, **`polygon-bitget`**.

### Threat tags and high-risk alerts (G3)
All additive.
- **`Threat`**: `terrorism_financing`, `ransomware`, `darknet_market`, `fraud`, `sanctioned_other`. **`ThreatTag`**: `{threat, entity, source, url, evidence}`: what a public source says, in its own words. Show `evidence` as written.
- **`LabelOut`** gains `threat`, `threat_entity`, `threat_source`, `threat_url`, `threat_evidence` (all null on an untagged label). `category` is unchanged and still drives the outcome.
- **`TypologyCode` has a new value, `threat_contact`** (severity `high`): traced money reached, or the wallet was funded by, or the wallet is, a tagged address whose category raises no alert of its own. **`TypologyFlag.threat`** is the tag; it is also set on a `sanctioned_contact` or `mixer_contact` whose address carries one, and the sentence then ends "; tagged terrorism financing (ISIL KHORASAN, OFAC SDN list)". Figures as the other label flags: `share`, `amount`, `hops`.
- **`CaseSummary.screening`** `{hit, text, tag}`: the check of the case's own address, present from the answer to `POST /api/cases` on (before the trace runs). **`CaseSummary.threats`**: the distinct threats the case touches. `GET /api/cases?threat=<threat>|any`.
- **`GET /api/labels/search?threat=<threat>|any`**, and **`LabelCoverage.by_threat`**.
- **`Alert.threat`** on the dashboard; **`WatchChange.kind: "new_threat_link"`** (high) with `threat`, when a re-check finds a link to a tagged address that the baseline did not have. A baseline taken before this change reports no link as new.
- `WalletDetail.risk`: a tag on the address's label makes the level `high`; the first reason is the tag with its evidence.
- A new live demo case: **`tron-terror-link`** (twelve demo cases now).


### Risk, SAHYOG and coverage (G2)

All additive, except that **`RiskInfo.level` is gone** (it was a three-step rule; `risk_class` replaces it).

- **Risk** (`vaspfusion/risk.py`, `config/risk.yaml`). **An indicator score from published red-flag rules. Not a probability, and not measured against known outcomes.** Show that sentence (`risk.basis`) wherever the score is shown.
  - `RiskInfo`: `score` (0 to 100: the sum of the points of the indicators present, capped), `risk_class` (`low` 0-24, `medium` 25-49, `high` 50-74, `severe` 75-100), `indicators[]` (`code`, `name`, `points`, `text`, `fatf_category`, `wallet`, `case_id`, `tx_hashes[]`; largest first; one entry per indicator however often it is seen), `reasons[]` (the same sentences), `basis`, `source`. On a case also `flows[]` (`edge_id`, `tx_hash`, `risk_class`, `reasons[]`: **only the transfers above Low**; a transfer not listed is Low) and `path_class` (the path the Hop Rail shows).
  - `CaseDetail.risk`, `CaseSummary.risk_class` and `risk_score`: set on a finished case, null otherwise. **Worked out when the case is read**, from its stored flags, labels and slices; never stored, so not part of `content_sha256` or the findings fingerprint. Changing `config/risk.yaml` changes every case's score at once.
  - `WalletDetail.risk`: the address's own label, the pattern flags that name it in any stored case, and, where it is the wallet a case traced, that case's indicators.
  - `Dashboard.risk_classes`: finished cases by class (all four keys). `WatchItem.risk_class`; a watched wallet whose class is higher than at its baseline has a change of kind `risk_raised` (severity high for High or Severe, else warn).
  - Indicators: sanctioned (itself, contact, funding), mixer (itself, contact, funding), CoinJoin shape, scam list (itself, contact), bridge, swap service, peel chain, forwarding within minutes, fan-out, fan-in, round amounts, most funds stopping at an unlabelled busy wallet. A sanctioned or mixer contact alone is Severe; its points grow with the share of the funds and shrink with the distance. The list follows FATF, "Virtual Assets - Red Flag Indicators of Money Laundering and Terrorist Financing" (September 2020); the filing under its categories and the points are this project's (`config/risk.yaml` says how the reference was checked).
- **SAHYOG, both directions**: `POST /api/sahyog/complaints`, `GET /api/sahyog/complaints/{ref}`, `POST /api/sahyog/requests/{id}/replies` (API key, not an officer's session) and the simulator's `GET /api/sahyog-sim`, `POST /api/sahyog-sim/complaints`, `POST /api/sahyog-sim/requests/{id}/reply`. Specified in `docs/sahyog_contract.md`. `CaseSummary.sahyog_complaint_ref` is set on a case a complaint reported. `StatusEvent.via` is `sahyog` for a reply that arrived through the gateway.
- **`GET /api/coverage`** → `PsCoverage`: `rows[]` (`id`, `section`, `text` = the line of the problem statement word for word, `status` built / partly / planned, `what`, `where` = a screen, `evidence_kind` test / make, `evidence`, `gap`, `computed`), `counts`, `total`, `traceable_chains`, `source`. From `data/ps_coverage.yaml`; a row with `computed` is worked out from the chains that trace.
- **`LabelCoverage.traceable_total`**, `traceable_chains`: labels on the chains a trace can run on. The landing's headline shows this, not `total`.
- Audit actions added: `coverage.view`, `sahyog.complaint`, `sahyog.status`, `sahyog.reply`, `sim.view`, `sim.complaint`, `sim.reply`.

### Batches, the trace budget and measured throughput (G5)

All additive.

- **`POST /api/cases/batch`** → 202 `BatchDetail`. Body `BatchCreate`: either `rows[]` (`address`, optional `chain`, `case_ref`) or `csv` (the text of a CSV file; columns `address, chain, case_ref`, header line optional, comma, semicolon or tab), plus optional `name`, `max_hops`, `max_wallets`, `max_seconds`. At most 2,000 rows and 2 MB. There is no multipart upload: the browser reads the file and posts its text.
  - Every row is checked on its own. A row that cannot be traced has `accepted: false` and `error` (a sentence); the others are queued. A wallet given twice has `duplicate_of` (the earlier row) and shares its case. A wallet that already has a finished case is linked to it, not traced again.
  - 422 only when the upload as a whole cannot be read: neither or both of `rows` and `csv`, no row, too many rows, too large.
- **`GET /api/batches`** → `BatchList` (newest first, without rows). **`GET /api/batches/{id}`** → `BatchDetail`: `progress` (`total`, `accepted`, `duplicates`, `refused`, `queued`, `running`, `done`, `failed`, `by_outcome`, `finished`), `workers` (0 = traced in the server process), `results_csv`, and `rows[]` in upload order. Poll it while `progress.finished` is false.
  - `BatchRow`: `row` (its number in the upload), `address`, `chain`, `case_ref`, `accepted`, `error`, `duplicate_of`, `case_id`, `case_url`, `status`, and once the case is done `outcome`, `top_vasp`, `hops`, `proximity_rank`, `share_of_funds`, `confidence`, `risk_class`, `budget_ended`. **Proximity (`hops`, `proximity_rank`, `share_of_funds`) and `confidence` are separate figures**, as on a case.
- **`GET /api/batches/{id}/results.csv`**: the same table as a file, one line per uploaded row. Cells that a spreadsheet would run as a formula are written as text.
- **The trace budget.** `CaseCreate.max_wallets` (1 to 2,000, default 40: wallets read per direction, largest share first) and `max_seconds` (1 to 3,600, default none).
  - `provenance.budget` (`TraceBudget`): `max_wallets`, `max_hops`, `max_seconds`, `ended_by` (`wallets`, `time` or null), `ended_side`, `wallets_read`, `share_not_followed`, `text`. **Show `text` when `ended_by` is set**: the budget, not the evidence, ended the trace. Null in a case stored before G5.
  - `provenance.input` gains `max_wallets`, `max_seconds`, `stopped_after` **only when the budget was changed**: a case traced with the default budget has the same four-field input and the same input digest as before. `stopped_after` records where a time limit ended the walk, so `verify` replays it exactly.
- **`GET /api/scale`** → `ScaleMetrics`: `status` (`measured` or `not_measured`), `measured_on`, `machine`, `chain_data`, `wallets`, `rounds`, `runs[]` (`workers`, `cases`, `seconds`, `cases_per_minute`, `median_seconds_per_case`, `p95_seconds_per_case`, `transfers_per_second`, `peak_memory_mb`, `speedup`, ...), `one_process`, `intake`, `baseline`, `limits[]`, `notes[]`. Read from `artifacts/scale/metrics.json` (`make bench-scale`). Show `limits` beside the figures.
- **The queue.** Every trace is queued in the case store before it runs (`vaspfusion/store/queue.py`). With `VASPFUSION_WORKERS=n` (`make serve WORKERS=n`) a pool of n worker processes traces; a case's `status` and `progress` read the same either way.
- Audit actions added: `batch.upload`, `batch.list`, `batch.view`, `batch.export`, `scale.view`.
- Mocks: `batches.json`, `batches/b-demo.json` (the three demo cases and one refused row), `scale.json` (the measured figures, real). In demo mode an upload answers with the demonstration batch.

## Money that crossed a bridge (G4)

A deposit into a labelled bridge is matched to its payout by the bridge's own public index
(Across today), the payout is read on the destination chain, and the trace goes on from the
recipient. Everything below is additive; a case stored before G4 has none of it.

- `CaseDetail.chains`: the chains the traced money was followed on, in the order it crossed.
  One entry unless a deposit was followed.
- `CaseDetail.crossings[]` (`Crossing`): every bridge deposit, followed or not.
  `status`: `followed` | `not_traced` (matched: `dest_name`, `recipient` and `payout_tx` are
  set, `reason` says why the trace stopped) | `unresolved` (no match; the trail ends at the
  bridge as before). `amount_out` is what the recipient received in `payout_tx`, read on the
  destination chain; it can be less than the bridge quotes. `fee` = `traced_in` - `traced_out`.
- **Wallet ids.** `GraphNode.id` is the address, or `chain:address` for a wallet on another
  chain than the case (an EVM address is the same string on every EVM chain, so the recipient
  of a bridge is often the suspect's own address). `GraphNode.address` is always the plain
  address and `GraphNode.chain` its chain. `GraphEdge.source` / `target` are ids. **Every other
  address field is a plain address** with its chain beside it: `Hop.from_chain` / `to_chain`,
  `Candidate.chain` and `path_chains`, `RequestWallet.chain`, `TypologyFlag.chain`.
- **The cross-chain edge.** `GraphEdge.bridge` / `Hop.bridge` (a `Crossing`) is set on the
  payout: `source` is the bridge wallet, `target` the recipient, `tx_hash` the payout
  transaction, `chain` the destination chain. The deposit is the edge before it.
- `CaseDetail.tx_chains`: transaction hash -> chain, for every transaction that is not on the
  case's own chain. Use it for explorer links wherever only a hash is at hand (evidence, flags).
- `FundsSlice.kind` has a new value, `bridge_fee`: what the followed crossings cost.
- `RequestWallet.asset`: over a bridge a stablecoin can arrive as another one.
- A swap service (`category: swap_service`) is a VASP: it is named, routed and written to.
  Its letter always carries the `transactions` ask, worded as a request for the payout chain,
  address and transaction.

## What the trace saw, and the context beside the trail (U8)
The graph of a case is sparse on purpose: it draws the wallet's money only. Two additions say what was left out and give it back on request. Both are additive.

- **`CaseDetail.trace_summary`** (`TraceSummary`, null on a case with no result or stored before this was counted):
  - `transfers_seen` (every transfer in every listing the trace read, each once), `transfers_followed` (those that carry the wallet's money: the transfers on the graph), `transfers_dust`.
  - `wallets_seen`, `wallets_read` (listings read), `wallets_followed` (read and followed on, the case's own wallet included), `wallets_not_followed`.
  - `not_followed[]` (`NotFollowed`): `reason`, `count`, `wallet_ids` (ids as in `graph.nodes`, so `chain:address` for a wallet on another chain; at most 200), `text`. Reasons: `small` (under 1% of the funds), `dust` (only on transfers below the dust limit), `hub`, `labelled` (the trail ends there by design), `depth_limit`, `budget`, `unreadable`, `other_chain`. **Every wallet on the graph is either followed or under exactly one reason.** `dust` and `other_chain` wallets are not on the graph.
  - `text`: the one line to show ("Followed 23 of 655 transfers seen. 23 wallets not followed: 16 below the dust limit, 4 high-activity hubs, …"). The case file prints the same line.
  - Each figure is counted by the trace where it makes the decision (`trace.py`: `TraceResult.seen`, `.dust`, `.read`); none is estimated afterwards.
  - It is part of `content_sha256` (a replay reproduces it) and **not** of `findings_sha256`: the findings fingerprints of the recorded cases did not change.
- **`GET /api/cases/{id}/context[?wallet=&limit=]`** → `CaseContext`: the transfers the trace read and did not follow.
  - `transfers` (the whole count; without `wallet` it equals `transfers_seen − transfers_followed`), `truncated`, `nodes[]` (`id`, `address`, `chain`, `on_graph`, `label`), `edges[]` (`id`, `tx_hash`, `source`, `target`, `asset`, `amount`, `amount_usd`, `block_time`, `chain`, `why`: `dust`, `other_asset` or `not_traced`), `text`.
  - Nothing is stored for it: the server traces the wallet again from the cached chain responses only, as `verify` does. **The case is not changed, and context is never part of the attribution, the Hop Rail, a share of the funds or the risk class.** Draw it greyed.
  - `wallet`: one wallet's other transfers. A wallet the trace read answers from the cache. A wallet it did not read (a labelled wallet, one at the hop limit) is fetched when the server is online (`live: true`); offline, `recorded` is false, `edges` is empty and `reason` says so.
  - 409 until the case has a result, or when its responses are no longer cached; 404 for a wallet that is not part of the case. Audit action `case.context`.
  - A mock case has no trace behind it: its fixture answers `recorded: false` with the reason.

## Mocks (`mocks/`, regenerate with `make mocks`)
Seed 26182, deterministic (byte-identical on rerun). Three demo cases, one per outcome:

| id | chain | outcome | what it shows |
|---|---|---|---|
| `demo-tron-okx` | tron | ATTRIBUTED → OKX 0.91 | 3 hops, sweep into a real OKX proof-of-reserves wallet, derived deposit address, HTX as rank 2, counterfactual line |
| `demo-eth-abstain` | ethereum | INSUFFICIENT_EVIDENCE | only 12% of funds reached a real ChangeNOW hot wallet, 4 hops away; abstain reason and what would change |
| `demo-tron-sanctioned` | tron | SANCTIONED_OR_MIXER_REACHED | 92% of funds went into a real OFAC-listed Tron address; CoinDCX as a weaker candidate |

**Real:** every labelled address (and its entity, tier and source) comes from `data/labels.duckdb`, as do the label-search results and the label coverage counts.

**Demo:** suspect, hop and deposit addresses (valid format, derived from `sha256("vaspfusion-demo:…")`, unlabelled), plus tx hashes, amounts, times and confidences. The one `derived`-tier label (the OKX deposit address) says `DEMO` in its `source`. VASP directory fields in `vasps/*.json` are the real cited entries from `data/vasp_directory.yaml` (blank where no source was found).

UI mock client rule: `GET /api/<path>` → `mocks/<path>.json`, minus the keys that start with `_`.
