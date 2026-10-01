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
make model     # train, calibrate and measure the deposit-address model; then `make labels`
```
Contract work: `make mocks` regenerates `mocks/` (seeded), and `make types` regenerates `docs/openapi.json` and `ui/src/api/types.ts`.

## Layout
| Path | What |
|---|---|
| `vaspfusion/labels/` | Label store: normalise → build (tier-ranked dedupe) → lookup/search |
| `vaspfusion/chains/` | Chain adapters (Tron, EVM, BTC basic, Solana stub) behind a cache-first fetcher; the only code that reaches the network |
| `vaspfusion/trace.py` | Bidirectional trace: follows the wallet's money hop by hop, allocating by amount |
| `vaspfusion/attribute/rules.py` | Candidates, proximity rank, rule confidence, the three outcomes |
| `vaspfusion/discover/` | Deposit-address discovery: the sweep and gas-payer rules, the crawler, the hold-out evaluation |
| `derived/` | What discovery found (`<run>.csv`, `<run>_report.json`) and the hold-out result; `make labels` merges the CSVs |
| `vaspfusion/classify/` | The deposit-address model: features, dataset, splits, training + calibration, SHAP reasons, label scores |
| `artifacts/model_v1/<chain>/` | The model's dataset, measurements, plots and label scores (tracked; `model.pkl` is rebuilt by `make model`) |
| `vaspfusion/explain/case_narrative.py` | The paragraph an officer reads |
| `vaspfusion/cases.py`, `vaspfusion/store/cases.py` | `run_case` → the API's `CaseDetail`; cases in `data/case.duckdb` |
| `vaspfusion/api/` | `schemas.py` (the contract) and `main.py` (routes; cases and labels are live, the rest answer from mocks until their phase lands) |
| `vaspfusion/{graph,features,detect,eval}/`, `explain/{narrative,report}.py`, `store/dao.py` | Carried over from BTC-FUSION |
| `demo/cases.json` | Six real demo wallets and the result each must give |
| `docs/api_contract.md` | Endpoints, conventions, mock rules |
| `docs/plans/` | Per-phase implementation plans |
| `mocks/` | Demo fixtures for the UI track (labelled addresses real, the rest synthetic, all marked `_demo`) |

## Label store
One row per `(address, chain)`: `entity, category, kind, tier, source, source_url, label`, plus `confidence` and `evidence` on `derived` rows, and `confidence_low`, `confidence_high` and `model` (the deposit-address model's probability, range and reasons) on the derived rows the model scored.
- Tier priority: `published_por > curated > explorer_tag > derived`. A derived row never replaces a label from another source.
- EVM addresses are lowercased; Tron and BTC keep their case.
- Dune "EVM" rows are stored as chain `evm` and match any EVM chain on lookup.

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
| bitcoin | mempool.space `/api/address/{a}/txs` | – |
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

## Trace and attribution
```bash
python -m vaspfusion.cli trace <address> [--chain ..] [--max-hops 1-5] [--since ISO] [--json] [--save]
```
- **One asset is followed:** the stablecoin the wallet sent most of, else the native coin. Unknown tokens are never followed (this is what keeps address-poisoning spoofs out). Whatever else the wallet sent is listed as "not followed".
- **Allocation, "first out after arrival":** money that reached a wallet at time *t* is assigned to that wallet's next outgoing transfers at or after *t*, in time order. So every unit the wallet sent ends in exactly one place, and the case says where: an exchange, a sanctioned address, a hub, past the hop limit, or not moved.
- **Stops** at any labelled address, at hubs (30+ distinct counterparties in one fetch), at the hop limit, and at wallets holding under 1% of the funds. A wallet whose listing could not be read to the end (the adapters page with a cap) is reported as "not followed", never as "the money is still there".
- **Chains:** Tron and the EVM chains with a free data source (Ethereum, Polygon, Arbitrum, Base, Optimism). Bitcoin tracing arrives with B5.
- **Two numbers, never blended:** `proximity_rank` (hops, then share, then time) and `confidence`.
- **Confidence:** the average over the traced money of *label weight × 0.85^(hops − 1)*, scaled down when the share is under 25%. Label weights: published by the exchange 0.95, curated list 0.85, explorer tag 0.75; a derived deposit address weighs its own confidence. A VASP is named at 0.60 or more.
- **What is calibrated and what is not.** Where the money reached a deposit address the model confirmed, the candidate carries a `confidence_interval` (the model's range through the same formula) and the model's reasons as evidence. The label weights, the hop decay and the share factor are rule-set, so a case confidence is not a calibrated probability end to end; every screen and narrative says which part is which. A candidate without a range is "rule confidence".
- **Outcomes:** `ATTRIBUTED` · `INSUFFICIENT_EVIDENCE` (with the reason and what would change it) · `SANCTIONED_OR_MIXER_REACHED` (1% or more of the funds reached a sanctioned or mixer label).
- Demo wallets are real addresses chosen for their on-chain shape; nothing alleges wrongdoing by their owners. Their traces are recorded in `tests/fixtures/demo/` (`scripts/record_demo_fixtures.py`) and replay with no network.
- Offline replay must pick the same EVM backend as the run that filled the cache: set `ETHERSCAN_API_KEY` to any non-empty value (it is never sent when `OFFLINE=1`).
