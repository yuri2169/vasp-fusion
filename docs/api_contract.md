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
| GET | `/api/desk` | – | `Desk` | `desk.json` (until a finished case names an exchange) | **live** | B8 |
| GET | `/api/vasps/{name}` | – | `VaspDetail` | `vasps/{name}.json` (only while no live case or request touches it) | **live** | B8 |
| POST | `/api/requests` | `RequestCreate` | `RequestDetail` (201) | the demo request, if every case id is a mock demo id | **live** | B8 |
| GET | `/api/requests/{id}` | – | `RequestDetail` (letter JSON + `pdf_url`) | `requests/{id}.json` (only for the mock id) | **live** | B8 |
| PATCH | `/api/requests/{id}` | `RequestPatch` | `RequestDetail` | applied to the mock, not persisted (mock id only) | **live** | B8 |
| GET | `/api/requests/{id}/pdf` (also `/api/requests/{id}.pdf`) | – | `application/pdf` | the mock request, marked "Demo fixture - not evidence" | **live** | B8 |
| GET | `/api/dashboard` | – | `Dashboard` | `dashboard.json` | **label_coverage live**, the rest mock | B7/B9 |
| GET | `/api/model` | `?chain=tron` (default) or `ethereum` | `ModelInfo` | `model.json` (the measured Tron model) | **live** from `artifacts/model_v1/<chain>/metrics.json` | B6 |

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
- **`PATCH /api/requests/{id}`** moves it: `drafted → approved → sent → acknowledged → answered | freeze_confirmed | refused`. Also `approved → drafted` (send it back), `answered → freeze_confirmed`, and **`drafted | approved → withdrawn`** (new status: a draft made by mistake; its wallets can be drafted again, and so can the wallets of a `refused` request). **`allowed_next[]`** on every request says which statuses the buttons may offer now. A step that is not allowed is **409**. A draft cannot be sent: it has to be approved first.
  - `approved` and `sent` first check that every wallet in the letter is still what its case says. If a case was traced again with a different result, or removed, the step is **409** ("Withdraw this request and draft a new one").
  - `approved` clears `letter.watermark` and sets `payload.draft` to false.
  - `sent` hands the payload and the letter PDF to the gateway (a local outbox: nothing leaves the machine), sets `due`, fills **`receipt`** (`gateway`, `receipt_id`, `submitted_at`, `location`, `payload_sha256`) and `payload.documents[0].sha256` (the letter's SHA-256). **502** if the gateway fails; the request stays `approved` and can be sent again.
- **The letter** (`RequestDetail.letter`) is fixed when drafted. New fields: `cases[]` (`case_id`, `case_ref`, `complaint_no`, `wallet`, `chain`), `legal_citations[]` (`section`, `act`, `heading`, `url`), `channel`, and **`review_notes[]`**: what the officer should check before approving (an unlabelled wallet named because it passed everything on; the exchange's own wallet rather than a customer's; a naming that rests on one label; a label derived by our own rules; how the FIU-IND registration is known and as of when; no channel or legal name on file). Show them beside the letter, not in it. Each `LetterWallet` also has `case_id`, `case_ref`, `asset`, `amount`, `confidence`, `paid_into`, `label`. Addresses and hashes in a letter are always in full.
- **`GET /api/requests/{id}/pdf`** (or `.pdf`): A4, `Content-Disposition: inline`. A draft carries a banner on every page, a diagonal watermark and a last sheet of review notes; an approved letter has none of them. The same request always gives the same bytes, and once sent the bytes served are the ones that were submitted.
- The mock demo request follows the same rules: `POST` with a demo case answers only for the exchange that demo case names (else 422), and `PATCH` on it refuses a step that is not allowed (409).
- CLI: `make desk`, `make letter VASP=CoinDCX OFFICER="…" [CASES=a,b] [SEND=1]`.

**`ModelInfo`**: `status: "measured"` once `make model` has run (see "The deposit-address model (B6)"). With no `metrics.json` for the chain the route answers `status: "not_measured"`: every metric is null and the lists are empty, and the UI shows "not yet measured". Every number is measured; there are no placeholders.

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
