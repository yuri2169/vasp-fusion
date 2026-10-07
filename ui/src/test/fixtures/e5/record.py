"""Record the E5 screens' answers from a running API, as test fixtures for the interface.

    OFFLINE=1 make demo       # the demo cases, in stores of their own
    make serve                # or any port: API=http://localhost:8015/api
    python ui/src/test/fixtures/e5/record.py

It traces the two-exchange case again through the server (so the trace queue and the audit
log hold its events), makes a letter-of-request draft for HTX, and drafts, approves and
sends a request to CoinDCX with a reply day ten days on. Point the API at stores you can
throw away (VASPFUSION_CASE_DB, VASPFUSION_DESK_DB, VASPFUSION_AUDIT_DB,
VASPFUSION_SAHYOG_OUTBOX). Nothing leaves the machine.
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = os.environ.get("API", "http://localhost:8000/api")
OUT = Path(__file__).parent
OFFICER = "Insp. A. Rao, Cyber PS"
CASE = "tron-htx-coindcx"


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def save(name, data):
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1) + "\n")
    return data


def record():
    case = call("GET", f"/cases/{CASE}")
    call("POST", "/cases?refresh=true", {"address": case["address"], "chain": case["chain"],
                                          "case_ref": case["case_ref"]})
    while call("GET", f"/cases/{CASE}")["status"] != "done":
        time.sleep(0.3)
    save("case-before", call("GET", f"/cases/{CASE}"))
    query = urllib.parse.urlencode({"officer": OFFICER, "cases": CASE})
    save("letter-of-request-HTX", call("GET", f"/vasps/HTX/letter-of-request?{query}"))
    made = call("POST", "/requests", {"vasp": "CoinDCX", "case_ids": [CASE],
                                      "asks": ["kyc", "transactions"], "officer": OFFICER})
    call("PATCH", f"/requests/{made['id']}", {"status": "approved"})
    due = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
    call("PATCH", f"/requests/{made['id']}", {"status": "sent", "due": due})
    save("case-after", call("GET", f"/cases/{CASE}"))
    save("desk-after", call("GET", "/desk"))


if __name__ == "__main__":
    record()
    print(f"wrote {len(list(OUT.glob('*.json')))} fixtures to {OUT}")
