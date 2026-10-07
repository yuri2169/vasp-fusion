"""Drive the whole demo through the HTTP API and fail loudly if any step is off.

    python scripts/docker_smoke.py --serve          # start the server here, then test it
    python scripts/docker_smoke.py --url http://127.0.0.1:8000 [--read-only]

`make docker-smoke` runs the first form inside a container started with
`--network none`, so everything below is proved to work with no network at all:
sign in, the thirteen demo cases, the case file PDF, the receipt, verify, a fresh trace
from the cache, a refusal for a wallet that is not cached, the request desk, a
request drafted, approved and sent to the mock outbox, label search, the model page,
the audit log and its hash chain.

Standard library only: this file is copied into the image, which has no test tools.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _unlabelled_tron_address() -> str:
    """A well-formed Tron address made from a hash: no label, and in no cache."""
    import hashlib
    body = b"\x41" + hashlib.sha256(b"vaspfusion-smoke: not cached").digest()[:20]
    raw = body + hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n, out = int.from_bytes(raw, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = alphabet[r] + out
    return out


UNCACHED = _unlabelled_tron_address()


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None):
        """(status, headers, parsed JSON or raw bytes)."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.opener.open(req, timeout=120) as r:
                status, headers, raw = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            status, headers, raw = e.code, e.headers, e.read()
        if "json" in (headers.get("content-type") or ""):
            return status, headers, json.loads(raw)
        return status, headers, raw


class Smoke:
    def __init__(self, api: Api, read_only: bool):
        self.api, self.read_only, self.n = api, read_only, 0

    def ok(self, what: str, cond: bool, got=None) -> None:
        self.n += 1
        if not cond:
            print(f"FAIL  {what}" + (f"\n      got: {str(got)[:600]}" if got is not None else ""))
            raise SystemExit(1)
        print(f"  ok  {what}")

    def wait_done(self, case_id: str, seconds: float = 120) -> dict:
        deadline = time.monotonic() + seconds
        while True:
            _, _, case = self.api.call("GET", f"/api/cases/{case_id}")
            if case["status"] in ("done", "failed") or time.monotonic() > deadline:
                return case
            time.sleep(0.5)

    def run(self) -> None:
        api, ok = self.api, self.ok
        specs = json.loads((ROOT / "demo" / "cases.json").read_text())["cases"]
        golden = json.loads((ROOT / "tests" / "golden" / "fingerprints.json").read_text())
        officer = json.loads((ROOT / "demo" / "officer.json").read_text())
        hero = specs[0]

        s, _, health = api.call("GET", "/api/health")
        ok("the server is up, with its label database", s == 200 and health["label_db"], health)
        ok("it runs offline (OFFLINE=1)", health["offline"] is True, health)
        ok("a login is required", health["auth_required"] is True, health)
        s, _, body = api.call("GET", "/api/cases")
        ok("no case is shown before signing in (401)", s == 401, (s, body))
        s, _, body = api.call("POST", "/api/auth/login",
                              {"username": officer["username"], "password": "not the password"})
        ok("a wrong password is refused (401)", s == 401, (s, body))
        s, _, body = api.call("POST", "/api/auth/login",
                              {"username": officer["username"], "password": officer["password"]})
        ok(f"the demo officer signs in ({officer['username']})",
           s == 200 and body["officer"]["username"] == officer["username"], (s, body))
        s, _, page = api.call("GET", "/")
        ok("the interface (or the console) is served at /",
           s == 200 and b"<title" in page.lower(), s)
        if b'id="root"' in page:          # the image was built with the interface (UI=build)
            import re
            scripts = re.findall(rb'src="(/assets/[^"]+\.js)"', page)
            s, h, js = api.call("GET", scripts[0].decode()) if scripts else (0, {}, b"")
            ok("the interface's script is served, to be kept by the browser",
               s == 200 and len(js) > 10_000 and "immutable" in h.get("cache-control", ""),
               (s, len(js), h.get("cache-control")))
            ok("it carries no demo fixture", b"demo-tron-okx" not in js)
            s, _, deep = api.call("GET", "/cases/tron-coindcx")
            ok("an address inside the interface opens the interface (a reload works)",
               s == 200 and b'id="root"' in deep, s)

        s, h, cases = api.call("GET", "/api/cases")
        # the demo cases, and the wallets the demonstration watchlist had traced for it
        watched = [w["trace"]["id"] for w in
                   json.loads((ROOT / "demo" / "watchlist.json").read_text())["watch"] if w.get("trace")]
        ok(f"only real recorded cases are listed ({len(cases['items'])}), no fixture",
           h.get("x-data-source") == "live"
           and sorted(c["id"] for c in cases["items"]) == sorted([s_["id"] for s_ in specs] + watched)
           and not any(c["id"].startswith("demo-") for c in cases["items"]),
           (h.get("x-data-source"), [c["id"] for c in cases["items"]]))
        by_id = {c["id"]: c for c in cases["items"]}
        s, _, watch = api.call("GET", "/api/watchlist")
        ok(f"the demonstration watchlist is there ({len(watch['items'])} wallets), each with a first check",
           s == 200 and len(watch["items"]) == 5 and all(w["last_checked_at"] for w in watch["items"]),
           [(w["address"], w["last_checked_at"]) for w in watch["items"]])
        s, _, fx = api.call("GET", "/api/fx")
        ok("the rupee reference rate is served with its date and source",
           s == 200 and fx["rate"] > 0 and fx["as_of"] and fx["source_url"].startswith("https://"), fx)

        for spec in specs:
            c = by_id.get(spec["id"], {})
            ok(f"demo case {spec['id']}: {spec['expect']['outcome']}"
               + (f" -> {spec['expect']['top_vasp']}" if spec["expect"]["top_vasp"] else ""),
               (c.get("status"), c.get("outcome"), c.get("top_vasp")) ==
               ("done", spec["expect"]["outcome"], spec["expect"]["top_vasp"]), c)

        for spec in specs:
            s, _, receipt = api.call("GET", f"/api/cases/{spec['id']}/receipt")
            ok(f"{spec['id']}: the receipt carries the golden fingerprint",
               s == 200 and receipt["findings_sha256"] == golden[spec["id"]]["findings_sha256"],
               (s, receipt if s != 200 else receipt["findings_sha256"]))
            s, _, verify = api.call("POST", f"/api/cases/{spec['id']}/verify")
            ok(f"{spec['id']}: verified from the cache ({len(verify.get('checks', []))} checks)",
               s == 200 and verify["matches"] is True, (s, verify))

        # what the trace saw against what it followed, and the rest of it as context
        s, _, dense = api.call("GET", "/api/cases/tron-abstain")
        seen = dense.get("trace_summary") or {} if s == 200 else {}
        ok(f"tron-abstain: the trace says what it saw ({seen.get('text', '')[:44]}...)",
           s == 200 and 0 < seen["transfers_followed"] < seen["transfers_seen"]
           and seen["wallets_not_followed"] == sum(r["count"] for r in seen["not_followed"]),
           (s, seen))
        s, _, context = api.call("GET", "/api/cases/tron-abstain/context")
        ok(f"tron-abstain: its other {context.get('transfers')} transfers come back as context, "
           "from the cache alone",
           s == 200 and context["recorded"] is True
           and context["transfers"] == seen["transfers_seen"] - seen["transfers_followed"]
           and len(context["edges"]) == context["transfers"], (s, str(context)[:200]))

        # a bridge deposit followed onto another chain, from the recorded answers alone
        s, _, bridged = api.call("GET", "/api/cases/eth-bridge")
        legs = [x for x in bridged.get("crossings", []) if x["status"] == "followed"] \
            if s == 200 else []
        ok(f"eth-bridge: {len(legs)} Across deposits are followed from Ethereum onto Base, "
           "with no network",
           s == 200 and bridged["chains"] == ["ethereum", "base"] and len(legs) == 2
           and all(x["matched_by"] == "app.across.to" and x["dest_chain"] == "base"
                   and bridged["tx_chains"].get(x["payout_tx"]) == "base" for x in legs),
           (s, bridged.get("chains") if s == 200 else bridged))

        s, headers, pdf = api.call("GET", f"/api/cases/{hero['id']}/pdf")
        ok(f"the case file of {hero['id']} is a PDF ({len(pdf):,} bytes)",
           s == 200 and pdf[:5] == b"%PDF-" and hero["address"].encode() in pdf
           and golden[hero["id"]]["findings_sha256"].encode() in pdf, (s, headers.get("content-type")))
        _, _, again = api.call("GET", f"/api/cases/{hero['id']}.pdf")
        ok("the same case gives the same bytes", again == pdf)

        s, _, desk = api.call("GET", "/api/desk")
        rows = {r["vasp"]: r for r in desk["rows"]}
        ok("the desk groups the demo wallets by exchange (Bitget, CoinDCX, HTX)",
           s == 200 and {"Bitget", "CoinDCX", "HTX"} <= set(rows), list(rows))
        s, _, vasp = api.call("GET", "/api/vasps/CoinDCX")
        ok("the CoinDCX page has its cited legal name",
           s == 200 and vasp["directory"]["legal_name"] == "Neblio Technologies Private Limited",
           vasp.get("directory"))
        s, _, found = api.call("GET", "/api/labels/search?q=coindcx&chain=tron&limit=5")
        # The image holds the full label database, or (built from a clone without the label
        # sets, `make demo-labels`) only the labels the recorded demo read. Either way the
        # search must find CoinDCX's; the full one holds over a hundred of them.
        _, _, held = api.call("GET", "/api/labels/coverage")
        full = held.get("total", 0) > 1000
        ok(f"label search works ({found.get('total')} CoinDCX labels on Tron; "
           f"{'the full label database' if full else 'the recorded demo labels only'}, "
           f"{held.get('total')} labels)",
           s == 200 and found["total"] > (100 if full else 0)
           and all(i["entity"] == "CoinDCX" for i in found["items"]),
           (s, found.get("total"), held.get("total")))
        s, _, model = api.call("GET", "/api/model")
        ok("the model page has measured figures and the abstain check",
           s == 200 and model["status"] == "measured" and model["abstain"] is not None,
           (s, model.get("status")))

        if not self.read_only:
            s, _, queued = api.call("POST", "/api/cases?refresh=true", {"address": hero["address"]})
            ok("a traced wallet can be traced again", s == 202 and queued["id"] == hero["id"],
               (s, queued))
            fresh = self.wait_done(hero["id"])
            ok("...from the cache, with the same fingerprint",
               fresh["status"] == "done" and fresh["provenance"]["offline_replay"] is True
               and fresh["provenance"]["findings_sha256"] == golden[hero["id"]]["findings_sha256"],
               (fresh["status"], fresh.get("error"), fresh["provenance"]))

            s, _, queued = api.call("POST", "/api/cases", {"address": UNCACHED})
            ok("a wallet that is not in the cache is accepted for tracing", s == 202, (s, queued))
            failed = self.wait_done(queued["id"])
            ok("...and fails saying it is not cached, instead of guessing or fetching",
               failed["status"] == "failed" and "not cached" in (failed.get("error") or ""),
               (failed["status"], failed.get("error")))

            s, _, req = api.call("POST", "/api/requests", {
                "vasp": "CoinDCX", "case_ids": ["tron-coindcx", "tron-htx-coindcx"],
                "asks": ["kyc", "freeze"], "officer": officer["name"]})
            ok("one request to CoinDCX is drafted for both cases",
               s == 201 and req["status"] == "drafted" and len(req["letter"]["wallets"]) == 2
               and req["status_history"][0].get("by") == officer["username"], (s, req))
            rid = req["id"]
            s, _, body = api.call("PATCH", f"/api/requests/{rid}", {"status": "sent"})
            ok("a draft cannot be sent before it is approved (409)", s == 409, (s, body))
            s, _, body = api.call("PATCH", f"/api/requests/{rid}", {"status": "approved"})
            ok("it is approved", s == 200 and body["letter"]["watermark"] is None, (s, body))
            s, _, sent = api.call("PATCH", f"/api/requests/{rid}", {"status": "sent"})
            ok("it is sent to the mock SAHYOG outbox (nothing leaves the machine)",
               s == 200 and sent["receipt"]["gateway"] == "mock-outbox", (s, sent.get("receipt")))
            s, _, letter = api.call("GET", f"/api/requests/{rid}/pdf")
            ok(f"the letter is a PDF ({len(letter):,} bytes)",
               s == 200 and letter[:5] == b"%PDF-", s)

        # --- the problem statement, risk, and the SAHYOG round trip on the simulator (G2)
        s, _, cov = api.call("GET", "/api/coverage")
        ok(f"the coverage page lists the problem statement ({cov.get('total')} lines: "
           f"{cov.get('counts')})",
           s == 200 and cov["total"] == len(cov["rows"]) == sum(cov["counts"].values())
           and all(r["gap"] for r in cov["rows"] if r["status"] != "built"), (s, cov.get("counts")))
        s, _, ofac = api.call("GET", "/api/cases/tron-ofac")
        s2, _, quiet = api.call("GET", f"/api/cases/{hero['id']}")
        ok("the sanctioned case is Severe and the attributed one is not, each with its reasons",
           s == s2 == 200 and ofac["risk"]["risk_class"] == "severe" and ofac["risk"]["indicators"]
           and quiet["risk"]["risk_class"] != "severe"
           and "Not a probability" in ofac["risk"]["basis"], (ofac.get("risk"), quiet.get("risk")))
        s, _, sim = api.call("GET", "/api/sahyog-sim")
        ok("the simulator is on, and says it is a simulator",
           s == 200 and sim["enabled"] and "Not the SAHYOG portal" in sim["notice"], (s, sim))
        if not self.read_only:
            s, _, body = api.call("POST", "/api/sahyog/complaints", {
                "complaint_ref": "SMOKE-0001", "agency": "smoke", "officer": "smoke",
                "wallets": [{"address": hero["address"]}]})
            ok("the intake refuses a caller without its API key (401)", s == 401, (s, body))
            s, _, filed = api.call("POST", "/api/sahyog-sim/complaints", {
                "complaint_ref": "SMOKE-0001", "agency": "smoke test", "officer": "smoke test",
                "wallets": [{"address": hero["address"]}, {"address": "not-a-wallet"}]})
            good = filed["wallets"][0] if s == 202 else {}
            ok("a complaint filed in the simulator has a case and a result; the bad address "
               "is refused by name",
               s == 202 and good.get("case_id") == hero["id"] and good.get("status") == "result"
               and good.get("top_vasp") == hero["expect"]["top_vasp"]
               and good.get("result_sent_at") and filed["wallets"][1]["accepted"] is False
               and "not-a-wallet" in filed["wallets"][1]["error"], (s, filed))
            s, _, case = api.call("GET", f"/api/cases/{hero['id']}")
            ok("the case says it was reported through SAHYOG",
               case.get("sahyog_complaint_ref") == "SMOKE-0001", case.get("sahyog_complaint_ref"))
            if b'id="root"' in page:
                s, _, ack = api.call("POST", f"/api/sahyog-sim/requests/{rid}/reply",
                                     {"status": "freeze_confirmed", "note": "smoke test"})
                s2, _, after = api.call("GET", f"/api/requests/{rid}")
                ok("the exchange's side confirms the freeze and the desk reads it",
                   s == 200 and ack["status"] == "freeze_confirmed"
                   and after["status"] == "freeze_confirmed"
                   and after["status_history"][-1].get("via") == "sahyog", (s, ack))

        s, _, scale = api.call("GET", "/api/scale")
        ok("the measured throughput is served from the bench file, with what limits it",
           s == 200 and scale["status"] == "measured"
           and [r["workers"] for r in scale["runs"]] == [1, 2, 4, 8] and scale["limits"]
           and scale["machine"], (s, str(scale)[:300]))
        if not self.read_only:
            rows = "address,chain,case_ref\n" + "".join(
                f"{sp['address']},{sp['chain']},SMOKE/{i}\n" for i, sp in enumerate(specs[:3], 1)
            ) + "not-a-wallet,,SMOKE/4\n"
            s, _, batch = api.call("POST", "/api/cases/batch", {"name": "smoke", "csv": rows})
            ok("a batch is accepted row by row: three wallets get their case, the bad row is "
               "kept with its reason",
               s == 202 and batch["progress"]["accepted"] == 3 and batch["progress"]["refused"] == 1
               and [r["case_id"] for r in batch["rows"][:3]] == [sp["id"] for sp in specs[:3]]
               and "chain" in (batch["rows"][3]["error"] or ""), (s, str(batch)[:400]))
            s, _, done = api.call("GET", f"/api/batches/{batch.get('id')}")
            ok("the batch's table has each wallet's result",
               s == 200 and done["progress"]["finished"] and done["progress"]["done"] == 3
               and [r["outcome"] for r in done["rows"][:3]]
               == [sp["expect"]["outcome"] for sp in specs[:3]]
               and done["rows"][0]["top_vasp"] == hero["expect"]["top_vasp"], (s, str(done)[:400]))
            s, headers, table = api.call("GET", f"/api/batches/{batch.get('id')}/results.csv")
            ok("...and downloads as CSV",
               s == 200 and "text/csv" in headers.get("content-type", "")
               and table.decode().splitlines()[0].startswith("row,wallet,chain")
               and len(table.decode().splitlines()) == 5, (s, table[:200]))

        s, _, audit = api.call("GET", "/api/audit?limit=500&verify=true")
        actions = [(a["officer"], a["action"], a["status"]) for a in audit["items"]]
        ok(f"the audit log has it all ({audit['total']} rows)",
           s == 200 and (None, "case.list", 401) in actions
           and (None, "auth.login", 401) in actions
           and (officer["username"], "case.export", 200) in actions
           and (officer["username"], "case.verify", 200) in actions, actions[:12])
        ok("the audit log's hash chain is intact", audit["chain"]["ok"] is True, audit["chain"])
        if not self.read_only:
            ok("...including who drafted, approved and sent the request",
               [a for a in actions if a[1] in ("request.draft", "request.status")][::-1] ==
               [(officer["username"], "request.draft", 201),
                (officer["username"], "request.status", 409),
                (officer["username"], "request.status", 200),
                (officer["username"], "request.status", 200)], actions)
        s, _, _ = api.call("POST", "/api/auth/logout")
        s2, _, _ = api.call("GET", "/api/cases")
        ok("signing out ends the session", s == 200 and s2 == 401, (s, s2))
        print(f"PASS: {self.n} checks")


def wait_up(base: str, seconds: float = 90) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            urllib.request.urlopen(base + "/api/health", timeout=3)
            return
        except OSError:
            if time.monotonic() > deadline:
                raise SystemExit(f"FAIL  the server did not answer at {base} in {seconds:.0f} s")
            time.sleep(0.5)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--serve", action="store_true", help="start the server here first")
    p.add_argument("--read-only", action="store_true",
                   help="skip the steps that write (a new trace, a request)")
    args = p.parse_args()
    server = None
    if args.serve:
        port = args.url.rsplit(":", 1)[-1].strip("/")
        server = subprocess.Popen([sys.executable, "-m", "vaspfusion.cli", "serve",
                                   "--host", "127.0.0.1", "--port", port],
                                  cwd=ROOT, env=os.environ.copy(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up(args.url)
        Smoke(Api(args.url), args.read_only).run()
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=20)


if __name__ == "__main__":
    main()
