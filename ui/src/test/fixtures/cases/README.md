# Stored results of real demo wallets

Each file is `GET /api/cases/<id>` as the API answered it on 2 Oct 2026 (code `b5-bitcoin-1`, commit `9e7038d`), after `OFFLINE=1 make demo`. The wallets, labels, transfers and transaction hashes are real; the wallets are the demo set in `demo/cases.json`, which alleges nothing about their owners.

| file | what it shows |
|---|---|
| `tron-coindcx.json` | ATTRIBUTED, a model-confirmed deposit address one hop away, an exchange that funded the wallet, a lead |
| `tron-htx-coindcx.json` | two exchanges named; one holds without its label, one does not |
| `tron-abstain.json` | INSUFFICIENT_EVIDENCE with an exchange under the bar, five patterns and two leads |
| `tron-ofac.json` | SANCTIONED_OR_MIXER_REACHED with no exchange |
| `eth-bridge.json` | INSUFFICIENT_EVIDENCE: two bridges, 17 wallets, 36 transfers |

They are test data for the interface only. Nothing reads them at runtime.

To refresh after a deliberate backend change: run the API (`make serve`) and save `curl -s localhost:8000/api/cases/<id> | python -m json.tool --indent 1` over each file.
