"""Record the desk flow on the real demo cases from a running API, as test fixtures for the interface.

    make demo                 # the demo cases, in stores of their own (see README.md)
    make serve                # or any port: API=http://localhost:8010/api
    python ui/src/test/fixtures/desk/record.py            # writes the JSON files beside this script
    python ui/src/test/fixtures/desk/record.py --more     # only the two extra requests the screenshots show

It drafts, approves and sends real requests, so point the API at a desk store you can throw away
(VASPFUSION_DESK_DB, VASPFUSION_SAHYOG_OUTBOX). Nothing leaves the machine: the gateway is a local outbox.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

API = os.environ.get("API", "http://localhost:8000/api")
OUT = Path(__file__).parent
OFFICER = "Insp. A. Rao, Cyber PS"
ALL = ["kyc", "transactions", "freeze", "preservation"]


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
    save("desk-before", call("GET", "/desk"))
    save("vasp-CoinDCX-before", call("GET", "/vasps/CoinDCX"))
    save("vasp-Bitget", call("GET", "/vasps/Bitget"))
    save("requests-before", call("GET", "/requests"))

    draft = save("request-drafted", call("POST", "/requests", {
        "vasp": "CoinDCX", "case_ids": ["tron-coindcx", "tron-htx-coindcx"], "asks": ALL,
        "officer": OFFICER}))
    rid = draft["id"]
    save("request-approved", call("PATCH", f"/requests/{rid}",
                                  {"status": "approved", "note": "Checked against the case files"}))
    save("request-sent", call("PATCH", f"/requests/{rid}", {"status": "sent"}))
    save("request-htx-drafted", call("POST", "/requests", {
        "vasp": "HTX", "case_ids": ["tron-htx-coindcx"], "asks": ["kyc", "transactions"],
        "officer": OFFICER}))
    save("desk-after", call("GET", "/desk"))
    save("vasp-CoinDCX-after", call("GET", "/vasps/CoinDCX"))
    save("vasp-HTX", call("GET", "/vasps/HTX"))
    save("requests-after", call("GET", "/requests"))


def more():
    """An approved request and a withdrawn draft, so the screenshots of the desk and the
    register show every kind of row. Not saved as fixtures."""
    bitget = call("POST", "/requests", {"vasp": "Bitget", "case_ids": ["eth-bitget"], "asks": ALL,
                                        "officer": OFFICER})
    call("PATCH", f"/requests/{bitget['id']}",
         {"status": "approved", "note": "Checked against the case file"})
    htx = call("POST", "/requests", {"vasp": "HTX", "case_ids": ["btc-htx"], "asks": ["kyc"],
                                     "officer": OFFICER})
    call("PATCH", f"/requests/{htx['id']}",
         {"status": "withdrawn", "note": "Drafted with the wrong asks"})


if __name__ == "__main__":
    if "--more" in sys.argv:
        more()
    else:
        record()
    for row in call("GET", "/desk")["rows"]:
        print(row["vasp"], row["status"], "|", row["next_action"])
