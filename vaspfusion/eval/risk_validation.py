"""The risk score and the pattern rules, measured on real wallets with a documented story.

Two sets, fixed by scripts/build_validation_corpus.py before any wallet was traced
(data/validation/corpus.json): positives a public source documents as sanctioned, as
ransomware payment addresses, as scam or phishing addresses or as the wallets of a theft;
and controls with a documented ordinary purpose (charities, mining pools, treasuries,
distributors, a payment processor, customers of exchanges).

Each wallet is traced with the pipeline a case runs (`run_case`, the interface's default
budget) under three views of the label store:

* `as_shown`: every label, as an officer sees it. A positive that is itself on a list
  scores Severe by lookup, which says nothing about the rules.
* `own_hidden`: the wallet's own label hidden. THE MAIN FIGURE.
* `entity_hidden`: every label of the wallet's own entity hidden as well (the other
  addresses of the same list entry, the other wallets of the same theft), so a positive
  cannot score by reaching its listed neighbours.

The score of a view is `risk.wallet_risk` of the wallet with the label that view shows
and the case that view traced. The points in config/risk.yaml were set before this
measurement and were not changed after it; a changed file needs a fresh set of wallets.

The traced cases are kept slim (only what risk.py reads) in
artifacts/risk_validation_v1/cases.json.gz, so the measurement regenerates with no
network: `make risk-validation`.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

from scipy.stats import beta, fisher_exact

from .. import risk as R
from ..cases import run_case, trace_provider
from ..chains.base import ProviderError
from ..trace import TraceConfig

VERSION = "risk_validation_v1"
VIEWS = ("as_shown", "own_hidden", "entity_hidden")
MAIN_VIEW = "own_hidden"
ARMS = ("positive", "control")
RULES = ("peel_chain", "fan_out", "fan_in", "rapid_forwarding", "round_amounts")
# the indicators that read behaviour only, never a list
BEHAVIOUR = RULES + ("coinjoin_shape", "unlabelled_hub")
LABEL_KEYS = ("category", "entity", "label", "source", "threat", "threat_entity",
              "threat_source", "threat_url", "threat_evidence")
NOTES = (
    "The positives are addresses a public list names; the controls are addresses with a "
    "documented ordinary purpose. Neither is a sample of the wallets a complaint brings in.",
    "The main figure hides each wallet's own label. Other listed addresses stay visible, so "
    "a positive can still score by paying a listed neighbour; the entity-hidden view "
    "removes the neighbours of its own entry, and the behaviour-only score removes every "
    "list.",
    "A wallet with nothing to trace (no outgoing transfer of an asset the tool follows) "
    "scores Low by default. It stays in every count and is also reported apart.",
    "The two sets differ in more than guilt: most positives are old Bitcoin and Ethereum "
    "addresses, most controls are Ethereum service wallets and recent exchange customers. "
    "A difference between the arms is not all due to the rules.",
    "The points in config/risk.yaml were set before this measurement and not changed after "
    "it. They are a stated judgement, checked here, not fitted.",
    "Each wallet was traced once at the default budget (3 hops, 40 wallets per direction) "
    "from its most recent transfers; a different budget or date can change a wallet's result.",
)


class HiddenLabels:
    """A label store that does not know one address, or any address of some entities."""

    def __init__(self, store, address: str | None = None, entities=()):
        self.store, self.address = store, (address or "").lower()
        self.entities = {e for e in entities if e}

    def hidden(self, address: str, label) -> bool:
        return address.lower() == self.address or label.entity in self.entities \
            or (label.threat_entity in self.entities)

    def lookup_many(self, pairs):
        return {k: lab for k, lab in self.store.lookup_many(pairs).items()
                if not self.hidden(k[0], lab)}


def _label(lab) -> dict | None:
    if lab is None:
        return None
    d = lab if isinstance(lab, dict) else lab.as_dict()
    return {k: d.get(k) for k in LABEL_KEYS}


def slim(case: dict) -> dict:
    """What risk.py reads of a case, and the headline, and nothing else."""
    g = case.get("graph") or {}
    return {
        "id": case["id"], "address": case["address"], "chain": case["chain"],
        "status": case["status"], "outcome": case["outcome"], "asset": case.get("asset"),
        "total_sent": case.get("total_sent"), "top_vasp": case.get("top_vasp"),
        "candidates": [{"vasp": c["vasp"], "direction": c["direction"], "hops": c["hops"],
                        "confidence": c["confidence"]} for c in case.get("candidates", [])],
        "typology_flags": [{"code": f["code"], "wallet": f["wallet"], "text": f["text"],
                            "figures": f.get("figures") or {},
                            "tx_hashes": f.get("tx_hashes", [])}
                           for f in case.get("typology_flags", [])],
        "graph": {"nodes": [{"id": n["id"], "is_hub": bool(n.get("is_hub")),
                             "label": _label(n.get("label"))} for n in g.get("nodes", [])],
                  "edges": [{"id": e["id"], "source": e["source"], "target": e["target"],
                             "tx_hash": e["tx_hash"],
                             "direction": e.get("direction", "outbound")}
                            for e in g.get("edges", [])]},
        "where_funds_went": [{"kind": s["kind"], "name": s.get("name"), "share": s["share"]}
                             for s in case.get("where_funds_went", [])],
        "hop_rail": [{"tx_hash": h["tx_hash"]} for h in case.get("hop_rail") or []],
    }


def trace_wallet(wallet: dict, fetcher, store, cfg: TraceConfig = TraceConfig()) -> dict:
    """One wallet under the three views: {own_label, views: {view: slim case | {error}}}."""
    address, chain = wallet["address"], wallet["chain"]
    own = store.lookup_many([(address, chain)]).get((address, chain))
    entities = {own.entity, own.threat_entity} if own else set()
    stores = {"as_shown": store, "own_hidden": HiddenLabels(store, address),
              "entity_hidden": HiddenLabels(store, address, entities)}
    views = {}
    for view in VIEWS:
        try:
            case = run_case(address, chain, trace_provider(chain, fetcher, cfg), stores[view],
                            case_id=f"rv-{chain}-{address}", cfg=cfg, fetcher=fetcher,
                            scorer=None)
            views[view] = slim(case)
        except (ProviderError, ValueError) as e:
            views[view] = {"error": f"{type(e).__name__}: {e}"[:300]}
    return {"address": address, "chain": chain, "own_label": _label(own), "views": views}


def trace_corpus(wallets: list[dict], fetcher, open_store, *, done: dict | None = None,
                 on_done=None, cfg: TraceConfig = TraceConfig()) -> dict:
    """Every wallet, one thread per chain (a chain's API is asked by one wallet at a time).
    `done` holds wallets already traced (address -> row); `on_done(row)` is told each new one."""
    done = dict(done or {})
    lock = threading.Lock()
    by_chain: dict[str, list[dict]] = {}
    for w in wallets:
        if w["address"] not in done:
            by_chain.setdefault(w["chain"], []).append(w)

    def run(chain: str) -> None:
        with open_store() as store:
            for w in by_chain[chain]:
                row = trace_wallet(w, fetcher, store, cfg)
                with lock:
                    done[w["address"]] = row
                    if on_done:
                        on_done(row)

    with ThreadPoolExecutor(max_workers=max(1, len(by_chain))) as pool:
        list(pool.map(run, by_chain))
    return done


def write_cases(path: Path, rows: dict) -> None:
    body = json.dumps({"version": VERSION, "wallets": [rows[a] for a in sorted(rows)]},
                      sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as f:
        f.write(body)


def read_cases(path: Path) -> dict:
    with gzip.open(path, "rb") as f:
        return {w["address"]: w for w in json.loads(f.read())["wallets"]}


# ------------------------------------------------------------------ the measurement
def _interval(k: int, n: int, level: float = 0.95) -> list[float] | None:
    """Clopper-Pearson, two-sided."""
    if not n:
        return None
    a = (1 - level) / 2
    lo = 0.0 if k == 0 else float(beta.ppf(a, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a, k + 1, n - k))
    return [round(lo, 4), round(hi, 4)]


def _share(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def _auc(pos: list[float], neg: list[float]) -> float | None:
    """The chance a positive outscores a control, ties counting half."""
    if not pos or not neg:
        return None
    wins = sum((p > c) + 0.5 * (p == c) for p in pos for c in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def score_view(row: dict, view: str, cfg: dict) -> dict:
    """One wallet under one view: its score, class, indicators and flags."""
    case = row["views"][view]
    if "error" in case:
        return {"error": case["error"], "traced": False, "score": None, "risk_class": None,
                "indicators": [], "rules": [], "behaviour_score": None, "outcome": None}
    label = row["own_label"] if view == "as_shown" else None
    risk = R.wallet_risk(row["address"], label, [case], cfg)
    codes = [i["code"] for i in risk["indicators"]]
    behaviour = min(100, sum(i["points"] for i in risk["indicators"] if i["code"] in BEHAVIOUR))
    return {"traced": bool(case["graph"]["edges"]), "score": risk["score"],
            "risk_class": risk["risk_class"], "indicators": codes,
            "rules": sorted({f["code"] for f in case["typology_flags"]} & set(RULES)),
            "behaviour_score": behaviour, "behaviour_class": R.class_of(behaviour, cfg),
            "outcome": case["outcome"], "asset": case["asset"]}


def _arm(scored: list[dict], cfg: dict) -> dict:
    ok = [s for s in scored if "error" not in s]
    traced = [s for s in ok if s["traced"]]

    def high(rows, key="risk_class"):
        return sum(R.RANK[s[key]] >= R.RANK["high"] for s in rows)

    return {
        "wallets": len(scored), "could_not_be_read": len(scored) - len(ok),
        "nothing_to_trace": len(ok) - len(traced), "traced": len(traced),
        "classes": {c: sum(s["risk_class"] == c for s in ok) for c in R.CLASSES},
        "high_or_above": high(ok), "high_or_above_share": _share(high(ok), len(ok)),
        "high_or_above_interval": _interval(high(ok), len(ok)),
        "traced_high_or_above": high(traced),
        "traced_high_or_above_share": _share(high(traced), len(traced)),
        "traced_high_or_above_interval": _interval(high(traced), len(traced)),
        "median_score": median(s["score"] for s in ok) if ok else None,
        "behaviour_classes": {c: sum(s["behaviour_class"] == c for s in ok) for c in R.CLASSES},
        "behaviour_medium_or_above": sum(R.RANK[s["behaviour_class"]] >= 1 for s in ok),
    }


def _two_by_two(a: int, n_a: int, b: int, n_b: int) -> float | None:
    if not n_a or not n_b:
        return None
    return round(float(fisher_exact([[a, n_a - a], [b, n_b - b]])[1]), 4)


def _fired(scored: dict[str, list[dict]], codes, key: str, traced_only: bool) -> list[dict]:
    out = []
    for code in codes:
        row = {"code": code}
        for arm in ARMS:
            rows = [s for s in scored[arm] if "error" not in s and (s["traced"] or not traced_only)]
            row[arm] = sum(code in s[key] for s in rows)
            row[f"{arm}_of"] = len(rows)
            row[f"{arm}_share"] = _share(row[arm], len(rows))
        row["p_fisher"] = _two_by_two(row["positive"], row["positive_of"],
                                      row["control"], row["control_of"])
        out.append(row)
    return out


def _groups(wallets: list[dict], scored: dict[str, dict], key: str) -> list[dict]:
    out = []
    for name in dict.fromkeys(w[key] for w in wallets):
        mine = [w for w in wallets if w[key] == name]
        for arm in ARMS:
            rows = [scored[w["address"]] for w in mine if w["arm"] == arm]
            ok = [s for s in rows if "error" not in s]
            if not rows:
                continue
            out.append({key: name, "arm": arm, "wallets": len(rows),
                        "could_not_be_read": len(rows) - len(ok),
                        "traced": sum(s["traced"] for s in ok),
                        "classes": {c: sum(s["risk_class"] == c for s in ok) for c in R.CLASSES},
                        "high_or_above": sum(R.RANK[s["risk_class"]] >= 2 for s in ok),
                        "rules": {r: sum(r in s["rules"] for s in ok) for r in RULES}})
    return out


def measure(corpus: dict, rows: dict, cfg: dict | None = None, *, config_sha256: str = "",
            corpus_sha256: str = "") -> dict:
    cfg = cfg or R.load_config()
    wallets = corpus["wallets"]
    missing = [w["address"] for w in wallets if w["address"] not in rows]
    if missing:
        raise ValueError(f"{len(missing)} wallets of the corpus were never traced: "
                         f"{', '.join(missing[:3])}")
    views, per_wallet = {}, {w["address"]: {} for w in wallets}
    for view in VIEWS:
        scored = {w["address"]: score_view(rows[w["address"]], view, cfg) for w in wallets}
        for a, s in scored.items():
            per_wallet[a][view] = s
        by_arm = {arm: [scored[w["address"]] for w in wallets if w["arm"] == arm] for arm in ARMS}
        arms = {arm: _arm(by_arm[arm], cfg) for arm in ARMS}
        p, c = arms["positive"], arms["control"]
        ok = {arm: [s for s in by_arm[arm] if "error" not in s] for arm in ARMS}
        tr = {arm: [s for s in ok[arm] if s["traced"]] for arm in ARMS}
        views[view] = {
            "arms": arms,
            "separation": {
                "positives_high_or_above": p["high_or_above_share"],
                "controls_high_or_above": c["high_or_above_share"],
                "p_fisher": _two_by_two(p["high_or_above"], len(ok["positive"]),
                                        c["high_or_above"], len(ok["control"])),
                "auc_score": _auc([s["score"] for s in ok["positive"]],
                                  [s["score"] for s in ok["control"]]),
                "auc_score_traced": _auc([s["score"] for s in tr["positive"]],
                                         [s["score"] for s in tr["control"]]),
                "auc_behaviour_score": _auc([s["behaviour_score"] for s in ok["positive"]],
                                            [s["behaviour_score"] for s in ok["control"]]),
                "auc_behaviour_score_traced": _auc([s["behaviour_score"] for s in tr["positive"]],
                                                   [s["behaviour_score"] for s in tr["control"]]),
            },
            "rules": _fired(by_arm, RULES, "rules", traced_only=False),
            "rules_traced": _fired(by_arm, RULES, "rules", traced_only=True),
            "indicators": _fired(by_arm, R.CODES, "indicators", traced_only=False),
            "by_stratum": _groups(wallets, scored, "stratum"),
            "by_chain": _groups(wallets, scored, "chain"),
        }
    return {
        "version": VERSION, "seed": corpus["seed"], "main_view": MAIN_VIEW,
        "positives": sum(w["arm"] == "positive" for w in wallets),
        "controls": sum(w["arm"] == "control" for w in wallets),
        "trace": {"max_hops": 3, "max_wallets": 40, "inbound_hops": 1, "since": None,
                  "deposit_model_leads": "not scored (not a risk indicator)"},
        "risk_config_sha256": config_sha256, "corpus_sha256": corpus_sha256,
        "classes": cfg["classes"], "views": views, "notes": list(NOTES),
        "wallets": [{"address": w["address"], "chain": w["chain"], "arm": w["arm"],
                     "stratum": w["stratum"], **{v: per_wallet[w["address"]][v] for v in VIEWS}}
                    for w in wallets],
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summary(m: dict) -> dict:
    """The few figures the interface and the documents quote (GET /api/model)."""
    v = m["views"][m["main_view"]]
    p, c = v["arms"]["positive"], v["arms"]["control"]
    return {"version": m["version"], "positives": m["positives"], "controls": m["controls"],
            "view": m["main_view"],
            "positives_high_or_above": p["high_or_above"], "positives_scored": p["wallets"] - p["could_not_be_read"],
            "controls_high_or_above": c["high_or_above"], "controls_scored": c["wallets"] - c["could_not_be_read"],
            "positives_nothing_to_trace": p["nothing_to_trace"],
            "controls_nothing_to_trace": c["nothing_to_trace"],
            "auc_score": v["separation"]["auc_score"],
            "auc_behaviour_score": v["separation"]["auc_behaviour_score"],
            "rules": v["rules"], "notes": m["notes"]}
