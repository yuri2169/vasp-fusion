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
- Errors come back as `{"detail": "<plain-English sentence saying what happened and what to do>"}`. Codes used: 404 (unknown id), 422 (bad input; `detail` is a string for our own checks, and a list for Pydantic validation errors), 403 (cross-origin write refused), 501 (not built yet).
- Addresses are returned exactly as stored. EVM addresses are lowercase; Tron and BTC keep their case.
- **Proximity and confidence are separate fields and are never blended.** `proximity_rank` (1 = nearest: hops, share of funds, time) and `confidence` (0–1; rule-based in B3, calibrated from B6).
- Outcomes: `ATTRIBUTED` · `INSUFFICIENT_EVIDENCE` (then `abstain_reason` + `what_would_change` are set, and `top_vasp` is null) · `SANCTIONED_OR_MIXER_REACHED`.
- Label tiers, strongest first: `published_por` (exchange's own proof-of-reserves list) › `curated` (OFAC, cex-list, MEW scam list, Dune spellbook, operator statements) › `explorer_tag` (Etherscan-style tags) › `derived` (inferred by VASP-FUSION, e.g. B4 sweep/gas-payer). UI names: *Published by exchange*, *Curated list*, *Explorer tag*, *Derived by VASP-FUSION*.
- Categories: `exchange`, `custodial_wallet`, `swap_service` (all three are VASPs), plus `sanctioned`, `scam`, `mixer`, `bridge`, `defi`, `entity`.
- An `entity` of `Unidentified exchange` means the source tags the address as an exchange but names no owner. It counts as a VASP hit, but no request can be routed to it.

## Endpoints

| Method | Path | Request | Response model | Mock file | Status | Owner |
|---|---|---|---|---|---|---|
| GET | `/api/health` | – | `Health` | – | live | B1 |
| POST | `/api/cases?refresh=` | `CaseCreate` | `CaseSummary` (202) | returns a mock demo case if the address is one of theirs | **live** | B3 |
| GET | `/api/cases?outcome=&status=` | – | `CaseList` | `cases.json` (listed after the live cases) | **live** + mock | B3 |
| GET | `/api/cases/{id}` | – | `CaseDetail` | `cases/{id}.json` (only for the mock ids) | **live** | B3 (B4, B7 fill evidence/flags) |
| GET | `/api/wallets/{chain}/{address}` | – | `WalletDetail` | `wallets/{chain}/{address}.json` | **labels and `cases` live**, the rest mock | B3/B6 |
| GET | `/api/labels/search?q=&chain=&category=&tier=&limit=&offset=` | – | `LabelSearch` | `labels/search.json` (fallback) | **live** | B1 |
| GET | `/api/desk` | – | `Desk` | `desk.json` | mock | B8 |
| GET | `/api/vasps/{name}` | – | `VaspDetail` | `vasps/{name}.json` | mock | B8 |
| POST | `/api/requests` | `RequestCreate` | `RequestDetail` (201) | the demo request for that VASP | mock | B8 |
| GET | `/api/requests/{id}` | – | `RequestDetail` (letter JSON + `pdf_url`) | `requests/{id}.json` | mock | B8 |
| PATCH | `/api/requests/{id}` | `RequestPatch` | `RequestDetail` | applied to the mock, not persisted | mock | B8 |
| GET | `/api/requests/{id}/pdf` | – | `application/pdf` | – | 501 until B8 | B8 |
| GET | `/api/dashboard` | – | `Dashboard` | `dashboard.json` | **label_coverage live**, the rest mock | B7/B9 |
| GET | `/api/model` | – | `ModelInfo` | `model.json` (`not_measured`) | mock | B6 |

### Cases are live (B3)
- `POST /api/cases` validates the address (base58check / EIP-55 / bech32), stores the case as `queued`, answers 202 at once, then traces in the background: `queued → running → done | failed`. **Poll `GET /api/cases/{id}`** until the status is `done` or `failed`. A real trace takes about 1–10 s live, and well under a second from the cache.
- `chain` is optional: Tron, Bitcoin and Solana addresses are unambiguous, and an EVM address is taken as `ethereum` unless the officer picks another chain. EVM addresses are stored lowercase.
- 422 with a plain-English `detail` when: the chain can't be told from the address; the address is not valid on the chosen chain; or the chain can't be traced yet (traceable today: tron, ethereum, polygon, arbitrum, base, optimism; Bitcoin arrives with B5).
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

## Key shapes (see `types.ts` for every field)

**`CaseDetail`** = `CaseSummary` plus:
- `hop_rail: Hop[]`: the path to the top candidate, one ticket stub per hop (`from_address → to_address`, `amount`, `asset`, `amount_usd`, `block_time`, `elapsed_s`).
- `graph: {nodes: GraphNode[], edges: GraphEdge[]}`
  - nodes: `role` (`suspect` · `intermediary` · `exchange_hot` · `exchange_deposit` · `exchange` · `custodial_wallet` · `swap_service` · `bridge` · `mixer` · `sanctioned` · `hub` · `unknown`), `hop`, `label` (a `LabelOut` with `tier`), and `cluster` (the VASP name; collapse nodes that share it).
  - edges: `tx_hash`, `amount`, `amount_usd`, `block_time`.
- `candidates: Candidate[]`, sorted by `proximity_rank`. Each has `vasp`, `category`, `confidence` + `confidence_interval`, `hops`, `share_of_funds`, `time_to_reach_s`, `label_tier`, `deposit_address`, `path`, `evidence: EvidenceItem[]` (`kind`: label/path/sweep/gas_payer/model/counterfactual; `text`; `tier`; `tx_hashes`; signed `weight`), and `counterfactual`.
- `typology_flags: TypologyFlag[]`: `code` (peel_chain, fan_out, fan_in, rapid_forwarding, round_amounts, bridge_hop, mixer_contact, sanctioned_contact), `severity`, `wallet`, `text`, `figures`, `tx_hashes`.
- `narrative`, `abstain_reason`, `what_would_change[]`, `next_steps[]`, `provenance` (seed, code version, label DB hash, offline replay flag, data sources).

**`RequestDetail`**: `status` (drafted → approved → sent → acknowledged → answered | freeze_confirmed | refused), `status_history[]`, `letter` (reference, date, to, subject, numbered `paragraphs`, `wallets` table with tier, `asks` (kyc, transactions, freeze, preservation), `legal_basis` (§94 BNSS 2023 notice; §63 BSA 2023 certificate), `officer`, `watermark` (the draft watermark text; null once approved)), `pdf_url`, and `payload` (the SAHYOG JSON, specified in `docs/sahyog_contract.md` in B8).

**`ModelInfo`**: `status: "not_measured"` until B6. Every metric is null and the lists are empty; the UI shows "not yet measured". There are no placeholder numbers anywhere.

## Mocks (`mocks/`, regenerate with `make mocks`)
Seed 26182, deterministic (byte-identical on rerun). Three demo cases, one per outcome:

| id | chain | outcome | what it shows |
|---|---|---|---|
| `demo-tron-okx` | tron | ATTRIBUTED → OKX 0.91 | 3 hops, sweep into a real OKX proof-of-reserves wallet, derived deposit address, HTX as rank 2, counterfactual line |
| `demo-eth-abstain` | ethereum | INSUFFICIENT_EVIDENCE | only 12% of funds reached a real ChangeNOW hot wallet, 4 hops away; abstain reason and what would change |
| `demo-tron-sanctioned` | tron | SANCTIONED_OR_MIXER_REACHED | 92% of funds went into a real OFAC-listed Tron address; CoinDCX as a weaker candidate |

**Real:** every labelled address (and its entity, tier and source) comes from `data/labels.duckdb`, as do the label-search results and the label coverage counts.

**Demo:** suspect, hop and deposit addresses (valid format, derived from `sha256("vaspfusion-demo:…")`, unlabelled), plus tx hashes, amounts, times and confidences. The one `derived`-tier label (the OKX deposit address) says `DEMO` in its `source`. VASP directory fields are empty, because B8 fills only facts it can cite.

UI mock client rule: `GET /api/<path>` → `mocks/<path>.json`, minus the keys that start with `_`.
