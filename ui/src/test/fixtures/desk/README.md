# Recorded answers of the request desk

Each file is what the real API answered on 3 Oct 2026 (code `b5-bitcoin-1`), on the real demo cases after `OFFLINE=1 make demo`, with a desk store of its own. The wallets, labels, amounts, transaction hashes and directory facts are real; the officer's line ("Insp. A. Rao, Cyber PS") is the one the backend's own tests use. The demo wallets are the set in `demo/cases.json`, which alleges nothing about their owners.

| file | what it is |
|---|---|
| `desk-before.json` | `GET /api/desk` before any request: Bitget, CoinDCX and HTX, all "not requested" |
| `vasp-CoinDCX-before.json`, `vasp-Bitget.json` | `GET /api/vasps/<name>`: cited directory facts, wallets across cases (one of CoinDCX's is context only, 0.33) |
| `requests-before.json` | `GET /api/requests`: empty |
| `request-drafted.json` | `POST /api/requests` for CoinDCX over two cases, all four asks: a draft with its watermark and review notes |
| `request-approved.json` | the same after `PATCH {status: approved}` |
| `request-sent.json` | the same after `PATCH {status: sent}`: `due`, the gateway receipt |
| `request-htx-drafted.json` | a draft to HTX: an unlabelled wallet named because it passed everything on, seven review notes |
| `desk-after.json`, `vasp-CoinDCX-after.json`, `vasp-HTX.json`, `requests-after.json` | the same routes after those two requests |

They are test data for the interface only. Nothing reads them at runtime.

To refresh after a deliberate backend change: start the API on throwaway desk and outbox stores and run `record.py` (its docstring has the commands). `record.py --more` adds the approved and the withdrawn request that the `desk-live-*` screenshots show.
