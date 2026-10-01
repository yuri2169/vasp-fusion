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
| `vaspfusion/explain/case_narrative.py` | The paragraph an officer reads |
| `vaspfusion/cases.py`, `vaspfusion/store/cases.py` | `run_case` → the API's `CaseDetail`; cases in `data/case.duckdb` |
| `vaspfusion/api/` | `schemas.py` (the contract) and `main.py` (routes; cases and labels are live, the rest answer from mocks until their phase lands) |
| `vaspfusion/{graph,features,detect,eval}/`, `explain/{narrative,report}.py`, `store/dao.py` | Carried over from BTC-FUSION |
| `demo/cases.json` | Six real demo wallets and the result each must give |
| `docs/api_contract.md` | Endpoints, conventions, mock rules |
| `docs/plans/` | Per-phase implementation plans |
| `mocks/` | Demo fixtures for the UI track (labelled addresses real, the rest synthetic, all marked `_demo`) |

## Label store
One row per `(address, chain)`: `entity, category, kind, tier, source, source_url, label`, plus `confidence` and `evidence` on `derived` rows.
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

## Trace and attribution
```bash
python -m vaspfusion.cli trace <address> [--chain ..] [--max-hops 1-5] [--since ISO] [--json] [--save]
```
- **One asset is followed:** the stablecoin the wallet sent most of, else the native coin. Unknown tokens are never followed (this is what keeps address-poisoning spoofs out). Whatever else the wallet sent is listed as "not followed".
- **Allocation, "first out after arrival":** money that reached a wallet at time *t* is assigned to that wallet's next outgoing transfers at or after *t*, in time order. So every unit the wallet sent ends in exactly one place, and the case says where: an exchange, a sanctioned address, a hub, past the hop limit, or not moved.
- **Stops** at any labelled address, at hubs (30+ distinct counterparties in one fetch), at the hop limit, and at wallets holding under 1% of the funds. A wallet whose listing could not be read to the end (the adapters page with a cap) is reported as "not followed", never as "the money is still there".
- **Chains:** Tron and the EVM chains with a free data source (Ethereum, Polygon, Arbitrum, Base, Optimism). Bitcoin tracing arrives with B5.
- **Two numbers, never blended:** `proximity_rank` (hops, then share, then time) and `confidence`.
- **Confidence is rule-based and not calibrated** (B6 replaces it): the average over the traced money of *tier weight × 0.85^(hops − 1)*, scaled down when the share is under 25%. Tier weights: published by the exchange 0.95, curated list 0.85, explorer tag 0.75, derived 0.60. A VASP is named at 0.60 or more.
- **Outcomes:** `ATTRIBUTED` · `INSUFFICIENT_EVIDENCE` (with the reason and what would change it) · `SANCTIONED_OR_MIXER_REACHED` (1% or more of the funds reached a sanctioned or mixer label).
- Demo wallets are real addresses chosen for their on-chain shape; nothing alleges wrongdoing by their owners. Their traces are recorded in `tests/fixtures/demo/` (`scripts/record_demo_fixtures.py`) and replay with no network.
- Offline replay must pick the same EVM backend as the run that filled the cache: set `ETHERSCAN_API_KEY` to any non-empty value (it is never sent when `OFFLINE=1`).
