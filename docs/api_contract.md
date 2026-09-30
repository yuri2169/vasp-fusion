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
- **Proximity and confidence are separate fields and are never blended.** `proximity_rank` (1 = nearest: hops, share of funds, time) and `confidence` (0–1, calibrated from B6).
- Outcomes: `ATTRIBUTED` · `INSUFFICIENT_EVIDENCE` (then `abstain_reason` + `what_would_change` are set, and `top_vasp` is null) · `SANCTIONED_OR_MIXER_REACHED`.
- Label tiers, strongest first: `published_por` (exchange's own proof-of-reserves list) › `curated` (OFAC, cex-list, MEW scam list, Dune spellbook, operator statements) › `explorer_tag` (Etherscan-style tags) › `derived` (inferred by VASP-FUSION, e.g. B4 sweep/gas-payer). UI names: *Published by exchange*, *Curated list*, *Explorer tag*, *Derived by VASP-FUSION*.
- Categories: `exchange`, `custodial_wallet`, `swap_service` (all three are VASPs), plus `sanctioned`, `scam`, `mixer`, `bridge`, `defi`, `entity`.
- An `entity` of `Unidentified exchange` means the source tags the address as an exchange but names no owner. It counts as a VASP hit, but no request can be routed to it.

## Endpoints

| Method | Path | Request | Response model | Mock file | Status | Owner |
|---|---|---|---|---|---|---|
| GET | `/api/health` | – | `Health` | – | live | B1 |
| POST | `/api/cases` | `CaseCreate` | `CaseSummary` (202) | returns a demo case if the address matches | mock | B3 |
| GET | `/api/cases?outcome=&status=` | – | `CaseList` | `cases.json` | mock | B3 |
| GET | `/api/cases/{id}` | – | `CaseDetail` | `cases/{id}.json` | mock | B3 (B4, B7 fill evidence/flags) |
| GET | `/api/wallets/{chain}/{address}` | – | `WalletDetail` | `wallets/{chain}/{address}.json` | **labels live**, the rest mock | B3/B6 |
| GET | `/api/labels/search?q=&chain=&category=&tier=&limit=&offset=` | – | `LabelSearch` | `labels/search.json` (fallback) | **live** | B1 |
| GET | `/api/desk` | – | `Desk` | `desk.json` | mock | B8 |
| GET | `/api/vasps/{name}` | – | `VaspDetail` | `vasps/{name}.json` | mock | B8 |
| POST | `/api/requests` | `RequestCreate` | `RequestDetail` (201) | the demo request for that VASP | mock | B8 |
| GET | `/api/requests/{id}` | – | `RequestDetail` (letter JSON + `pdf_url`) | `requests/{id}.json` | mock | B8 |
| PATCH | `/api/requests/{id}` | `RequestPatch` | `RequestDetail` | applied to the mock, not persisted | mock | B8 |
| GET | `/api/requests/{id}/pdf` | – | `application/pdf` | – | 501 until B8 | B8 |
| GET | `/api/dashboard` | – | `Dashboard` | `dashboard.json` | **label_coverage live**, the rest mock | B7/B9 |
| GET | `/api/model` | – | `ModelInfo` | `model.json` (`not_measured`) | mock | B6 |

`POST /api/cases`: `chain` is optional. The server guesses it from the address format (Tron `T…`, EVM `0x…` → `ethereum`, BTC `1…/3…/bc1…`, Solana base58). If it can't tell, it returns a 422 asking the officer to pick one. B2 replaces this guess with checksum validation.

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
