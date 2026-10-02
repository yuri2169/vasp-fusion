# VASP-FUSION

Given an unknown crypto wallet, find the nearest VASP (exchange, custodial wallet or swap service) that took deposits from it, with a calibrated confidence, an investigation report and a SAHYOG request. SIH 2026 · PS 26182 (MHA / I4C) · Team 112bits.

Forked from our own BTC-FUSION (SIH26146), with the same stack: Python 3.12, FastAPI, Polars, igraph, LightGBM, SHAP and DuckDB; React, Vite, Tailwind and Cytoscape on the front end.

## Quickstart
```bash
make setup     # uv venv (Python 3.12) + install
make labels    # build data/labels.duckdb from ../research/data and print the stats
make test      # pytest
make serve     # API on http://127.0.0.1:8000  (docs at /docs)
make fetch ADDR=TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw   # transfers, cached; OFFLINE=1 = cache only
make trace ADDR=TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c   # wallet -> nearest exchange(s), as an officer reads it
make demo      # the real demo wallets (demo/cases.json) into the case store; OFFLINE=1 replays them
make desk      # the request desk: the exchanges those cases route to, one row each
make letter VASP=CoinDCX OFFICER="Insp. A. Rao"   # one consolidated request -> data/exports/<id>.pdf (a draft; SEND=1 approves and writes it to the mock SAHYOG outbox)
make model     # train, calibrate and measure the deposit-address model; then `make labels`
make abstain-eval   # measure the abstain bar on real customers traced with labels hidden
make case-pdf CASE=tron-coindcx   # the case file (A4 PDF) and its receipt -> data/exports/
make verify    # trace every stored case again from the cache only and compare fingerprints
make audit     # check the audit log's hash chain
make reproduce # regenerate every artifact that comes from tracked files; fails if one changed
make docker && make docker-up     # the offline image on http://127.0.0.1:8000
make docker-smoke                 # the whole demo inside a container with no network
```
Contract work: `make mocks` regenerates `mocks/` (seeded), and `make types` regenerates `docs/openapi.json` and `ui/src/api/types.ts`.

## Offline demo in Docker
```bash
make labels          # once: the image bakes data/labels.duckdb in
make docker          # build vasp-fusion:offline (needs the network once: base images, wheels)
make docker-up       # http://127.0.0.1:8000; sign in with the account in demo/officer.json
make docker-smoke    # 47 checks in a throwaway container started with --network none
```
- **Nothing reaches the network at run time.** The image sets `OFFLINE=1`: a chain request that is not in its cache is refused, never fetched. `make docker-smoke` proves it by running the whole demo with networking disabled.
- **What is baked in:** the label database; the chain responses the eight demo wallets' traces read, replayed from the tracked recordings in `tests/fixtures/demo/` into a cache (`cli demo-cache`, no network); the eight demo cases, traced while the image is built. **The build fails unless every case reproduces its golden findings fingerprint (`tests/golden/fingerprints.json`) and verifies.**
- **The interface.** `UI=build make docker` compiles `ui/` into the image. Without it (the default until the UI track lands) the API serves a plain console page at `/`: sign in, the cases with their case files and receipts, a Verify button, the desk, the audit log.
- **Login.** The image holds one demonstration account (`demo/officer.json`, published in the repository, so it protects nothing). `VASPFUSION_AUTH=off docker compose up` runs without a login. For real use, disable it and add officers: `docker compose exec vasp-fusion python -m vaspfusion.cli officer add <user> --name "..."`.
- **State** (cases, requests, audit log, token secret) lives in the volume `vaspfusion-data`. A rebuilt image does not replace it: `docker compose down -v` starts again from the image's demo data.
- The container runs as a non-root user with a read-only root filesystem and no Linux capabilities, bound to 127.0.0.1.
- To carry it to an air-gapped machine: `docker save vasp-fusion:offline | gzip > vasp-fusion.tar.gz`, then `docker load` there.
- A live trace from the container needs `OFFLINE=0` and real keys (`ETHERSCAN_API_KEY`, `TRONGRID_API_KEY`) in the environment.

## Case file, receipt, verify
```bash
python -m vaspfusion.cli case-pdf <case id>       # data/exports/case-<id>.pdf + .receipt.json
python -m vaspfusion.cli verify <case id>         # or --all, or --receipt file.json
```
- Sentences in the case file keep the short form of an address (first six and last six characters) exactly as the trace wrote it; the file never expands one, because a look-alike address would be indistinguishable. Every wallet of the case is listed in full in its wallet table. A case reference in a script other than Latin prints as question marks (standard PDF fonts).
- **The case file** (`GET /api/cases/{id}/pdf`): result, summary, where the funds went, a flow diagram with every wallet numbered and listed in full, each exchange reached with its evidence and transaction hashes, the path, patterns, leads, how the confidence was worked out (what is calibrated and what is not, and how the 0.60 bar was checked), what would change it, next steps, limitations, and the receipt. **The same case gives the same bytes**; every page's footer carries the findings fingerprint.
- **The receipt** is part of every case (`provenance`) and a document of its own (`GET /api/cases/{id}/receipt`): SHA-256 of the input (wallet, chain, hop limit, start date), of every chain response the run read (each listed, with one digest over all), of the label database and of the model; the code version, git commit and seed; the **findings fingerprint**, a digest over every figure, address, time and transaction hash of the result and none of its wording; and a content digest over the result with its wording. The case reference, complaint number and amount lost are the officer's entries and are covered by neither.
- **Verify** traces the wallet again from the cached responses only (it never fetches) and compares. It passes when the stored case still has its own digests, the same responses were read byte for byte, the new result has the same fingerprint, and its text is the same too (a difference in wording is accepted, and said, only when the code or the label database has changed since). The digests are not keyed, so a digest alone proves nothing: the replay does. A receipt on its own is checked the same way, and its stated outcome, exchange and confidence must be what the trace gives.
- Golden files: `tests/golden/` holds each demo wallet's fingerprint and its case file as text. `python tests/refresh_golden.py` rewrites them after a deliberate change; read the diff.

## Login and audit
```bash
python -m vaspfusion.cli officer add a.rao --name "Insp. A. Rao" --post "Cyber Crime PS"
python -m vaspfusion.cli officer list | disable <user>
python -m vaspfusion.cli audit [--officer a.rao] [--action case] [--target <case id>]
python -m vaspfusion.cli audit --verify
```
- **A login is required once an officer account exists** (disabled or not), or with `VASPFUSION_AUTH=required`. With none, the tool runs as a single-officer workstation and the log records "not signed in". `VASPFUSION_AUTH=off` forces it off.
- Accounts live in `data/officers.json` (scrypt hashes, a salt each; git-ignored). Five wrong passwords lock a user name for five minutes; attempts are counted before the password is checked, and a name with no account locks the same way. Accounts are made on the command line, not through the API.
- Tokens are HS256 JWTs, valid 8 hours, sent as `Authorization: Bearer` or the HttpOnly, SameSite=Strict session cookie the login sets. The signing secret is `VASPFUSION_JWT_SECRET`, or 32 random bytes written once to `data/auth_secret`.
- **Every `/api` request leaves one audit row** (`data/audit.duckdb`): who, which action, on which case, wallet, exchange or request, and the status. Never a request body. A refused request is a row too. The same read repeated within 30 seconds is one row.
- **The log is hash-chained and keyed:** each row's hash is an HMAC-SHA256 of the row and the hash before it, so an edited, removed or reordered row breaks the chain from there, `audit --verify` names it, and the log cannot be rewritten and rehashed without the key. The key is `VASPFUSION_AUDIT_KEY` (keep it off this machine's disk if you can), or else a file made beside the log (`data/audit.duckdb.key`). Whoever holds both the log and the key can rewrite it, and rows cut off the end leave a valid chain: note the head hash somewhere else (`audit --verify` prints it) to catch both.
- A request's status history records the signed-in officer who drafted, approved and sent it.
- Limits: one server process; a token cannot be revoked before it expires except by disabling its account; no roles (every officer can read the log).
- No file upload exists in this tool, so there is nothing to sandbox; cross-origin writes are refused (403), and every API reply is `no-store`, `nosniff`, not frameable.

## Reproduce
`make reproduce` regenerates, with no network: the label database, both models (trained from the tracked `dataset.csv`), the abstain measurement (from the tracked `claims.csv`), the demo's chain cache (from the recorded fixtures), the eight demo cases (checked against the golden fingerprints, then verified), the golden case files, the mocks and the OpenAPI schema; then runs the tests. It then compares every tracked artifact with what git holds. Only `trained_at` in a model's `metrics.json` may differ. `--full` also replays discovery, the model's dataset and the abstain traces from the crawl caches where they are on the machine.

## Layout
| Path | What |
|---|---|
| `vaspfusion/labels/` | Label store: normalise → build (tier-ranked dedupe) → lookup/search |
| `vaspfusion/chains/` | Chain adapters (Tron, EVM, Bitcoin, Solana stub) behind a cache-first fetcher; the only code that reaches the network |
| `vaspfusion/cluster.py` | Bitcoin: an address spent together with a labelled exchange address takes that exchange's label, with the cluster as evidence |
| `vaspfusion/trace.py` | Bidirectional trace: follows the wallet's money hop by hop, allocating by amount |
| `vaspfusion/attribute/rules.py` | Candidates, proximity rank, rule confidence, the three outcomes |
| `vaspfusion/discover/` | Deposit-address discovery: the sweep and gas-payer rules, the crawler, the hold-out evaluation |
| `derived/` | What discovery found (`<run>.csv`, `<run>_report.json`) and the hold-out result; `make labels` merges the CSVs |
| `vaspfusion/classify/` | The deposit-address model: features, dataset, splits, training + calibration, SHAP reasons, label scores |
| `artifacts/model_v1/<chain>/` | The model's dataset, measurements, plots, label scores and the model itself as LightGBM text (`model.txt`), all tracked |
| `vaspfusion/detect/typologies.py` | Typology flags over the traced money, each with figures and hashes |
| `vaspfusion/attribute/counterfactual.py`, `leads.py` | Does a named exchange survive without its label; unlabelled wallets that behave like deposit addresses |
| `vaspfusion/eval/abstain.py`, `artifacts/abstain_v1/` | The abstain bar measured by hiding labels: claims, risk vs coverage |
| `vaspfusion/explain/case_narrative.py` | The paragraph an officer reads |
| `vaspfusion/cases.py`, `vaspfusion/store/cases.py` | `run_case` → the API's `CaseDetail`; cases in `data/case.duckdb` |
| `vaspfusion/provenance.py` | The receipt: digests of the input, the responses, the findings; `verify_case` |
| `vaspfusion/explain/case_file.py`, `flow.py`, `case_pdf.py` | The case file: what it says (blocks, text), the flow diagram's layout, the A4 PDF |
| `vaspfusion/desk/`, `data/vasp_directory.yaml` | The request desk: routing, the cited exchange directory, letters, the mock SAHYOG gateway |
| `vaspfusion/auth/`, `vaspfusion/store/audit.py`, `vaspfusion/api/security.py` | Officer accounts and tokens; the hash-chained audit log; login and audit in front of the API |
| `vaspfusion/api/` | `schemas.py` (the contract), `main.py` (routes; only the dashboard and the three fixture cases still answer from mocks), `console.html` (served at `/` when no interface is built) |
| `vaspfusion/{graph,features,detect,eval}/`, `explain/narrative.py`, `store/dao.py` | Carried over from BTC-FUSION |
| `demo/cases.json`, `demo/officer.json` | Seven real demo wallets and the result each must give; the demonstration login |
| `tests/golden/` | Each demo wallet's findings fingerprint and case file as text |
| `Dockerfile`, `docker-compose.yml`, `requirements.lock`, `scripts/docker_smoke.py` | The offline image |
| `scripts/reproduce.py` | `make reproduce` |
| `docs/api_contract.md` | Endpoints, conventions, mock rules |
| `docs/plans/` | Per-phase implementation plans |
| `mocks/` | Demo fixtures for the UI track (labelled addresses real, the rest synthetic, all marked `_demo`) |

## Label store
One row per `(address, chain)`: `entity, category, kind, tier, source, source_url, label`, plus `confidence` and `evidence` on `derived` rows, and `confidence_low`, `confidence_high` and `model` (the deposit-address model's probability, range and reasons) on the derived rows the model scored.
- Tier priority: `published_por > curated > explorer_tag > derived`. A derived row never replaces a label from another source.
- EVM addresses are lowercased; Tron and BTC keep their case.
- Dune "EVM" rows are stored as chain `evm` and match any EVM chain on lookup.
- Sources: the wallet-attribution set and the Dune spellbook extract (115,242 labels), the derived deposit addresses, and the exchange packs of the **GraphSense TagPacks** (MIT, pinned to one commit): 336,531 exchange tags on Bitcoin, Ethereum and Tron, of which 336,208 are BitMEX's own published address list and 120 are WalletExplorer's named exchange wallets. `make tagpacks` flattens the packs in `research/data/graphsense-tagpacks/` into the CSV `make labels` reads.

```python
from vaspfusion.labels.lookup import lookup, LabelStore
lookup("TAa8e7U7seCy7NcZ52xYVQXXybFfwvsUxz", "tron")   # Label(entity='Bitget', tier='published_por', ...)
```

## Chain adapters
```python
from vaspfusion.chains import get_provider, detect_chain
p = get_provider(detect_chain("TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw"))   # tron
p.transfers("TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw", "in", since=None, limit=200)
# -> [Transfer(chain, tx_hash, block_time, from_addr, to_addr, asset, amount, amount_usd, fee_payer, asset_contract)]
```
| Chain | Source | Key (optional) |
|---|---|---|
| tron | TronGrid `/v1/accounts/{a}/transactions/trc20` (USDT) + `/transactions` (TRX) | `TRONGRID_API_KEY` |
| ethereum, polygon, arbitrum | Etherscan v2 with a key, else Blockscout | `ETHERSCAN_API_KEY` |
| base, optimism | Blockscout (keyless) | – |
| bsc | Etherscan v2 **paid** plan only (the free plan refuses) | `ETHERSCAN_API_KEY` |
| bitcoin | Esplora `/api/address/{a}/txs`: blockstream.info, or mempool.space with `VASPFUSION_BTC_API=mempool.space` (same API; a replay needs the backend it was recorded from) | – |
| solana | address check only | – |

- Keys come from the process env, then `.env` (never committed). They are never printed, cached or written to fixtures.
- Every response is cached raw in `data/chain_cache.duckdb` with its SHA-256, keyed by `(chain, address, direction, query)`. Re-runs replay from the cache; `--refresh` re-fetches. **`OFFLINE=1`** serves only from the cache and fails loudly on a miss.
- Tests replay responses recorded once from the live APIs (`scripts/record_chain_fixtures.py` → `tests/fixtures/chains/`); CI needs no network.
- Tokens other than the known USDT/USDC contracts are named `SYMBOL@contract`, so a fake "USDT" never passes as USDT.

## Deposit-address discovery
```bash
make discover        # three Tron runs -> derived/*.csv (cached; OFFLINE=1 replays byte-identical)
make labels          # merges the derived rows into the label DB as tier=derived
make discover-eval   # hold-out test on explorer-tagged addresses -> derived/holdout_*.json
```
Starting from an exchange's labelled wallets, every address that paid stablecoins into one of them is a candidate. Two rules decide (`vaspfusion/discover/rules.py`):
- **Sweep rule.** The address forwarded at least 90% of the stablecoins it received to labelled wallets of one exchange, each part within 7 days of arriving. Sweeps are paired with the newest deposits; an idle balance counts against the share.
- **Gas-payer rule.** Whoever delegated energy or sent 1 to 100 TRX to the address in the hour before a sweep (or signed the sweep) is its payer. A payer that is a labelled wallet of the same exchange confirms the sweep rule. A payer of another exchange is a **conflict**: recorded in the CSV, never a label.
- An unlabelled payer that serves 10 or more of these addresses, 95% of them one exchange's, is reported as that exchange's **gas station** (in `<run>_report.json`, not as a label: an energy seller would look the same).
- Each derived label carries a rule confidence = the attribution weight of the wallet it sweeps to × 0.95 (both rules agree), 0.90 (gas station) or 0.80 (sweep rule only), and `evidence`, the paragraph an officer reads. That confidence is hand-set, not calibrated; where the deposit-address model confirms the label, the label carries the model's value instead (next section).
- A derived label never replaces a label from another source, and two runs that name different exchanges for one address load neither.

**Result (1 Oct 2026, `derived/`):** 122 labelled Tron exchange wallets → **5,497 derived deposit addresses**: OKX 1,742 · Gate.io 1,134 · KuCoin 958 · Bitget 755 · CoinDCX 558 · Bitfinex 217 · Bitrue 133 (HTX and WazirX: none). 3,773 by both rules, 1,711 by sweep + gas station, 13 by the sweep rule alone; no conflicts. 811 have a listing that was cut at 50 rows, and their evidence says so.

**Measured on held-out explorer tags** (`derived/holdout_ethereum_bitget.json`; Ethereum, because our data has no tagged Tron deposit addresses): of 300 Etherscan-tagged Bitget deposit addresses, labels hidden, the rules rediscovered 66 (**recall 22.0%**; 230 never held a stablecoin, which is all the rule reads; among the 70 that did, **94.3%**). None was given to the wrong exchange. On 300 tagged addresses that are not deposit addresses the rule fired on 24 of 150 exchange wallets (16.0%) and 0 of 150 others; all 24 named the exchange their own tag names.

## Deposit-address model
```bash
make model-data                       # the Tron training set (cached; OFFLINE=1 replays byte-identical)
make model                            # train, calibrate, measure, score the derived labels
make labels                           # merge the scores into the label DB
make model-data MODEL_CHAIN=ethereum  # the explorer-tagged benchmark
make model MODEL_CHAIN=ethereum
```
A LightGBM model (`vaspfusion/classify/`) says how likely an address is an exchange deposit address from what it does. It reads 14 behaviour features of one address and no label: how much of what it receives it forwards to one wallet, how fast, how many wallets pay it and are paid by it, who covers its network fees, and whether the wallet it pays most forwards everything on in turn (a deposit address does; a collecting wallet does not). Venn-Abers turns its score into a probability with a range; SHAP gives the reasons, written in plain words.

- **Both classes are read the same way:** the same listings, the same start date, the same row limit, nothing later than the run's last positive transfer, and only the first 14 days of each address. An address is judged without its own label.
- **Never split at random.** By time (earliest 60% train, next 20% calibrate, last 20% test) and by exchange (everything of one exchange held out). `eval/splits.verify` rejects a leak.
- **The two features that read exchange labels are an ablation, not part of the model.** On Tron the positives were picked by those labels, so a model that reads them is the rule again.
- **Labels carry cross-fit scores:** each exchange's addresses are cut into 5 blocks by time and each block is scored by a model trained on the other blocks. No address is scored by a model that trained on it.
- **The model can confirm a label, not overrule it.** A derived label carries *weight of the exchange wallet's label × the model's probability*, with its range, when that is at least the rules' confidence. Otherwise the rules' confidence stays and the evidence says why. The model cannot see the sweep into a labelled exchange wallet, so it must not veto it.

**Measured (2 Oct 2026, `artifacts/model_v1/`, seed 26182):**

*Tron*, 8,952 real addresses: the 5,497 derived deposit addresses, 3,434 wallets that paid into them, 21 labelled exchange wallets. **The truth here is the discovery rules' verdict**, so these numbers say how well behaviour alone recovers what rules and labels found.

| How it was tested | n | PR-AUC | ROC-AUC | Brier | ECE | Precision | Recall |
|---|---|---|---|---|---|---|---|
| By time (latest 20%) | 1,791 | 1.000 | 1.000 | 0.0026 | 0.0093 | 0.994 | 1.000 |
| By exchange, pooled (never saw the exchange) | 8,950 | 0.9989 | 0.9985 | 0.0140 | 0.0293 | 0.998 | 0.9935 |
| Cross-fit (the labels' scores) | 8,952 | 0.9995 | 0.9994 | 0.0044 | 0.0076 | 0.999 | 0.9935 |

- The bar is not chance: the single rule "forwards 90% or more to one wallet" already gives precision 0.934 and recall 1.000 by time, because the positives were chosen for that. The model's gain is on the look-alikes: of the 418 other wallets that also forward 90% or more, a model that never saw the exchange calls 10 a deposit address (2.4%); the rule calls all 418 one.
- By exchange: PR-AUC is 1.000 for Bitfinex, Bitget, Bitrue, Gate.io, KuCoin and OKX, and 0.980 for CoinDCX (recall 0.943: 30 of its addresses sweep into a wallet that forwards on again).
- The model confirms 5,249 of the 5,497 derived labels; 248 keep the rules' confidence (36 of them because the model does not recognise the behaviour).
- Not measured: a wallet that never dealt with an exchange is not in the sample, and the probabilities are calibrated at this dataset's class mix.

*Ethereum*, 1,467 real addresses, **a truth our rules never saw**: 599 explorer-tagged deposit addresses (Bitget, and "Binance Dep" filed upstream under `bilaxy`), 271 tagged addresses that are not deposit addresses, 597 wallets that paid into the deposit addresses.

| How it was tested | n | PR-AUC | ROC-AUC | Brier | ECE | Precision | Recall |
|---|---|---|---|---|---|---|---|
| By time (latest 20%) | 294 | 0.955 | 0.980 | 0.057 | 0.056 | 0.803 | 0.981 |
| By exchange, pooled | 1,196 | 0.762 | 0.786 | 0.371 | 0.385 | 0.909 | 0.100 |
| Cross-fit | 1,467 | 0.950 | 0.972 | 0.061 | 0.028 | 0.892 | 0.895 |

- The one rule alone gives precision 0.55 and recall 0.56 here; the model gives 0.80 and 0.98.
- **By exchange it fails:** with two exchanges, each model learned deposit addresses from one exchange only, and what it learned did not carry over (recall 0.10). On Tron, with six exchanges to learn from, it did.
- Reading the exchange's other labelled wallets (the two ablation features) lifts PR-AUC by time from 0.955 to 0.975 on this truth, where the labels did not pick the positives.

Plots: `reliability.svg`, `reliability_by_exchange.svg`, `reliability_labels.svg`, `importance.svg` in each chain's folder.

## The abstain bar, measured
```bash
make abstain-eval                 # 280 real wallets traced twice (cached; OFFLINE=1 replays byte-identical)
python -m vaspfusion.cli abstain-eval --from-claims   # measure again from the tracked claims.csv
```
No exchange is named below confidence 0.60. There is no labelled set of "wallet → exchange" cases to pick that bar on, so one is built by hiding labels (`vaspfusion/eval/abstain.py`):
- **Wallets:** 280 real Tron wallets (40 per exchange, seed 26182) that paid an address the discovery rules derived as a deposit address. **Known answer:** the exchanges each paid directly, from the full label store.
- **Test:** each is traced from the start of its discovery window with all 5,497 derived labels hidden, so the exchange must be found through an unlabelled wallet. Each exchange reached is a claim; it is right if it is in the known answer. A claim through a wallet the rules did not derive counts as wrong, although that wallet may be a deposit address the rules missed.
- **Result** (`artifacts/abstain_v1/tron/validation.json`): 303 claims, 224 right. At 0.60, 155 of the 280 wallets get an exchange named, 15 of them wrong (9.7%; upper bound 17.3%, one-sided Clopper-Pearson over wallets, corrected for the nine bars tried), and 125 abstain. At 0.80: 121 named, 8 wrong (6.6%; bound 14.6%). **No bar on the grid brings the bound under 5%**, so the measurement does not single out a bar and 0.60 stays a rule-set value. Claims three hops away are right 2 times in 20.
- **What it is not.** The wallets were picked by the pattern the label-hidden trace walks (which favours right claims), the known answer includes the tool's own derived labels, every wallet is an exchange customer, and the confidence is rule-set. The bar is checked, not calibrated. Plot: `artifacts/abstain_v1/tron/risk_coverage.svg`.

## Trace and attribution
```bash
python -m vaspfusion.cli trace <address> [--chain ..] [--max-hops 1-5] [--since ISO] [--json] [--save]
```
- **One asset is followed:** the stablecoin the wallet sent most of, else the native coin. Unknown tokens are never followed (this is what keeps address-poisoning spoofs out). Whatever else the wallet sent is listed as "not followed".
- **Allocation, "first out after arrival":** money that reached a wallet at time *t* is assigned to that wallet's next outgoing transfers at or after *t*, in time order. So every unit the wallet sent ends in exactly one place, and the case says where: an exchange, a sanctioned address, a hub, past the hop limit, or not moved.
- **Stops** at any labelled address, at hubs (30+ distinct counterparties in one fetch), at the hop limit, and at wallets holding under 1% of the funds. A wallet whose listing could not be read to the end (the adapters page with a cap) is reported as "not followed", never as "the money is still there".
- **Chains:** Tron, Bitcoin, and the EVM chains with a free data source (Ethereum, Polygon, Arbitrum, Base, Optimism). Bitcoin has rules of its own, below.
- **Two numbers, never blended:** `proximity_rank` (hops, then share, then time) and `confidence`.
- **Confidence:** the average over the traced money of *label weight × 0.85^(hops − 1)*, scaled down when the share is under 25%. Label weights: published by the exchange 0.95, curated list 0.85, explorer tag 0.75; a derived deposit address weighs its own confidence. A VASP is named at 0.60 or more.
- **What is calibrated and what is not.** Where the money reached a deposit address the model confirmed, the candidate carries a `confidence_interval` (the model's range through the same formula) and the model's reasons as evidence. The label weights, the hop decay and the share factor are rule-set, so a case confidence is not a calibrated probability end to end; every screen and narrative says which part is which. A candidate without a range is "rule confidence".
- **Outcomes:** `ATTRIBUTED` · `INSUFFICIENT_EVIDENCE` (with the reason and what would change it) · `SANCTIONED_OR_MIXER_REACHED` (1% or more of the funds reached a sanctioned or mixer label).
- Demo wallets are real addresses chosen for their on-chain shape; nothing alleges wrongdoing by their owners. Their traces are recorded in `tests/fixtures/demo/` (`scripts/record_demo_fixtures.py`) and replay with no network.
- Offline replay must pick the same EVM backend as the run that filled the cache: set `ETHERSCAN_API_KEY` to any non-empty value (it is never sent when `OFFLINE=1`).

## Bitcoin
A Bitcoin transaction has many inputs and many outputs and does not say which input paid which output. Three rules turn it into something the trace can follow, and none of them guesses.

- **Pro rata.** An address that put in `v` of a transaction's `V` input value sent each output `v / V` of that output's value, rounded down to a satoshi. Outputs back to one of the transaction's own input addresses are change, not transfers. **No change heuristic is used**: an output to any other address is followed like a payment. The miner fee is what is left, and is its own slice of "where the funds went" (`fee`).
- **Cluster labels** (`vaspfusion/cluster.py`). The inputs of one transaction are signed by one owner, so an address that was spent together with a labelled exchange address belongs to that exchange. That is how an exchange's deposit addresses are found on Bitcoin: they are swept together with its own wallets. The traced wallet, and every unlabelled wallet that received 1% or more of the funds, is checked on its own most recent page of transactions (the page the trace reads anyway). The label is `derived`, source `vaspfusion-cluster`, and its evidence says "cluster of N addresses, M labelled", the labelled address in full, and the linking transaction. Confidence = the weight of the strongest labelled member × 0.90 (hand-set, not calibrated). Two owners in one cluster give no label.
- **CoinJoin.** A transaction with the shape of a CoinJoin is left out of the clustering, and a wallet's coins that enter one go into a sink (`coinjoin:<txid>`) named as a mixer: the trace stops there.

`graph/resolve.py` (BTC-FUSION's clustering) is reused with its change heuristic switched off: "this output was never seen before" cannot be checked from one address's page, and a wrong guess would put an exchange's label on its customer.

**The CoinJoin rule, measured on real transactions (2 Oct 2026).** BTC-FUSION's rule had only been measured on generated data. On the pages of the Wasabi 1.x coordinator's fee address it recognised **1 of 99** real rounds (it asks for the equal outputs to be half of all outputs; in real rounds they are 26% to 51%). With the equal outputs at a quarter of all outputs, five or more of them, and not dust, it recognises **99 of 99**, and flags **1 of 7,334** transactions read from the pages of 460 labelled exchange addresses (a 2014 transaction with five outputs of exactly 1 BTC). Not measured: Wasabi 2 and JoinMarket rounds.

**The demo case** (`btc-htx`, real): `bc1qw75rzzczmu2ulmjnrat3kn8h2rrrlr6wt7q3x6` sent 0.364594 BTC on 1 Oct 2026 to `19vP8bkaR5K9K5W12QyHoYd7TZpz16BxSV`, which no list names. That address was spent together with 287 others in 9 transactions, one of them `1AQLXAB6aXSVbRMjbhSBudLf1kcsbWSEjg`, which HTX published in its proof of reserves: ATTRIBUTED → HTX, rule confidence 0.855, and still HTX without the cluster label (the sweep itself pays HTX's published wallet).

**Limits.** The trace follows addresses, not individual coins: where an address holds other money too, "first out after arrival" is a convention. A cluster is read from one page (the 25 to 50 most recent transactions of the address). Outputs with no address form (pay-to-pubkey, bare multisig) are not followed. The 0.60 bar has not been measured on Bitcoin. mempool.space did not resolve from the development network on 2 Oct 2026, which is why blockstream.info is the default backend.
