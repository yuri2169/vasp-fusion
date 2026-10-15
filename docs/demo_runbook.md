# Demo runbook

How to run the demonstration in front of a jury, what to do when something goes wrong, and
where the answer to each likely question is in this repository. `docs/demo_script.md` has the
original three-minute script with the sentences to say; this runbook adds the screens built
since and the fallbacks. `make demo-flow` (`ui/scripts/demo-flow.mjs`) drives and checks the same
path in a real browser.

## Before the jury arrives
1. Start the tool and the reference portal: `UI=build make docker && make docker-up`, or without
   Docker `make serve-pair` and `make portal` after `make offline-demo` and `make ui-build`.
   Open http://127.0.0.1:8000 and sign in with the demonstration account in `demo/officer.json`.
2. Run `make demo-flow` once against it. It must end with `PASS`. It leaves one request sent
   to CoinDCX, which the dashboard and the desk then show.
3. To start again from a clean desk: `docker compose down -v && make docker-up`.
4. For a live trace (a judge's own address) the tool needs the network and the keys in `.env`
   (`TRONGRID_API_KEY`, `ETHERSCAN_API_KEY`, `HELIUS_API_KEY`), and must run without
   `OFFLINE=1`: `make serve-pair` from a checkout, or the container with `OFFLINE=0` and the keys
   in its environment. The offline image cannot trace a wallet it has not recorded.

## Running order (about five minutes)

| # | Screen | Do | Point at |
|---|---|---|---|
| 1 | Sign in | Sign in. | Every case and request is logged under the officer's name (`make audit` checks the log's hash chain). |
| 2 | SAHYOG simulator | "SAHYOG simulator" in the menu leads to the reference portal's screen (port 8100). Paste `TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c` in "File a complaint", then "Open the case" when its result is in. | The portal is a separate program; it posts the complaint to the tool and gets the result back over signed HTTP. It is a simulator, not SAHYOG, and says so. |
| 3 | Case of `tron-coindcx` | The case the complaint opened. | "Reported through SAHYOG"; the Hop Rail ends at CoinDCX, confidence 0.85; 58% of 2,652.22 USDT reached it in one hop; still named at 0.72 with its strongest label removed. |
| 4 | Same case, Audit tab | "Verify this case". | The wallet is traced again and every figure matches the stored receipt. |
| 5 | Request | "Draft request to CoinDCX", approve, mark as sent. | One A4 letter per exchange (sections 94 BNSS and 63 BSA, 106 BNSS for a freeze); the receipt is the portal's. |
| 6 | Desk, dashboard | Open the request desk, then the dashboard. | CoinDCX sent with its reply day; "Awaiting a reply" went up by one; the map of where the exchanges are registered. |
| 7 | Case `tron-abstain` (DEMO/2026/105) | Open it. **Spend the most time here.** | INSUFFICIENT EVIDENCE: only 10% reached CoinDCX, rule confidence 0.33; no request is offered; the page says what would change that. |
| 8 | Case `tron-ofac` (DEMO/2026/103) | Open it. | 99% of 101,078.34 USDT went straight to an OFAC-listed address; the alert leads the page; the address is also on the issuer's freeze list. |
| 9 | Case `tron-htx-coindcx` (DEMO/2026/104) | Open it. | Two exchanges: who to write to first and why; for HTX, which no source shows as registered with FIU-IND, a letter-of-request draft under section 112 BNSS, not sent. |
| 10 | Case `wazirx-2024` | Open it from the landing page's "A publicly documented case". | The real theft of 18 July 2024: WazirX named as the source, no cash-out exchange named; the request to the issuer of USDT, drafted. |
| 11 | Present mode | "Present" on any case. | The finding, the route, what was left out and why, the handoff: four screens for a briefing. |
| 12 | Model page | Open `/model`. | The six-chain table beside the baseline, Ethereum's poor row included, and the risk check. |

If time is short, keep 1, 3, 5, 7 and 12.

## The wallets

**Recorded (always work, no network):** the thirteen in `demo/cases.json`. Their chain responses
are in `tests/fixtures/demo/`, replayed into `data/demo_cache.duckdb` by `make demo-cache`, and
each must reproduce its fingerprint in `tests/golden/fingerprints.json`.

| Case | Chain | Result |
|---|---|---|
| `tron-coindcx` | Tron | CoinDCX |
| `eth-bitget` | Ethereum | Bitget |
| `tron-ofac` | Tron | Sanctioned address reached |
| `tron-htx-coindcx` | Tron | CoinDCX, also HTX |
| `tron-abstain` | Tron | Insufficient evidence |
| `eth-abstain` | Ethereum | Insufficient evidence |
| `eth-bridge` | Ethereum | Insufficient evidence (60% into the Across bridge) |
| `btc-htx` | Bitcoin | HTX |
| `bnb-coindcx` | BNB Chain | CoinDCX |
| `sol-okx` | Solana | OKX |
| `polygon-bitget` | Polygon | Bitget |
| `tron-terror-link` | Tron | Sanctioned address reached (terrorism financing) |
| `wazirx-2024` | Ethereum | Insufficient evidence (the documented theft) |

**Live:** any other address. It needs the network, the keys and a server without `OFFLINE=1`.
Measured live, one trace at a time, the median was 11 to 21 seconds on the EVM chains, Bitcoin and
Solana (`artifacts/benchmark_v1/summary.json`) and 40.8 seconds on Tron over 8 traces, 5.6 to 67.8
seconds (`artifacts/live_timing.json`). Free API keys are rate-limited; a busy wallet can take
longer.

## If a live trace is slow or comes back empty
- **Say why before switching.** "This is a live read of the chain through free public APIs. While
  it runs, here is the same kind of case recorded earlier." Then open the recorded case of the
  same chain from the table above. The live case keeps running in the queue and can be opened
  from Cases when it finishes.
- **To bound the wait,** lower "Wallets read per direction" and the hop limit on the intake form, or post
  with `max_seconds` (`POST /api/cases`); the case then says where the time budget stopped it.
- **Empty or "nothing to trace":** the wallet has no transfer of an asset the tool follows (USDT
  or USDC; BTC on Bitcoin). Say so; it is a real answer, not an error.
- **Failed:** a provider refused or timed out (HTTP 429 or no answer). The case says which; "Trace
  again" retries. On the offline image a wallet that was never recorded fails the same way,
  because nothing may be fetched.
- **Insufficient evidence** on a judge's address is the tool working as designed; open the
  case's "What would change this" and explain it.

## Letting a judge pick an address
1. Ask for an address on Tron, Ethereum, BNB Chain, Polygon, Arbitrum, Base, Optimism, Bitcoin
   or Solana (the intake form names the chain as soon as the address is pasted, and refuses a
   mistyped one before anything is traced).
2. Make sure the server is live (above). Leave the defaults (3 hops, 40 wallets).
3. Open a case with it, then show steps 3 and 4 of the running order on the result.
4. Say before it finishes: a named exchange is a lead to confirm with the exchange, not proof,
   and on Ethereum about one name in three was wrong when this was measured.
5. Nothing about a judge's wallet leaves the machine except the chain providers' reads. To
   remove the case afterwards, use a scratch store (`VASPFUSION_CASE_DB`) for the demo.

## Questions a jury may ask, and where the answer is

| Question | Short answer | Where |
|---|---|---|
| How often is it right? | Wrong on 15 of 155 named wallets on Tron, 22 of 69 on Ethereum, 2 of 28 on Bitcoin, 0 of 19 on BNB Chain, 0 of 11 on Polygon, 0 of 3 on Solana, with the labels one hop away hidden. | `artifacts/benchmark_v1/summary.json`, `tests/test_benchmark.py` |
| Why not just name the nearest exchange? | That is the baseline; on every chain it names more and is wrong more often (Tron 39 of 248). | `artifacts/benchmark_v1/summary.json` |
| Is the confidence a probability? | No. It orders answers; the deposit-address model inside it is calibrated on Tron (ECE 0.0093). The error at the 0.60 bar is what is quoted. | `artifacts/model_v1/tron/metrics.json`, `artifacts/abstain_v1/tron/validation.json` |
| Is the demo canned? | The recorded cases replay real chain responses; "Verify" traces again and compares digests; a live trace reads the chain. | `tests/golden/fingerprints.json`, `tests/test_verify.py`, `scripts/reproduce.py` |
| Is it connected to SAHYOG? | Not to the real portal, whose interface is not public. It talks to a separate reference portal over signed HTTP, checked by a conformance suite. | `docs/sahyog_contract.md`, `refportal/`, `tests/conformance/test_conformance.py` |
| Which Indian exchanges can it name? | 6 of the 47 on FIU-IND's list as given to Parliament on 2 Dec 2024; CoinDCX in three recorded cases. | `data/indian_exchanges.yaml`, `vaspfusion/labels/india.py` |
| Does the risk score work? | Only through links to listed addresses: 22 of 65 listed wallets and 2 of 65 ordinary ones at High or above with their own label hidden. No pattern rule separates them. | `artifacts/risk_validation_v2/results.json`, `tests/test_risk_validation.py` |
| Has it been tried on a real crime? | The WazirX theft of July 2024, from all 27 tagged wallets: source named, no cash-out exchange reached. | `artifacts/wazirx_2024/trace_table.json`, `data/validation/wazirx_2024.json` |
| How much faster than by hand? | Not measured: the manual timing sheet has not been filled, so no saving is claimed. A complaint of 13 wallets to four drafted freezing requests took 4.3 seconds on recorded data. | `artifacts/manual_timing/sheet.csv`, `artifacts/freeze_readiness.json` |
| Can it freeze money? | No. It drafts the request with a freeze asked (106 BNSS) and tracks the reply; no freeze was made or timed. | `vaspfusion/desk/legal.py`, `data/ps_coverage.yaml` |
| How many cases can it handle? | 900.9 cases a minute with 4 workers on one laptop, replayed; live it is bound by the providers' rate limits. | `artifacts/scale/metrics.json`, `docs/scaling.md` |
| Does it follow money across chains? | Across and Stargate, checked on the destination chain; Wormhole only when redeemed on a chain it reads. | `tests/test_stargate_case.py`, `tests/test_trace_crosschain.py` |
| Where do the labels come from? | Published exchange reserves, curated lists, explorer tags and our own derived deposit addresses, each row with its source; threat tags from cited public lists. | `vaspfusion/labels/load.py`, `data/threat_sources.json`, `config/threats.yaml` |
| Can a case be tampered with? | Each case has a content digest and a receipt; the audit log is hash-chained. | `tests/test_provenance.py`, `tests/test_audit.py` |
| Does it need the internet? | Not for the recorded cases: the image is checked inside a container with no network. | `scripts/docker_smoke.py`, `make offline-check` |
| What does the problem statement ask that it does not do? | Six lines are partly built and each says what is missing; three wait on SAHYOG access. | `data/ps_coverage.yaml`, `tests/test_coverage.py` |
