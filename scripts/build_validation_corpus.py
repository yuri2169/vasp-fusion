"""Fix the wallets the risk score is measured on, before any of them is traced.

    python scripts/build_validation_corpus.py [--labels data/labels.duckdb]
                                              [--benchmark artifacts/benchmark_v1]
    # a fresh set, after the points were changed: another seed, and no wallet of the first
    python scripts/build_validation_corpus.py --seed 26183 --taken 2026-10-08 \
        --exclude data/validation/corpus.json --out data/validation/corpus_v2.json

Every address is drawn by this script from a named public source, with a fixed seed, from
the full label database (`make labels`) and from the wallets of the six-chain benchmark.
Nothing about a wallet's activity is looked at: a drawn wallet that turns out to have
nothing to trace stays in the set and is reported as such.

* Positives: addresses a public source documents as sanctioned, as ransomware payment
  addresses, as scam or phishing addresses, or as the wallets of a theft.
* Controls: addresses with a documented ordinary purpose that the pattern rules could
  well fire on (charities, mining pools, treasuries, airdrop and reward distributors, a
  payment processor), and customers of exchanges from the benchmark's samples.

The addresses of the WazirX theft of July 2024 are left out: that case is traced on its
own (data/validation/wazirx_2024.json).

Writes data/validation/corpus.json. Run it once; the measurement reads the file.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "validation" / "corpus.json"
SEED = 26182
TAKEN = "2026-10-08"
# an explorer-tagged exploiter or hacker wallet (it carried no threat tag when the first set
# was drawn and carries `theft` since; the rule reads the name tag, not the threat)
EXPLOITER = ("source = 'eth-labels' and category = 'entity' "
             "and regexp_matches(label, '(Exploiter|Hacker)( [0-9]+)?$')")
OFAC = "category = 'sanctioned' and source like 'ofac-sdn%'"
TAGGED = "source = 'eth-labels' and category = 'entity' and threat is null"

# (stratum, what it is, chain, how many, WHERE clause over the label table, most per entity)
POSITIVES = [
    ("ofac_tron", "On the OFAC SDN list", "tron", 10, OFAC, None),
    ("ofac_ethereum", "On the OFAC SDN list", "ethereum", 5, OFAC, None),
    ("ofac_bitcoin", "On the OFAC SDN list", "bitcoin", 5, OFAC, None),
    ("ransomware_bitcoin", "Ransomware payment address (Ransomwhere)", "bitcoin", 10,
     "threat_source = 'ransomwhere'", None),
    ("scam_list_ethereum", "On a scam list (EtherScamDB, MyEtherWallet darklist)", "ethereum",
     10, "category = 'scam' and (source like '%etherscamdb%' or source like 'mew-ethereum-lists%')",
     None),
    ("defi_fraud_ethereum", "Listed as DeFi fraud (GraphSense TagPack)", "ethereum", 5,
     "source = 'graphsense-tagpack:defi-fraud-masterthesis'", None),
    ("scam_list_bitcoin", "On a scam list (EtherScamDB)", "bitcoin", 5,
     "category = 'scam' and source like '%etherscamdb%'", None),
    ("exploiter_ethereum", "Explorer-tagged exploiter or hacker wallet", "ethereum", 10,
     f"{EXPLOITER} and entity <> 'Wazirx Exploit'", 2),
    ("phishing_ethereum", "Explorer-tagged phishing address", "ethereum", 5,
     "source = 'eth-labels' and label like 'Fake_Phishing%'", None),
]
CONTROLS = [
    ("charity_ethereum", "Explorer-tagged charity or donation address", "ethereum", 10,
     f"{TAGGED} and entity in ('Charity', 'Donate')", None),
    ("mining_ethereum", "Explorer-tagged mining pool", "ethereum", 10,
     f"{TAGGED} and entity = 'Mining'", None),
    ("treasury_ethereum", "Explorer-tagged treasury", "ethereum", 8,
     f"{TAGGED} and label like '%Treasury%'", 1),
    ("distributor_ethereum", "Explorer-tagged airdrop or reward distributor", "ethereum", 7,
     f"{TAGGED} and (label like '%Airdrop%' or label like '%Distributor%')", 1),
    ("payment_ethereum", "Explorer-tagged payment processor (BitPay)", "ethereum", 5,
     f"{TAGGED} and entity = 'BitPay'", None),
]
# exchange customers from the benchmark's wallets: (chain, how many)
CUSTOMERS = [("tron", 8), ("ethereum", 6), ("bitcoin", 8), ("bsc", 4), ("polygon", 4)]
COLUMNS = ("address", "entity", "label", "source", "source_url", "threat", "threat_source",
           "threat_url")


def draw(rng: random.Random, rows: list[dict], n: int, per_entity: int | None) -> list[dict]:
    """`n` of `rows` (sorted by address first, so the draw depends on the seed alone), with
    at most `per_entity` of one entity."""
    pool = sorted(rows, key=lambda r: r["address"])
    rng.shuffle(pool)
    taken: list[dict] = []
    seen: dict[str, int] = {}
    for r in pool:
        if per_entity and seen.get(r["entity"], 0) >= per_entity:
            continue
        seen[r["entity"]] = seen.get(r["entity"], 0) + 1
        taken.append(r)
        if len(taken) == n:
            break
    return taken


def from_labels(db, rng, arm: str, strata, used: set[str], taken: str) -> list[dict]:
    out = []
    for stratum, what, chain, n, where, per_entity in strata:
        found = db.execute(f"select {', '.join(COLUMNS)} from labels where chain = ? "
                           f"and ({where})", [chain]).fetchall()
        rows = [dict(zip(COLUMNS, r)) for r in found if r[0] not in used]
        for r in draw(rng, rows, n, per_entity):
            out.append({"address": r["address"], "chain": chain, "arm": arm, "stratum": stratum,
                        "what": what, "entity": r["entity"], "label": r["label"],
                        "source": r["source"], "source_url": r["source_url"],
                        "threat": r["threat"], "threat_source": r["threat_source"],
                        "threat_url": r["threat_url"], "taken": taken,
                        "available": len(rows)})
    return out


def customers(rng, benchmark: Path, commit: str, used: set[str], taken: str) -> list[dict]:
    out = []
    for chain, n in CUSTOMERS:
        with (benchmark / chain / "wallets.csv").open() as f:
            rows = [{"address": r["wallet"], "entity": r["exchange"]} for r in csv.DictReader(f)]
        rows = [r for r in {r["address"]: r for r in rows}.values() if r["address"] not in used]
        for r in draw(rng, rows, n, None):
            out.append({"address": r["address"], "chain": chain, "arm": "control",
                        "stratum": f"exchange_customer_{chain}",
                        "what": "A wallet that paid an exchange's deposit address (the "
                                "six-chain benchmark's sample)",
                        "entity": f"customer of {r['entity']}", "label": None,
                        "source": "vasp-fusion benchmark_v1",
                        "source_url": f"artifacts/benchmark_v1/{chain}/wallets.csv"
                                      + (f" at commit {commit}" if commit else ""),
                        "taken": taken, "available": len(rows)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", default=str(ROOT / "data" / "labels.duckdb"))
    ap.add_argument("--benchmark", default=str(ROOT / "artifacts" / "benchmark_v1"))
    ap.add_argument("--benchmark-commit", default="")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--taken", default=TAKEN, help="the date written beside each wallet")
    ap.add_argument("--exclude", action="append", default=[],
                    help="an earlier set: none of its wallets is drawn again (repeatable)")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    used = {w["address"] for f in args.exclude for w in json.loads(Path(f).read_text())["wallets"]}
    db = duckdb.connect(args.labels, read_only=True)
    wallets = from_labels(db, rng, "positive", POSITIVES, used, args.taken) \
        + from_labels(db, rng, "control", CONTROLS, used, args.taken)
    db.close()
    wallets += customers(rng, Path(args.benchmark), args.benchmark_commit, used, args.taken)
    both = {w["address"] for w in wallets if w["arm"] == "positive"} & \
           {w["address"] for w in wallets if w["arm"] == "control"}
    if both:
        sys.exit(f"in both arms: {sorted(both)}")
    doc = {"_notice": "Real addresses, each drawn by scripts/build_validation_corpus.py from the "
                      "public source named beside it. The list was fixed before any of them "
                      "was traced. A control being here alleges nothing about its owner; a "
                      "positive is here because the named source lists it.",
           "seed": args.seed, "taken": args.taken,
           "excludes": [str(Path(f).as_posix()) for f in args.exclude],
           "labels_sha256": hashlib.sha256(Path(args.labels).read_bytes()).hexdigest(),
           "positives": sum(w["arm"] == "positive" for w in wallets),
           "controls": sum(w["arm"] == "control" for w in wallets),
           "wallets": wallets}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, indent=1) + "\n")
    by: dict[str, int] = {}
    for w in wallets:
        by[f"{w['arm']}:{w['stratum']}"] = by.get(f"{w['arm']}:{w['stratum']}", 0) + 1
    for k, v in by.items():
        print(f"  {k:<42}{v:>4}")
    print(f"{doc['positives']} positives, {doc['controls']} controls -> {args.out}")


if __name__ == "__main__":
    main()
