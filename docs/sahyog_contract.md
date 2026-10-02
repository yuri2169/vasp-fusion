# SAHYOG gateway contract

**What this is.** SAHYOG is the I4C portal through which notices reach intermediaries. Its interface is not public, so VASP-FUSION cannot call it. This document is **our side of the contract**: the interface a gateway must implement and the JSON it is handed. It is a proposal for I4C to map onto the real portal, not a description of SAHYOG's API.

**What exists today.** One implementation, `MockSahyogGateway`, which writes the payload and the letter PDF to a folder (`data/sahyog_outbox/`, or `VASPFUSION_SAHYOG_OUTBOX`). **Nothing leaves the machine.** The request's history says so in words: "Written to the SAHYOG outbox (mock-outbox); nothing left this machine".

Code: `vaspfusion/desk/gateway.py` (interface, mock), `vaspfusion/desk/letter.py` (`build_payload`), `vaspfusion/desk/service.py` (when it is called).

## The interface

```python
class SahyogGateway(Protocol):
    name: str
    def submit(self, payload: dict, pdf: bytes, *, now: datetime) -> dict: ...
    def sent_pdf(self, request_id: str) -> bytes | None: ...
```

- Called once, when the officer moves an **approved** request to `sent` (`PATCH /api/requests/{id}` with `status: "sent"`).
- `payload` is the JSON below with `draft: false`. `pdf` is the letter without the draft marks; its SHA-256 is in `payload.documents[0].sha256`.
- Returns a **receipt**: `gateway`, `receipt_id`, `submitted_at` (UTC), `location`, `payload_sha256`. The receipt is stored on the request (`RequestDetail.receipt`).
- Raises `GatewayError` if the payload is a draft or the submission did not go through. The request then stays `approved`, with no due date and no receipt, and the API answers 502.
- **Submitting the same payload and letter again must succeed without sending twice** (the desk may have failed after the first submission and will retry). A different payload under an id already submitted is refused.
- `sent_pdf` returns the letter exactly as submitted, if the gateway keeps it. The desk serves those bytes for a sent request, after checking them against the recorded SHA-256.
- Before a request is approved or sent the desk checks that every wallet in it is still what its case says; a gateway never sees a request whose case has changed since the draft.

A real gateway replaces the mock in one place: `make_gateway()` in `vaspfusion/api/main.py`.

## The payload: `vaspfusion-sahyog-request/1`

Written to the outbox as canonical JSON (sorted keys, UTF-8, no spaces), so `payload_sha256` can be checked by anyone holding the file.

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | `vaspfusion-sahyog-request/1` |
| `request_id` | string | `req-<year>-<number>`, unique on this installation |
| `reference` | string | the reference printed on the letter, `VF/REQ/<year>/<number>` |
| `created_at` | UTC timestamp | when the request was drafted |
| `draft` | bool | `true` until approved. **A gateway must refuse `true`.** |
| `recipient` | object | `vasp` (trade name), `legal_name`, `jurisdiction`, `fiu_ind_registered`, `fiu_ind_as_of`, `channel` (the exchange's own published law-enforcement channel). From `data/vasp_directory.yaml`; `null` where no source was found |
| `officer` | string | who makes the request, as typed |
| `subject` | string | the letter's subject line |
| `cases[]` | objects | `case_id`, `case_ref`, `complaint_no`, `wallet` (the wallet under investigation), `chain` |
| `wallets[]` | objects | one per wallet the exchange is asked about, below |
| `asks[]` | strings | any of `kyc`, `transactions`, `freeze`, `preservation`, in that order |
| `legal_basis` | object | `text` (the line on the letter) and `citations[]` (`section`, `act`, `heading`, `url`) |
| `documents[]` | objects | empty until sent; then the letter: `name`, `media_type`, `sha256` |
| `generated_by` | object | `tool`, `code_version` |

`wallets[]`:

| Field | Meaning |
|---|---|
| `address`, `chain` | the wallet, in full |
| `case_id` | the case it comes from |
| `asset`, `amount` | the traced funds that went through this wallet to the exchange, exact. One row per wallet; the rows of a case add up to what reached the exchange |
| `amount_usd` | the same amount when the asset is a US-dollar stablecoin, else `null` (no price feed) |
| `evidence_tier` | of the label that names the exchange: `published_por`, `curated`, `explorer_tag`, `derived` |
| `confidence` | the case's confidence for this exchange (0 to 1). An assessment, not proof |
| `first_seen` | when the traced funds first reached the wallet (UTC) |
| `tx_hashes[]` | the transactions of the route, in full |
| `paid_into` | set when `address` carries no label itself: the exchange's labelled wallet it passed everything on to |

Example (a real demo wallet, shortened to one wallet):

```json
{
  "schema": "vaspfusion-sahyog-request/1",
  "request_id": "req-2026-0002",
  "reference": "VF/REQ/2026/0002",
  "created_at": "2026-10-02T09:30:00Z",
  "draft": false,
  "recipient": {"vasp": "CoinDCX", "legal_name": "Neblio Technologies Private Limited",
                "jurisdiction": "India", "fiu_ind_registered": true,
                "fiu_ind_as_of": "2023-12-04", "channel": null},
  "officer": "Insp. A. Rao, Cyber PS",
  "subject": "Request for KYC records and a freeze in respect of 1 wallet attributed to CoinDCX (DEMO/2026/104)",
  "cases": [{"case_id": "tron-htx-coindcx", "case_ref": "DEMO/2026/104", "complaint_no": null,
             "wallet": "TGfoGrh8ddh4zzpBe3G82p1tgmeUq49sWr", "chain": "tron"}],
  "wallets": [{"address": "TLUQsVHsmUrcWEy3tGrpEdh2ue8z2NHPYk", "chain": "tron",
               "case_id": "tron-htx-coindcx", "asset": "USDT", "amount": 6000.0,
               "amount_usd": 6000.0, "evidence_tier": "derived", "confidence": 0.8492,
               "first_seen": "2024-07-23T08:44:12Z",
               "tx_hashes": ["a12af76b0c4c89cdc0a316d9dc7f23a72b48844f197c0944effb684461f80dae"],
               "paid_into": null}],
  "asks": ["kyc", "freeze"],
  "legal_basis": {"text": "Notice under Section 94 of the Bharatiya Nagarik Suraksha Sanhita, 2023. ...",
                  "citations": [{"section": "94", "act": "Bharatiya Nagarik Suraksha Sanhita, 2023",
                                 "heading": "Summons to produce document or other thing",
                                 "url": "https://www.indiacode.nic.in/handle/123456789/20099"}]},
  "documents": [{"name": "req-2026-0002.pdf", "media_type": "application/pdf", "sha256": "..."}],
  "generated_by": {"tool": "VASP-FUSION", "code_version": "b9-receipt-1"}
}
```

## What is not in the contract

- **Replies.** The exchange's acknowledgement, answer, freeze confirmation or refusal is recorded by the officer (`PATCH` with the new status and a note). A real gateway could report them; the mock cannot.
- **Identity.** Nothing signs the payload or proves who the officer is. Login and the audit trail are phase B9.
- **Delivery to the exchange.** The directory records each exchange's own published channel (a portal or an address) for the officer's use. The tool does not submit to those channels.

## Legal basis cited

| Section | Act | Heading | Used for |
|---|---|---|---|
| 94 | Bharatiya Nagarik Suraksha Sanhita, 2023 | Summons to produce document or other thing | every request |
| 63 | Bharatiya Sakshya Adhiniyam, 2023 | Admissibility of electronic records | every request (the certificate that must come with electronic records) |
| 106 | Bharatiya Nagarik Suraksha Sanhita, 2023 | Power of police officer to seize certain property | only when a freeze is asked |

Texts: India Code, <https://www.indiacode.nic.in/handle/123456789/20099> (BNSS) and <https://www.indiacode.nic.in/handle/123456789/20063> (BSA). The wording on the letter is a draft for the officer to review. It is not legal advice.
