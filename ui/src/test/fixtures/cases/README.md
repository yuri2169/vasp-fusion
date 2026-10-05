# Stored results of real demo wallets

Each file is `GET /api/cases/<id>` as the API answered it on 2 Oct 2026 (code `b5-bitcoin-1`, commit `9e7038d`), after `OFFLINE=1 make demo`. The wallets, labels, transfers and transaction hashes are real; the wallets are the demo set in `demo/cases.json`, which alleges nothing about their owners.

| file | what it shows |
|---|---|
| `tron-coindcx.json` | ATTRIBUTED, a model-confirmed deposit address one hop away, an exchange that funded the wallet, a lead |
| `tron-htx-coindcx.json` | two exchanges named; one holds without its label, one does not |
| `tron-abstain.json` | INSUFFICIENT_EVIDENCE with an exchange under the bar, five patterns and two leads |
| `tron-ofac.json` | SANCTIONED_OR_MIXER_REACHED with no exchange |
| `eth-bridge.json` | INSUFFICIENT_EVIDENCE: two Across deposits followed from Ethereum onto Base, one bridge deposit not matched; 21 wallets, 45 transfers. Refreshed 5 Oct 2026 (G4) |

Each carries the `trace_summary` the API gave for it on 5 Oct 2026 (added to the stored result; nothing else in the four older files was refreshed). `../context/tron-coindcx.json` is `GET /api/cases/tron-coindcx/context` of the same day: the 152 transfers that trace read and did not follow.

They are test data for the interface only. Nothing reads them at runtime.

To refresh after a deliberate backend change: run the API (`make serve`) and save `curl -s localhost:8000/api/cases/<id> | python -m json.tool --indent 1` over each file.
