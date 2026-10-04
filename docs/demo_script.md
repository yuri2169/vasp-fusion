# The 3-minute demo

What to click and what to say. The same path is driven and checked by `make demo-flow`
(`ui/scripts/demo-flow.mjs`); the recording of it is `docs/screenshots/final-demo-flow.gif`.
Everything on screen is a real wallet, traced from recorded chain responses, with no network.

Run it: `make labels`, `UI=build make docker`, `make docker-up`, open http://127.0.0.1:8000 and
sign in with the demonstration account in `demo/officer.json`. To start again from a clean desk:
`docker compose down -v && make docker-up`.

The order below is the phase brief's. A mock jury session during U5 asked for the
second case to be given the most time and for four sentences to be said aloud; they are marked **Say**.

| Time | Do | Say |
|---|---|---|
| 0:00 | Sign in. | **Say:** "A complaint gives the officer one wallet. The question is which exchange to write to, and how sure we are. Every action from here is logged under the officer's name." |
| 0:15 | Cases, "Open a case", paste `TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c`, tick "Trace again", "Trace wallet". | **Say:** "This is a real Tron wallet. The trace is instant because it replays recorded chain responses: the demo needs no internet, and I will prove in a moment that it is not canned." |
| 0:30 | The Hop Rail extends to the stamp: ATTRIBUTED, CoinDCX, 0.85. Point at "Where the 2,652.22 USDT went" and at "Why CoinDCX?". | "58% reached a CoinDCX deposit address in one hop. Two separate meters: how near, and how sure. The evidence is in sentences, with the transaction hashes." |
| 0:50 | Point at "Still named with its strongest label removed" and at the line under the meters. | **Say:** "We hid our best clue and traced again: still CoinDCX, at 0.72. And this line is our error, not our accuracy: we name an exchange only at 0.60 or more; with our own labels hidden, 155 of 280 wallets were named and 15 were wrong. It is a lead to confirm with the exchange, not proof." |
| 1:10 | Audit tab, "Verify this case". | "Verify traces the wallet again and compares every figure with the stored receipt, digest for digest." |
| 1:25 | "Draft request to CoinDCX", "Draft request". The A4 letter with its watermark; point at the notes beside it. | "One letter per exchange, under section 94 BNSS and 63 BSA, and 106 BNSS because a freeze is asked. The notes tell the officer what to check before approving, such as: this address was labelled by our own rules." |
| 1:45 | "Approve request", then "Mark as sent". Point at the receipt. "Open letter PDF". | **Say:** "This prototype is not connected to SAHYOG, so this writes the letter and its data to a local outbox, and the officer submits it through the portal. The page says so: nothing left this machine." |
| 2:00 | Request desk (one row per exchange; CoinDCX is Sent, reply due). Dashboard: "Awaiting a reply" is now 1. | "The unit of work is an exchange, not a complaint. Bitget is waiting here with 552,163.80 dollars across its case." |
| 2:10 | Cases, open DEMO/2026/105 (`tron-abstain`). | **Say:** "Here only 10% reached CoinDCX, 0.33. Many tools would name it. Ours says insufficient evidence, offers no request, and says what would change that. A wrong notice costs an officer more than no notice." Stay here. |
| 2:40 | Cases, open DEMO/2026/103 (`tron-ofac`). | "And here 99% of 101,078 USDT went straight to an address on the OFAC list. The alert leads the page." |
| 2:55 | Stop. | If asked: the Model page has every measurement with its caveats; the case file is a PDF with the receipt on its last page; Bitcoin and Ethereum cases are in the list. |

If a juror asks about the 15 wrong: they are on the Model page, "The 0.60 naming bar, checked",
with the notes that say what that test does and does not show.
