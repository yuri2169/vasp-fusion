# VASP-FUSION

Given an unknown crypto wallet, find the nearest VASP (exchange, custodial wallet or swap service) that took deposits from it, with a calibrated confidence, an investigation report and a SAHYOG request. SIH 2026 · PS 26182 (MHA / I4C) · Team 112bits.

Forked from our own BTC-FUSION (SIH26146), with the same stack: Python 3.12, FastAPI, Polars, igraph, LightGBM, SHAP and DuckDB; React, Vite, Tailwind and Cytoscape on the front end.

## Quickstart
```bash
make setup     # uv venv (Python 3.12) + install
make labels    # build data/labels.duckdb from ../research/data and print the stats
make test      # pytest
make serve     # API on http://127.0.0.1:8000  (docs at /docs)
```
Contract work: `make mocks` regenerates `mocks/` (seeded), and `make types` regenerates `docs/openapi.json` and `ui/src/api/types.ts`.

## Layout
| Path | What |
|---|---|
| `vaspfusion/labels/` | Label store: normalise → build (tier-ranked dedupe) → lookup/search |
| `vaspfusion/api/` | `schemas.py` (the contract) and `main.py` (routes; mocks until each phase lands) |
| `vaspfusion/{graph,features,detect,attribute,explain,store,eval}/` | Carried over from BTC-FUSION |
| `docs/api_contract.md` | Endpoints, conventions, mock rules |
| `docs/plans/` | Per-phase implementation plans |
| `mocks/` | Demo fixtures for the UI track (labelled addresses real, the rest synthetic, all marked `_demo`) |

## Label store
One row per `(address, chain)`: `entity, category, kind, tier, source, source_url, label`.
- Tier priority: `published_por > curated > explorer_tag > derived`.
- EVM addresses are lowercased; Tron and BTC keep their case.
- Dune "EVM" rows are stored as chain `evm` and match any EVM chain on lookup.

```python
from vaspfusion.labels.lookup import lookup, LabelStore
lookup("TAa8e7U7seCy7NcZ52xYVQXXybFfwvsUxz", "tron")   # Label(entity='Bitget', tier='published_por', ...)
```
