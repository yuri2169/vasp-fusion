"""The provenance receipt of a case: what it was computed from, as SHA-256 digests
anyone can recompute, and `verify_case`, which computes the case again and compares.

A receipt answers "is this real, and would I get it again?":

* `input_sha256`      the question asked: wallet, chain, hop limit, start date;
* `responses_sha256`  every chain API response the run read (each page's own SHA-256
                      is listed, so one changed page can be named);
* `label_db_sha256`   the label database file;
* `model_sha256`      the deposit-address model, when the run used it;
* `findings_sha256`   the findings fingerprint: every figure, address and transaction
                      hash of the result, and none of its wording;
* `git_commit`, `code_version`, `seed`   the code that ran.

Digests are taken over canonical JSON: keys sorted, no spaces, floats rounded to six
places (so the last bits of a float cannot differ between machines and still be the
same finding).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
FLOAT_PLACES = 6
RECEIPT_SCHEMA = "vaspfusion-receipt/1"


# ------------------------------------------------------------------ canonical form
def _norm(v):
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return round(v, FLOAT_PLACES) + 0.0          # + 0.0 turns -0.0 into 0.0
    if isinstance(v, Decimal):
        return _norm(float(v))
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    raise TypeError(f"not canonical: {type(v).__name__}")


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(obj) -> str:
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


# ------------------------------------------------------------------ the parts
def case_input(address: str, chain: str, max_hops: int, since: datetime | None) -> dict:
    """The question a case answers. Everything else a trace depends on is code."""
    return {"address": address, "chain": chain, "max_hops": max_hops,
            "since": iso(since) if since is not None else None}


def responses(trail: list[dict]) -> list[dict]:
    """The pages a run read (`Fetcher.trail`), each once, in a fixed order."""
    pages = {(p["query"], p["sha256"]) for p in trail}
    return [{"query": q, "sha256": s} for q, s in sorted(pages)]


def responses_sha256(pages: list[dict]) -> str:
    return sha256_of([[p["query"], p["sha256"]] for p in pages])


def case_headline(case: dict) -> dict:
    """The figures of a case: what a replay, or a later code change, must reproduce.
    (The wording of the narrative is free to improve, so it is not part of this.)"""
    return {
        "outcome": case["outcome"], "top_vasp": case["top_vasp"], "confidence": case["confidence"],
        "asset": case["asset"], "total_sent": case["total_sent"],
        "candidates": [{k: c[k] for k in ("vasp", "direction", "proximity_rank", "confidence",
                                          "confidence_interval", "hops", "share_of_funds",
                                          "deposit_address", "label_tier",
                                          "counterfactual_holds")}
                       for c in case["candidates"]],
        "where_funds_went": case["where_funds_went"],
        "nodes": len(case["graph"]["nodes"]), "edges": len(case["graph"]["edges"]),
        "flags": [[f["code"], f["wallet"], f["figures"]] for f in case["typology_flags"]],
    }


def findings(case: dict) -> dict:
    """Everything a finished case found, without its wording: the headline figures, every
    transfer the money was followed through, the wallets and their labels, the evidence
    hashes behind each candidate, and what a request to each exchange would list."""
    g = case["graph"]
    return {
        "address": case["address"], "chain": case["chain"],
        "headline": case_headline(case),
        "total_received": case.get("total_received"),
        "abstain_reason_given": case.get("abstain_reason") is not None,
        "hop_rail": [[h["tx_hash"], h["from_address"], h["to_address"], h["amount"],
                      h.get("traced_amount")] for h in case["hop_rail"]],
        "wallets": sorted([n["id"], n["role"], n["hop"],
                           (n["label"] or {}).get("entity"), (n["label"] or {}).get("tier")]
                          for n in g["nodes"]),
        "transfers": sorted([e["tx_hash"], e["source"], e["target"], e["asset"], e["amount"],
                             e.get("traced_amount"), e.get("direction", "outbound")]
                            for e in g["edges"]),
        "evidence": [[c["vasp"], c["direction"], c["path"], c.get("amount"),
                      sorted({h for ev in c["evidence"] for h in ev["tx_hashes"]}),
                      [[w["address"], w["amount"], w.get("paid_into"), w["tx_hashes"]]
                       for w in (c.get("request_wallets") or [])]]
                     for c in case["candidates"]],
        "flag_hashes": [[f["code"], f["wallet"], f["severity"], sorted(f["tx_hashes"])]
                        for f in case["typology_flags"]],
    }


def findings_sha256(case: dict) -> str:
    return sha256_of(findings(case))


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


MODEL_FILES = ("model.txt", "model_features.json", "calibration.json")


def model_sha256(model_dir: str | Path) -> str | None:
    """One digest over the files the runtime model is loaded from; None when there is
    no model there."""
    d = Path(model_dir)
    present = [n for n in MODEL_FILES if (d / n).exists()]
    if "model.txt" not in present:
        return None
    return sha256_of([[n, file_sha256(d / n)] for n in present])


@lru_cache(maxsize=1)
def git_state() -> tuple[str | None, bool | None]:
    """(commit, uncommitted changes?) of the code that is running. A container has no
    checkout, so the image build passes the commit in VASPFUSION_GIT_COMMIT."""
    env = os.environ.get("VASPFUSION_GIT_COMMIT", "").strip()
    if env:
        return env, os.environ.get("VASPFUSION_GIT_DIRTY", "").strip() in ("1", "true")
    try:
        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                                  timeout=10, check=True).stdout.strip()
        if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT.resolve():
            return None, None                # ROOT merely sits inside someone else's repo
        return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        return None, None


def run_provenance(case_in: dict, trail: list[dict], *, model_dir: str | Path | None) -> dict:
    """The receipt fields a run knows before its findings exist."""
    pages = responses(trail)
    commit, dirty = git_state()
    chain = case_in["chain"]
    digest = model_sha256(model_dir) if model_dir is not None else None
    return {"input": case_in, "input_sha256": sha256_of(case_in),
            "responses": pages, "responses_sha256": responses_sha256(pages),
            "pages": len(pages),
            "model_version": f"{Path(model_dir).parent.name}/{chain}" if digest else None,
            "model_sha256": digest, "git_commit": commit, "git_dirty": dirty}


# ------------------------------------------------------------------ the receipt document
RECEIPT_KEYS = ("seed", "code_version", "git_commit", "git_dirty", "input", "input_sha256",
                "pages", "responses_sha256", "label_db_sha256", "model_version",
                "model_sha256", "findings_sha256", "fetched_at", "offline_replay",
                "data_sources", "responses")


def receipt(case: dict) -> dict | None:
    """The receipt as a document of its own (the case file's last page, `GET
    /api/cases/{id}/receipt`). None for a case that carries none: one stored before B9,
    or one that has not finished."""
    prov = case.get("provenance") or {}
    if case.get("status") != "done" or not prov.get("findings_sha256"):
        return None
    doc = {"schema": RECEIPT_SCHEMA, "case_id": case["id"], "case_ref": case.get("case_ref"),
           "outcome": case["outcome"], "top_vasp": case["top_vasp"],
           "confidence": case["confidence"], "created_at": case["created_at"],
           "demo": bool(case.get("demo")),
           **{k: prov.get(k) for k in RECEIPT_KEYS}}
    return {**doc, "receipt_sha256": sha256_of(doc)}


# ------------------------------------------------------------------ verify
def _check(name: str, result: str, detail: str, stored=None, now=None) -> dict:
    return {"name": name, "result": result, "detail": detail, "stored": stored, "now": now}


def verify_case(case: dict, rerun: Callable[[dict], dict], *,
                label_db_sha256: str | None = None, now: datetime | None = None) -> dict:
    """Compute a stored case again and say whether it is the same case.

    `rerun(input)` traces the wallet again **from the cache only** and returns the new
    case. The stored case verifies when (1) its own fingerprint is still the one in its
    receipt, (2) the pages read are the same bytes, and (3) the new findings have the
    same fingerprint. A changed label database, model or commit is reported beside
    those: it is the usual reason for (3) to differ, not a failure in itself."""
    prov = case.get("provenance") or {}
    if case.get("status") != "done" or not prov.get("findings_sha256") or not prov.get("input"):
        return _no_receipt(case.get("id"), now)
    stored_fp = prov["findings_sha256"]
    own = findings_sha256(case)
    itself = _check(
        "stored_case", "same" if own == stored_fp else "different",
        "The stored case still has the fingerprint in its receipt." if own == stored_fp else
        "The stored case no longer matches its own receipt: it was changed after it was "
        "computed.", stored_fp, own)
    return _verify(case.get("id"), prov, itself, rerun, label_db_sha256, now,
                   describe=lambda fresh: _what_changed(case, fresh))


def verify_receipt(doc: dict, rerun: Callable[[dict], dict], *,
                   label_db_sha256: str | None = None, now: datetime | None = None) -> dict:
    """The same check for a receipt that left the machine without its case (an exported
    `<case>.receipt.json`): the receipt must still have its own digest, and the wallet
    traced again must give the fingerprint it states."""
    if not doc.get("findings_sha256") or not doc.get("input"):
        return _no_receipt(doc.get("case_id"), now)
    own = sha256_of({k: v for k, v in doc.items() if k != "receipt_sha256"})
    intact = own == doc.get("receipt_sha256")
    itself = _check(
        "stored_case", "same" if intact else "different",
        "The receipt still has its own digest." if intact else
        "The receipt no longer matches its own digest: it was changed after it was issued.",
        doc.get("receipt_sha256"), own)

    def describe(fresh: dict) -> str:
        said = [f"{k.replace('_', ' ')} {doc.get(k)!r} -> {fresh[k]!r}"
                for k in ("outcome", "top_vasp", "confidence") if doc.get(k) != fresh[k]]
        return ", ".join(said) + "." if said else "the figures behind the headline differ."
    return _verify(doc.get("case_id"), doc, itself, rerun, label_db_sha256, now, describe)


def _no_receipt(case_id, now) -> dict:
    return {"case_id": case_id, "matches": False, "checks": [],
            "checked_at": iso(now or datetime.now(timezone.utc)),
            "summary": "This case carries no receipt (it was stored before receipts "
                       "existed, or it has not finished). Trace it again, then verify."}


def _verify(case_id, prov: dict, itself: dict, rerun, label_db_sha256, now,
            describe: Callable[[dict], str]) -> dict:
    out = {"case_id": case_id, "matches": False, "checks": [itself],
           "checked_at": iso(now or datetime.now(timezone.utc))}
    checks = out["checks"]
    stored_fp = prov["findings_sha256"]
    try:
        fresh = rerun(prov["input"])
    except Exception as e:  # noqa: BLE001 - whatever stopped the replay is the answer
        checks.append(_check("replay", "not_checked",
                             f"Could not trace it again from the cache: {type(e).__name__}: "
                             f"{str(e)[:300]}"))
        out["summary"] = ("Not verified: the wallet could not be traced again from the "
                          "cached chain responses.")
        return out
    new = fresh["provenance"]

    old_pages = {p["query"]: p["sha256"] for p in prov.get("responses") or []}
    new_pages = {p["query"]: p["sha256"] for p in new.get("responses") or []}
    if new["responses_sha256"] == prov["responses_sha256"]:
        checks.append(_check("responses", "same",
                             f"The same {prov['pages']} chain responses were read, byte for "
                             f"byte.", prov["responses_sha256"], new["responses_sha256"]))
    else:
        changed = sorted(q for q in old_pages if q in new_pages and old_pages[q] != new_pages[q])
        gone = sorted(q for q in old_pages if q not in new_pages)
        added = sorted(q for q in new_pages if q not in old_pages)
        parts = [f"{len(v)} {word}" for v, word in ((changed, "changed"),
                                                    (gone, "no longer read"),
                                                    (added, "newly read")) if v]
        first = (changed or gone or added or ["(the list of responses was not recorded)"])[0]
        checks.append(_check("responses", "different",
                             f"The chain responses differ: {', '.join(parts) or 'digest'}. "
                             f"First: {first}",
                             prov["responses_sha256"], new["responses_sha256"]))

    same_findings = new["findings_sha256"] == stored_fp
    checks.append(_check(
        "findings", "same" if same_findings else "different",
        "Traced again, the result has the same fingerprint." if same_findings else
        "Traced again, the result is different: " + describe(fresh),
        stored_fp, new["findings_sha256"]))

    for name, old, cur, words in (
            ("labels", prov.get("label_db_sha256"), label_db_sha256, "label database"),
            ("model", prov.get("model_sha256"), new.get("model_sha256"),
             "deposit-address model"),
            ("code", prov.get("git_commit"), new.get("git_commit"), "code (git commit)")):
        if old is None and cur is None:
            continue                     # neither run used it (e.g. no model on Ethereum)
        if old is None or cur is None:
            checks.append(_check(name, "not_checked",
                                 f"The {words} was not recorded on one side.", old, cur))
        else:
            checks.append(_check(name, "same" if old == cur else "different",
                                 f"The {words} is the same." if old == cur else
                                 f"The {words} has changed since this case was computed.",
                                 old, cur))

    core = {c["name"]: c["result"] for c in checks}
    out["matches"] = all(core[k] == "same" for k in ("stored_case", "responses", "findings"))
    if out["matches"]:
        out["summary"] = ("Verified: traced again from the cached chain responses, the case "
                          "has the same findings fingerprint.")
    else:
        why = [words for name, words in (("labels", "the label database"),
                                         ("model", "the model"), ("code", "the code"))
               if core.get(name) == "different"]
        out["summary"] = ("Not verified: " + " ".join(
            c["detail"] for c in checks
            if c["name"] in ("stored_case", "responses", "findings") and c["result"] != "same")
            + (f" Changed since: {', '.join(why)}." if why else ""))
    return out


def _what_changed(old: dict, new: dict) -> str:
    a, b = findings(old), findings(new)
    ha, hb = a.pop("headline"), b.pop("headline")
    keys = [f"headline.{k}" for k in ha if ha[k] != hb.get(k)] + \
           [k for k in a if a[k] != b.get(k)]
    said = []
    for k in ("outcome", "top_vasp", "confidence"):
        if ha[k] != hb[k]:
            said.append(f"{k.replace('_', ' ')} {ha[k]!r} -> {hb[k]!r}")
    return (", ".join(said) + ". " if said else "") + "Parts that differ: " + ", ".join(keys) + "."
