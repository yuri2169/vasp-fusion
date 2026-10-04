"""Command line: `python -m vaspfusion.cli <command>`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _table(title: str, counts: dict, total: int) -> str:
    lines = [f"  {title}"]
    for k, v in counts.items():
        lines.append(f"    {k:<22}{v:>9,}  {100 * v / max(total, 1):5.1f}%")
    return "\n".join(lines)


TAGPACKS_CSV = "graphsense_tagpacks_exchange.csv"


def cmd_tagpacks(args) -> None:
    from collections import Counter

    from .labels.tagpacks import read_packs, write_csv
    rows = read_packs(args.packs)
    write_csv(rows, args.out)
    by = Counter(r["currency"] for r in rows)
    print(f"tagpacks -> {args.out}")
    print(f"  {len(rows):,} exchange tags from {len({r['source'] for r in rows})} packs: "
          + ", ".join(f"{c} {n:,}" for c, n in sorted(by.items())))
    for source, n in sorted(Counter(r["source"] for r in rows).items()):
        print(f"    {source:<52}{n:>8,}")


def cmd_labels(args) -> None:
    from .labels.load import build_labels
    research = Path(args.research)
    stats = build_labels(Path(args.db), research / "wallet-attribution" / "data",
                         research / "indian_vasps_dune_spellbook.csv",
                         derived_dir=Path(args.derived), model_dir=Path(args.model),
                         tagpacks_csv=research / TAGPACKS_CSV)
    t = stats["total"]
    print(f"labels -> {args.db}")
    print(f"  raw rows {stats['raw_rows']:,}  duplicates dropped "
          f"{stats['duplicates_dropped']:,}  unique (address, chain) {t:,}")
    print(f"  GraphSense TagPacks (exchange packs): {stats['tagpack_rows']:,} rows, "
          f"{stats['tagpack_kept']:,} kept as the label of their address (the rest are "
          "addresses a stronger or equal source already labels). `make tagpacks` writes "
          f"{TAGPACKS_CSV}.")
    print(f"  unusable addresses dropped {stats['invalid_dropped']:,} (valid on no chain, e.g. "
          f"truncated upstream)  re-filed to their real chain {stats['chain_refiled']:,}")
    ex = stats["by_category"].get("exchange", 0)
    derived_ex = stats["derived_exchange"]
    print(f"  exchange rows {ex:,} = {ex - stats['exchange_tag_promoted'] - derived_ex:,} upstream "
          f"+ Dune exchange rows + {stats['exchange_tag_promoted']:,} promoted by Etherscan's "
          f"Exchange tag + {derived_ex:,} derived deposit addresses")
    print(f"  derived deposit addresses merged from {args.derived}: "
          f"{stats['by_tier'].get('derived', 0):,} (of {stats['derived_loaded']:,} in the "
          f"discovery files; {stats['derived_shadowed']:,} already labelled by a stronger "
          f"source or named by two runs; {stats['derived_conflicting']:,} left out because two "
          "runs name different exchanges). Run `make discover` to produce them.")
    print(f"  of those, {stats['derived_model_scored']:,} carry the deposit-address model's "
          f"calibrated confidence and range (from {args.model}; `make model` writes it); "
          f"{stats['derived_model_unconfirmed']:,} keep the rules' confidence because the "
          "model did not confirm them; the rest were not scored")
    print(_table("by category", stats["by_category"], t))
    print(_table("by tier", stats["by_tier"], t))
    print(_table("by kind", stats["by_kind"], t))
    print(_table("by chain", stats["by_chain"], t))


def _short(a: str) -> str:
    return a if len(a) <= 16 else f"{a[:8]}…{a[-6:]}"


def cmd_fetch(args) -> None:
    import sys
    from datetime import datetime, timezone

    from . import chains
    from .chains.http import api_key

    try:
        chain = args.chain or chains.detect_chain(args.address)
        since = None
        if args.since:
            since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
            since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        fetcher = chains.default_fetcher()
        fetcher.refresh = args.refresh
        rows = chains.get_provider(chain, fetcher).transfers(
            args.address, args.direction, since=since, limit=args.limit)
    except (chains.InvalidAddress, chains.ProviderError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    if args.json:
        for t in rows:
            print(json.dumps(t.to_dict(), sort_keys=True))
        return

    labels = {}
    db = Path(args.labels_db)
    if args.labels == "auto" and db.exists():
        from .labels.lookup import LabelStore
        with LabelStore(db) as store:
            labels = store.lookup_many({(a, chain) for t in rows
                                        for a in (t.from_addr, t.to_addr)})
    me = args.address.strip()  # adapters return EVM and bech32 addresses lowercased
    me = me.lower() if me.startswith("0x") or me.lower().startswith("bc1") else me

    def who(a: str) -> str:
        lab = labels.get((a, chain))
        return f"{_short(a)} ({lab.entity})" if lab else _short(a)

    how = "given" if args.chain else "auto-detected"
    print(f"{chain} ({how})  {who(me)}  direction={args.direction} "
          f"since={args.since or '-'} limit={args.limit}")
    print("keys: " + ", ".join(f"{k} {'set' if api_key(k) else 'not set'}"
                               for k in ("TRONGRID_API_KEY", "ETHERSCAN_API_KEY", "HELIUS_API_KEY",
                                         "ANKR_API_KEY")))
    print(f"  {'time (UTC)':<21}{'dir':<5}{'asset':<12}{'amount':>24}  "
          f"{'counterparty':<34}tx")
    for t in rows:
        d = t.direction_for(me)
        other = t.to_addr if d == "out" else t.from_addr
        asset = t.asset if len(t.asset) <= 11 else t.asset[:10] + "…"
        print(f"  {t.to_dict()['block_time']:<21}{d:<5}{asset:<12}{t.to_dict()['amount']:>24}  "
              f"{who(other):<34}{_short(t.tx_hash)}")
    s = fetcher.stats
    print(f"{len(rows)} transfers | pages: {s['live']} live, {s['hits']} cached, "
          f"{s['retries']} retries | "
          f"OFFLINE={1 if fetcher.offline else 0} | cache {fetcher.cache.path}")


def _since(text: str | None):
    from datetime import datetime, timezone
    if not text:
        return None
    since = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return since if since.tzinfo else since.replace(tzinfo=timezone.utc)


def _run_case(address: str, chain: str | None, max_hops: int, labels_db: str, since=None,
              **kw) -> tuple[dict, object]:
    """Trace one wallet through the shared cache-first fetcher. Returns (case, fetcher)."""
    from . import chains
    from .cases import file_sha256, run_case, trace_provider
    from .labels.lookup import LabelStore
    from .trace import TraceConfig

    chain = chain or chains.detect_chain(address)
    address = address.strip()
    if chain in chains.EVM_FAMILY or address.lower().startswith("bc1"):
        address = address.lower()
    fetcher = chains.default_fetcher()
    cfg = TraceConfig(max_hops=max_hops, since=since)
    with LabelStore(labels_db) as labels:
        case = run_case(address, chain, trace_provider(chain, fetcher, cfg), labels, cfg=cfg,
                        fetcher=fetcher, label_db_sha256=file_sha256(labels_db), **kw)
    return case, fetcher


def _pages(fetcher) -> str:
    s = fetcher.stats
    return (f"pages: {s['live']} live, {s['hits']} cached, {s['retries']} retries | "
            f"OFFLINE={1 if fetcher.offline else 0}")


def _rules(args):
    from dataclasses import replace

    from .discover.rules import DiscoverConfig
    rules = DiscoverConfig()
    return rules if args.max_hours is None else replace(rules, max_hours=args.max_hours)


def cmd_discover(args) -> None:
    """Derive deposit addresses from the chain's labelled exchange wallets (B4)."""
    from math import ceil

    from . import chains
    from .discover.crawl import CrawlConfig, discover
    from .discover.store import write_result
    from .labels.lookup import LabelStore

    base = CrawlConfig()
    cfg = CrawlConfig(
        window_start=_since(args.since) or base.window_start,
        lookback_days=args.lookback_days, seed_limit=args.seed_limit,
        candidate_limit=args.candidate_limit, max_candidates=args.max_candidates,
        entities=tuple(e.strip() for e in args.entities.split(",")) if args.entities else None,
        rules=_rules(args))
    # its own cache file, held open for the whole run: thousands of small pages would
    # otherwise each reopen the main cache, and would bloat what the demo has to ship
    cache = chains.ChainCache(args.cache, hold=True)
    fetcher = chains.Fetcher(cache, chains.UrllibTransport())
    seed_page = min(200, cfg.seed_limit)
    seed_provider = chains.get_provider(args.chain, fetcher, page_size=seed_page,
                                        max_pages=ceil(cfg.seed_limit / seed_page))
    candidate_provider = chains.get_provider(args.chain, fetcher,
                                             page_size=cfg.candidate_limit, max_pages=1)

    def progress(stage: str, i: int, n: int) -> None:
        if i == n or i % 500 == 0:
            print(f"  {stage}: {i}/{n}  ({_pages(fetcher)})", file=sys.stderr, flush=True)

    with LabelStore(args.labels_db) as labels:
        result = discover(args.chain, seed_provider, candidate_provider, labels, cfg, progress,
                          workers=args.workers)
    cache.close()
    csv_path, report_path = write_result(args.out, result, name=args.name)

    print(f"discovery on {args.chain}: transfers into labelled exchange wallets since "
          f"{cfg.window_text()} (rules: forward >= {cfg.rules.min_share:.0%} within "
          f"{cfg.rules.max_hours:g} h; gas within {cfg.rules.gas_window_s // 60} min)")
    print(f"{'exchange':<12}{'seeds':>6}{'active':>7}{'cand.':>7}{'fired':>7}{'derived':>8}"
          f"{'both':>6}{'station':>8}{'sweep':>6}{'confl.':>7}{'known':>6}{'errors':>7}")
    for entity, st in result.stats.items():
        r = st["by_rule"]
        print(f"{entity:<12}{st['seeds']:>6}{st['active_seeds']:>7}{st['candidates']:>7}"
              f"{st['fired']:>7}{st['derived']:>8}{r.get('sweep+gas', 0):>6}"
              f"{r.get('sweep+station', 0):>8}{r.get('sweep', 0):>6}{st['conflict']:>7}"
              f"{st['known']:>6}{st['errors']:>7}")
    t = result.totals
    print(f"{'TOTAL':<12}{t['seeds']:>6}{t['active_seeds']:>7}{t['candidates']:>7}"
          f"{t['fired']:>7}{t['derived']:>8}{'':>20}{t['conflict']:>7}{t['known']:>6}"
          f"{t['errors']:>7}")
    print(f"derived labels by the exchange they name: {t['labels_by_exchange']}")
    for s in result.stations:
        print(f"gas station (reported, not a label): {s['address']} pays for {s['addresses']} "
              f"{s['entity']} deposit addresses ({s['share']:.0%} of those it serves)")
    print(f"wrote {csv_path} and {report_path}")
    print("rule confidences are hand-set, not calibrated; run `make labels` to merge the "
          "derived rows into the label DB")
    print(_pages(fetcher))


def cmd_discover_eval(args) -> None:
    """Measure the discovery rules on held-out explorer-tagged addresses (RQ1)."""
    from . import chains
    from .discover.evaluate import EvalConfig, evaluate, sample
    from .labels.lookup import LabelStore

    cfg = EvalConfig(chain=args.chain, entity=args.entity, n_positive=args.positives,
                     n_negative=args.negatives, seed=args.seed, limit=args.limit,
                     rules=_rules(args))
    fetcher = chains.default_fetcher()
    provider = chains.get_provider(cfg.chain, fetcher, page_size=cfg.limit, max_pages=1)

    def progress(stage: str, i: int, n: int) -> None:
        if i == n or i % 50 == 0:
            print(f"  {stage}: {i}/{n}  ({_pages(fetcher)})", file=sys.stderr, flush=True)

    with LabelStore(args.labels_db) as labels:
        groups = sample(labels, cfg)
        report = evaluate(provider, labels, *groups, cfg, progress)
    out = Path(args.out) / f"{args.name or f'holdout_{cfg.chain}_{cfg.entity.lower()}'}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"config": report.config, "metrics": report.metrics,
                               "rows": report.rows}, indent=1, sort_keys=True) + "\n")

    m = report.metrics

    def pct(x) -> str:
        return "n/a" if x is None else f"{100 * x:.1f}%"

    print(f"hold-out test of the discovery rules: {cfg.entity} on {cfg.chain}, "
          f"explorer-tagged addresses, seed {cfg.seed}")
    print(f"  positives (tagged {cfg.entity} deposit addresses, labels hidden): {m['positives']}")
    print(f"    rediscovered for {cfg.entity}: {m['true_positives']}  -> recall {pct(m['recall'])}")
    print(f"    with stablecoin activity: {m['positives_with_stablecoin_activity']}  -> recall "
          f"{pct(m['recall_with_stablecoin_activity'])}")
    print(f"    by rule: {m['true_positives_by_rule']}")
    print(f"    named another exchange: {m['wrong_entity']}  conflicts: {m['conflicts']}  "
          f"-> entity precision {pct(m['entity_precision'])}")
    for reason, n in m["missed_by_reason"].items():
        print(f"    missed, {reason}: {n}")
    fpr = m["false_positive_rate"]
    print(f"  negatives (tagged, not deposit addresses): {m['negatives']}")
    print(f"    rule fired on {m['false_positives']} "
          f"({m['false_positives_naming_the_tagged_exchange']} of them named the exchange "
          "the tag names)")
    print(f"    false-positive rate: exchange wallets {pct(fpr['exchange_wallets'])}, "
          f"other tagged addresses {pct(fpr['other_tagged'])}")
    print(f"  precision in this sample: {pct(m['precision_in_sample'])} "
          "(depends on the sample mix)")
    print(f"  fetch errors: {m['errors']}")
    print(f"wrote {out}")
    print(_pages(fetcher))


def _model_data_tagged(args) -> None:
    """A chain with no discovery run: the truth is the explorer's deposit tags."""
    import json

    from . import chains
    from .classify.dataset import TaggedConfig, build_tagged, write_dataset
    from .labels.lookup import LabelStore

    base = TaggedConfig()
    cfg = TaggedConfig(chain=args.chain, per_exchange=min(args.per_exchange, base.per_exchange),
                       seed=args.seed)
    # B4's hold-out pages are in the main cache: read them there, fetch the rest into ours
    cache = chains.LayeredCache(chains.ChainCache(args.cache, hold=True), chains.ChainCache())
    fetcher = chains.Fetcher(cache, chains.UrllibTransport())
    provider = chains.get_provider(args.chain, fetcher, page_size=cfg.limit, max_pages=1)

    def progress(stage: str, i: int, n: int) -> None:
        if i == n or i % 100 == 0:
            print(f"  {stage}: {i}/{n}  ({_pages(fetcher)})", file=sys.stderr, flush=True)

    with LabelStore(args.labels_db) as labels:
        examples, stats = build_tagged(provider, labels, cfg, progress, workers=args.workers)
    cache.close()
    out = Path(args.out) / args.chain
    path = write_dataset(out / "dataset.csv", examples)
    stats["config"] = {"entities": list(cfg.entities), "n_positive": cfg.n_positive,
                       "n_negative": cfg.n_negative, "per_exchange": cfg.per_exchange,
                       "limit": cfg.limit, "seed": cfg.seed}
    (out / "dataset_report.json").write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(f"deposit-address dataset for {args.chain} (explorer-tagged truth): "
          f"{stats['examples']} addresses")
    for source, n in stats["by_source"].items():
        print(f"  {source:<22}{n:>7}")
    print(f"customers seen {stats['customers_seen']} (sampled up to {cfg.per_exchange} per "
          f"exchange: {stats['customers']})")
    print(f"no usable transfers: {stats['empty']}; could not be read: {stats['errors']}; "
          f"wallets they pay most: {stats['recipients_read']} read, "
          f"{stats['recipient_errors']} could not be read")
    print(f"wrote {path}")
    print(_pages(fetcher))


def cmd_model_data(args) -> None:
    """Build the deposit-address model's training set (B6) from the chain caches."""
    import json

    from . import chains
    from .classify.dataset import DatasetConfig, build, load_runs, write_dataset
    from .labels.lookup import LabelStore

    runs = [r for r in load_runs(args.derived) if r.chain == args.chain]
    if not runs:
        return _model_data_tagged(args)
    limit = runs[0].limit
    if any(r.limit != limit for r in runs):
        sys.exit("the discovery runs were read with different row limits")
    caches = [chains.ChainCache(path, hold=True) for path in (args.crawl_cache, args.cache)]
    # the negatives and the recipients go into our own cache; a recipient that is itself
    # a derived deposit address is already in the crawl's
    fetchers = [chains.Fetcher(caches[0], chains.UrllibTransport()),
                chains.Fetcher(chains.LayeredCache(caches[1], caches[0]),
                               chains.UrllibTransport())]
    # the crawl's candidate protocol: one page of `limit` rows per listing
    crawl, extra = (chains.get_provider(args.chain, f, page_size=limit, max_pages=1)
                    for f in fetchers)

    def progress(stage: str, i: int, n: int) -> None:
        if i == n or i % 500 == 0:
            print(f"  {stage}: {i}/{n}  ({_pages(fetchers[1])})", file=sys.stderr, flush=True)

    cfg = DatasetConfig(per_exchange=args.per_exchange, seed=args.seed)
    with LabelStore(args.labels_db) as labels:
        examples, stats = build(runs, crawl, extra, labels, cfg, progress, workers=args.workers)
    for c in caches:
        c.close()
    out = Path(args.out) / args.chain
    path = write_dataset(out / "dataset.csv", examples)
    stats["config"] = {"per_exchange": cfg.per_exchange, "seed": cfg.seed,
                       "horizon_days": cfg.horizon_days,
                       "runs": [{"name": r.name, "since": r.since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "limit": r.limit} for r in runs]}
    (out / "dataset_report.json").write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(f"deposit-address dataset for {args.chain}: {stats['examples']} addresses")
    for source, n in stats["by_source"].items():
        print(f"  {source:<22}{n:>7}")
    print(f"customers seen {stats['customers_seen']} (sampled up to {cfg.per_exchange} per "
          f"exchange: {stats['customers']}); {stats['customers_in_two_exchanges']} paid into "
          "two exchanges")
    print(f"no usable transfers in the window: {stats['empty']}; could not be read: "
          f"{stats['errors']}; wallets they pay most: {stats['recipients_read']} read, "
          f"{stats['recipient_errors']} could not be read")
    print(f"wrote {path}")
    print(_pages(fetchers[1]))


def cmd_model(args) -> None:
    """Train, calibrate and measure the deposit-address model; score the derived labels."""
    from datetime import datetime, timezone

    from .classify.dataset import load_runs
    from .classify.report import build_model

    runs = [r for r in load_runs(args.derived) if r.chain == args.chain]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result, scores = build_model(args.chain, args.out, runs, trained_at=now, seed=args.seed)
    m = result.metrics
    d, t = m["dataset"], m["time_split"]
    print(f"deposit-address model ({m['version']}, {m['backend']}, seed {m['seed']}) on "
          f"{m['chain']}: {d['addresses']:,} addresses, {d['positive']:,} deposit addresses, "
          f"{d['negative']:,} others")
    s = t["sizes"]
    print(f"by time: train {s['train']:,} / calibrate {s['calib']:,} / test {s['test']:,}")
    x = t["test"]
    print(f"  PR-AUC {x['pr_auc']}  ROC-AUC {x['roc_auc']}  Brier {x['brier']}  ECE {x['ece']}  "
          f"precision {x['at_0_5']['precision']}  recall {x['at_0_5']['recall']}  "
          f"range width {x['interval_mean_width']}")
    print("by exchange (each scored by a model that never saw it):")
    print(f"  {'exchange':<12}{'n':>6}{'dep.':>6}{'PR-AUC':>8}{'ROC':>8}{'Brier':>8}{'ECE':>8}"
          f"{'prec.':>8}{'recall':>8}")

    def row(name, r, prec, rec) -> str:
        cells = [r["pr_auc"], r["roc_auc"], r["brier"], r["ece"], prec, rec]
        return (f"  {name:<12}{r['n']:>6}{r['n_positive']:>6}"
                + "".join(f"{'-' if c is None else c:>8}" for c in cells))

    for r in m["leave_one_exchange_out"]["folds"]:
        print(row(r["exchange"], r, r["precision"], r["recall"]))
    p = m["leave_one_exchange_out"]["pooled"]
    print(row("POOLED", p, p["at_0_5"]["precision"], p["at_0_5"]["recall"]))
    la = m["leave_one_exchange_out"]["look_alikes"]
    print(f"  negatives that forward {la['forwarding_at_least']:.0%} or more to one wallet, like "
          f"a deposit address: {la['flagged']} of {la['negatives']} called one")
    c = m["cross_fit"]
    print(f"cross-fit ({c['blocks']} time blocks per exchange; each address scored by a model "
          "that did not train on it; these are the labels' scores):")
    for r in c["by_exchange"]:
        print(row(r["exchange"], r, r["precision"], r["recall"]))
    p = c["pooled"]
    print(row("POOLED", p, p["at_0_5"]["precision"], p["at_0_5"]["recall"]))
    print(f"  range width {p['interval_mean_width']}; ranges consistent with the observed rate "
          f"in {p['range_check']['consistent']} of {len(p['range_check']['groups'])} groups; "
          f"look-alike negatives called a deposit address: {c['look_alikes']['flagged']} of "
          f"{c['look_alikes']['negatives']}")
    ab = m["ablation_label_features"]
    print(f"with the two label features (not shipped): by time PR-AUC "
          f"{ab['time_split']['pr_auc']}; on an exchange whose labels are hidden, pooled "
          f"recall {ab['leave_one_exchange_out']['pooled']['at_0_5']['recall']}")
    print("what the model leans on: " + ", ".join(
        f"{f['feature']} {f['importance']:.0%}" for f in m["feature_importance"][:5]))
    audit = m["leak_audit"]
    print(f"leak audit (address order, minute, second of first transfer): "
          f"{'none over the gate' if not audit['strict_over_gate'] else audit['strict_over_gate']}")
    confirmed = sum(1 for s in scores if s["basis"] == "model")
    print(f"scored {len(scores):,} derived labels: the model confirms {confirmed:,} (they carry "
          f"its confidence and range); {len(scores) - confirmed:,} keep the rules' confidence")
    print(f"wrote {Path(args.out) / args.chain}/ (run `make labels` to merge the scores)")


def cmd_abstain_eval(args) -> None:
    """Measure the abstain threshold on label-hidden traces of real exchange customers."""
    from . import chains
    from .cases import trace_provider
    from .classify.dataset import load_runs, read_dataset
    from .eval import abstain as A
    from .labels.lookup import LabelStore

    cfg = A.AbstainConfig(per_exchange=args.per_exchange, seed=args.seed)
    out = Path(args.out) / args.chain
    if args.from_claims:
        rows, stats = A.read_claims(out / "claims.csv"), None
    else:
        wallets = A.sample_wallets(read_dataset(Path(args.model) / args.chain / "dataset.csv"),
                                   cfg)
        caches = [chains.ChainCache(args.cache, hold=True), chains.ChainCache(hold=True)]
        fetcher = chains.Fetcher(chains.LayeredCache(*caches), chains.UrllibTransport())
        provider = trace_provider(args.chain, fetcher, cfg.trace)

        def progress(stage: str, i: int, n: int) -> None:
            if i == n or i % 20 == 0:
                print(f"  {stage}: {i}/{n}  ({_pages(fetcher)})", file=sys.stderr, flush=True)

        since = {r.name: r.since for r in load_runs(args.derived) if r.chain == args.chain}
        rows, stats = A.collect(wallets, args.chain, provider, lambda: LabelStore(args.labels_db),
                                cfg, workers=args.workers, progress=progress, since=since)
        for c in caches:
            c.close()
        A.write_claims(out / "claims.csv", rows)
        print(f"{stats['wallets_read']} of {stats['wallets_sampled']} wallets traced twice "
              f"({stats['errors']} could not be read) | {_pages(fetcher)}")
    m = A.measure(rows, args.chain, cfg)
    if stats:
        m["collected"] = stats
    elif (out / "validation.json").exists():
        m["collected"] = json.loads((out / "validation.json").read_text()).get("collected")
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps(m, indent=1, allow_nan=False) + "\n")
    (out / "risk_coverage.svg").write_text(A.risk_coverage_svg(m))
    print(f"abstain threshold, {args.chain} (seed {m['seed']}):")
    for note in m["notes"]:
        print("  - " + note)
    print(f"  {'bar':>5}{'named':>7}{'wrong':>7}{'risk':>8}{'upper':>8}{'abstain':>9}   "
          f"{'claims':>7}{'wrong':>7}")
    for b in m["bars"]:
        risk = "-" if b["risk"] is None else f"{b['risk']:.1%}"
        print(f"  {b['threshold']:>5.2f}{b['named']:>7}{b['wrong']:>7}{risk:>8}"
              f"{b['risk_upper_bound']:>8.1%}{b['abstained']:>9}   "
              f"{b['claims_answered']:>7}{b['claims_wrong']:>7}")
    print(f"wrote {out}/")


def cmd_trace(args) -> None:
    import sys
    import textwrap

    from . import chains
    from .explain import fmt
    try:
        case, fetcher = _run_case(args.address, args.chain, args.max_hops, args.labels_db,
                                  since=_since(args.since))
    except (chains.InvalidAddress, chains.ProviderError, FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    if args.save:
        from .store.cases import CaseStore
        CaseStore().save(case)
    if args.json:
        print(json.dumps(case, indent=2, sort_keys=True))
        return

    asset = case["asset"] or ""
    top = next((c for c in case["candidates"] if c["vasp"] == case["top_vasp"]
                and c["confidence"] == case["confidence"]), None)
    if top is not None and top["confidence_interval"]:
        said = (f"  {case['top_vasp']}  confidence {case['confidence']:.2f} "
                f"({fmt.prob_range(*top['confidence_interval'])})")
    elif case["top_vasp"]:
        said = f"  {case['top_vasp']}  rule confidence {case['confidence']:.2f}"
    else:
        said = ""
    print(f"{case['chain']}  {case['address']}  ->  {case['outcome']}{said}")
    print()
    print(textwrap.fill(case["narrative"], width=100))
    if case["candidates"]:
        print(f"\n  {'rank':<5}{'VASP':<24}{'dir':<5}{'conf':>6}{'hops':>6}{'share':>8}  "
              f"{'label tier':<15}entry address")
        for c in case["candidates"]:
            print(f"  {c['proximity_rank']:<5}{c['vasp'][:23]:<24}{c['direction'][:3]:<5}"
                  f"{c['confidence']:>6.2f}{c['hops']:>6}{fmt.pct(c['share_of_funds']):>8}  "
                  f"{c['label_tier']:<15}{c['deposit_address']}")
    if case["where_funds_went"]:
        print("\n  where the funds went")
        for w in case["where_funds_went"]:
            what = f"{w['kind'].replace('_', ' ')}" + (f": {w['name']}" if w["name"] else "")
            print(f"    {fmt.pct(w['share']):>8}  {fmt.amount(str(w['amount']), asset):>22}  {what}")
    for title, key in (("flags", "typology_flags"), ("what would change this", "what_would_change"),
                       ("next steps", "next_steps")):
        if case[key]:
            print(f"\n  {title}")
            for item in case[key]:
                print(textwrap.fill(item["text"] if isinstance(item, dict) else item, width=100,
                                    initial_indent="    - ", subsequent_indent="      "))
    g = case["graph"]
    print(f"\n{len(g['nodes'])} wallets, {len(g['edges'])} transfers | {_pages(fetcher)} | "
          f"case id {case['id']}" + (" (saved)" if args.save else ""))


def cmd_demo(args) -> None:
    """Run every wallet in demo/cases.json into the case store and check the results."""
    import sys

    from . import chains
    from .store.cases import CaseStore
    specs = json.loads(Path(args.file).read_text())["cases"]
    store = CaseStore()
    ok = 0
    print(f"  {'id':<19}{'chain':<10}{'outcome':<29}{'top VASP':<10}{'conf':>5}  pages")
    for spec in specs:
        try:
            case, fetcher = _run_case(spec["address"], spec["chain"], spec.get("max_hops", 3),
                                      args.labels_db, case_id=spec["id"], demo=True,
                                      meta={"case_ref": spec.get("case_ref")})
        except (chains.InvalidAddress, chains.ProviderError, FileNotFoundError) as e:
            print(f"  {spec['id']:<19}{spec['chain']:<10}FAILED: {e}", file=sys.stdout)
            continue
        store.save(case)
        want = (spec["expect"]["outcome"], spec["expect"]["top_vasp"])
        good = (case["outcome"], case["top_vasp"]) == want
        ok += good
        conf = f"{case['confidence']:.2f}" if case["confidence"] is not None else "-"
        s = fetcher.stats
        print(f"  {spec['id']:<19}{spec['chain']:<10}{case['outcome']:<29}"
              f"{case['top_vasp'] or '-':<10}{conf:>5}  {s['live']} live, {s['hits']} cached"
              + ("" if good else f"   !! expected {want[0]} / {want[1]}"))
    print(f"{ok}/{len(specs)} as expected | cases stored in {store.path}")
    if args.watchlist and Path(args.watchlist).exists():
        _seed_watchlist(args.watchlist, args.labels_db, store)
    same = len(specs)
    if args.golden:
        same = _golden(args.golden, [store.get(spec["id"]) for spec in specs])
    if ok != len(specs) or same != len(specs):
        raise SystemExit(1)


def watch_traces(path) -> list[dict]:
    """The demonstration watchlist's wallets that need a trace of their own, as case specs."""
    return [{"address": w["address"], "chain": w["chain"], **w["trace"]}
            for w in json.loads(Path(path).read_text())["watch"] if w.get("trace")]


def _seed_watchlist(path: str, labels_db: str, cases) -> None:
    """Put the demonstration watchlist (demo/watchlist.json) into the watch store. A wallet
    already watched is left as it is. A wallet no case has traced is traced first, as an
    ordinary case, so that its first check is a real one."""
    from datetime import datetime, timezone

    from . import chains
    from .store.watch import WatchStore, watch_id
    from .watch import snapshot
    watch, added = WatchStore(), 0
    for w in json.loads(Path(path).read_text())["watch"]:
        wid = watch_id(w["chain"], w["address"])
        if watch.get(wid) is not None:
            continue
        case = cases.find(w["chain"], w["address"])
        if case is None and w.get("trace"):
            try:
                case, _ = _run_case(w["address"], w["chain"], w["trace"].get("max_hops", 1),
                                    labels_db, case_id=w["trace"]["id"])
                cases.save(case)
            except (chains.InvalidAddress, chains.ProviderError, FileNotFoundError) as e:
                # watched all the same: it reads "not traced yet" until a check succeeds
                print(f"  {w['trace']['id']}: could not be traced for its first check: {e}")
        done = case is not None and case.get("status") == "done" and "candidates" in case
        watch.save({"id": wid, "chain": w["chain"], "address": w["address"], "note": w["note"],
                    "added_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "added_by": "demonstration set-up",
                    "baseline": snapshot(case) if done else None})
        added += 1
    print(f"{len(watch.list())} wallets on the watchlist ({added} added) | {watch.path}")


def _golden(path: str, cases: list) -> int:
    """How many stored demo cases have the findings fingerprint the repository records
    for them (tests/golden/fingerprints.json)."""
    golden = json.loads(Path(path).read_text())
    same = 0
    for case in cases:
        if case is None:
            continue
        got = (case.get("provenance") or {}).get("findings_sha256")
        want = golden.get(case["id"], {}).get("findings_sha256")
        if got == want:
            same += 1
        else:
            print(f"  !! {case['id']}: fingerprint {got}, golden {want}")
    print(f"{same}/{len(cases)} golden fingerprints reproduced ({path})")
    return same


def cmd_demo_cache(args) -> None:
    """Build a chain cache holding exactly the pages the demo wallets' traces read, from
    the recorded fixtures (no network). The offline image ships this file."""
    import os

    from . import chains
    from .cases import file_sha256, run_case, trace_provider
    from .chains.replay import RecordedTransport
    from .classify.runtime import make_scorer
    from .labels.lookup import LabelStore
    from .trace import TraceConfig

    specs = json.loads(Path(args.file).read_text())["cases"]
    if args.watchlist and Path(args.watchlist).exists():
        specs = specs + watch_traces(args.watchlist)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.unlink(missing_ok=True)
    sha = file_sha256(args.labels_db)
    try:
        cache = chains.ChainCache(tmp)
        with LabelStore(args.labels_db) as labels:
            for spec in specs:
                transport = RecordedTransport(Path(args.fixtures) / f"{spec['id']}.json")
                fetcher = chains.Fetcher(cache, transport, offline=False, sleep=lambda s: None)
                cfg = TraceConfig(max_hops=spec.get("max_hops", 3))
                # any key selects the backend the fixtures were recorded from; none is sent
                case = run_case(spec["address"], spec["chain"],
                                trace_provider(spec["chain"], fetcher, cfg, key="recorded"),
                                labels, case_id=spec["id"], cfg=cfg, fetcher=fetcher,
                                label_db_sha256=sha, demo="expect" in spec,
                                scorer=make_scorer(spec["chain"], fetcher, key="recorded"))
                print(f"  {spec['id']:<27}{case['outcome']:<29}{case['top_vasp'] or '-':<10}"
                      f"{case['provenance']['pages']} pages")
    except chains.ProviderError as e:
        tmp.unlink(missing_ok=True)
        print(f"error: {e}\nThe trace asked for a page the fixtures do not hold: the label "
              f"DB is not the one they were recorded with, or the code reads more pages. "
              f"Re-record them (scripts/record_demo_fixtures.py --extend) or rebuild the "
              f"label DB (`make labels`).", file=sys.stderr)
        raise SystemExit(1) from e
    pages = cache.count()
    os.replace(tmp, out)
    print(f"wrote {out} ({pages} pages, no network)")


def cmd_case_pdf(args) -> None:
    """Write a stored case's file (A4 PDF) and its receipt (JSON) to data/exports/."""
    from .explain.case_file import NotReady
    from .explain.case_pdf import case_pdf
    from .provenance import receipt
    from .store.cases import CaseStore

    case = CaseStore().get(args.case_id)
    if case is None:
        print(f"error: no case {args.case_id}", file=sys.stderr)
        raise SystemExit(1)
    try:
        pdf = case_pdf(case)
    except NotReady as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    out = Path(args.out) if args.out else ROOT / "data" / "exports" / f"case-{case['id']}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf)
    print(f"  case file  {out}  ({len(pdf):,} bytes)")
    doc = receipt(case)
    if doc is not None:
        side = out.with_suffix(".receipt.json")
        side.write_text(json.dumps(doc, indent=2) + "\n")
        print(f"  receipt    {side}\n  fingerprint {doc['findings_sha256']}")


def cmd_verify(args) -> None:
    """Trace stored cases again from the cache only and compare the fingerprints."""
    from . import chains
    from .cases import file_sha256, verify_receipt, verify_stored
    from .labels.lookup import LabelStore
    from .store.cases import CaseStore

    sha = file_sha256(args.labels_db)
    fetcher = chains.cache_only_fetcher()
    with LabelStore(args.labels_db) as labels:
        if args.receipt:
            doc = json.loads(Path(args.receipt).read_text())
            results = [verify_receipt(doc, fetcher, labels, label_db_sha256=sha)]
        else:
            store = CaseStore()
            if args.all:
                ids = [c["id"] for c in reversed(store.list(status="done"))]
            elif args.case_id:
                ids = [args.case_id]
            else:
                print("error: name a case id, or use --all or --receipt FILE", file=sys.stderr)
                raise SystemExit(1)
            results = []
            for cid in ids:
                case = store.get(cid)
                if case is None:
                    print(f"error: no case {cid} in {store.path}", file=sys.stderr)
                    raise SystemExit(1)
                results.append(verify_stored(case, fetcher, labels, label_db_sha256=sha))
    good = sum(r["matches"] for r in results)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        detail = len(results) == 1
        for r in results:
            fp = next((c["stored"] for c in r["checks"] if c["name"] == "findings"), None)
            print(f"  {r['case_id'] or '-':<19}{'VERIFIED' if r['matches'] else 'NOT VERIFIED':<14}"
                  + (f"fingerprint {fp}" if fp else ""))
            if detail or not r["matches"]:
                for c in r["checks"]:
                    print(f"      {c['name']:<12}{c['result']:<12}{c['detail']}")
                if not r["checks"]:
                    print(f"      {r['summary']}")
        print(f"{good}/{len(results)} verified | cache {fetcher.cache.path} (read only, no network)")
    if good != len(results):
        raise SystemExit(1)


def _desk_service():
    from .desk.directory import Directory
    from .desk.gateway import MockSahyogGateway
    from .desk.service import DeskService
    from .store.cases import CaseStore
    from .store.requests import RequestStore
    return DeskService(CaseStore(), RequestStore(), Directory.load(), MockSahyogGateway())


def cmd_desk(args) -> None:
    """The request desk: one row per exchange, from every finished case in the store."""
    svc = _desk_service()
    desk = svc.desk()
    if args.json:
        print(json.dumps(desk, indent=1))
        return
    if not desk["rows"]:
        print("No finished case names an exchange yet. Run `make demo` or trace a wallet.")
        return
    print(f"  {'exchange':<12}{'wallets':>8}{'USD':>14}  {'status':<17}{'FIU-IND':<22}next")
    for r in desk["rows"]:
        e = svc.directory.get(r["vasp"])
        fiu = "no source" if e["fiu_ind_registered"] is None else (
            ("registered" if e["fiu_ind_registered"] else "not registered")
            + f" ({e['fiu_ind_as_of']:%b %Y})")
        print(f"  {r['vasp']:<12}{r['wallet_count']:>8}{r['total_usd']:>14,.2f}  "
              f"{r['status']:<17}{fiu:<22}{r['next_action']}"
              + (f"  [{r['last_request_id']}]" if r["last_request_id"] else ""))
        print(f"  {'':<12}cases: {', '.join(r['case_ids'])}")
    for f in desk["follow_ups"]:
        print(f"  !! {f['text']}  [{f['request_id']}]")


def cmd_request(args) -> None:
    """Draft one consolidated request to an exchange and write its letter as a PDF."""
    from .desk.routing import routed_wallets
    from .desk.service import DeskError
    svc = _desk_service()
    vasp = svc.directory.canonical(args.vasp)
    case_ids = [c for c in (args.cases or "").split(",") if c] or sorted(
        case["id"] for case in svc._all_cases()
        if any(w["vasp"] == vasp for w in routed_wallets(case, canonical=svc.directory.canonical)))
    try:
        if not case_ids:
            raise DeskError(422, f"No finished case routes a wallet to {vasp}. See `make desk`.")
        req = svc.create(vasp, case_ids, args.asks.split(","), args.officer)
        if args.approve or args.send:
            req = svc.patch(req["id"], "approved")
        if args.send:
            req = svc.patch(req["id"], "sent")
    except DeskError as e:
        raise SystemExit(f"{e}") from None
    out = Path(args.out) if args.out else ROOT / "data" / "exports" / f"{req['id']}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(svc.pdf(req["id"]))
    letter = req["letter"]
    print(f"{req['id']}  {req['reference']}  {req['status']}"
          + (f"  (reply due {req['due']})" if req["due"] else ""))
    print(f"  to       {letter['to']}")
    if letter["channel"]:
        print(f"  channel  {letter['channel']}")
    print(f"  cases    {', '.join(c['case_ref'] or c['case_id'] for c in letter['cases'])}")
    for w in letter["wallets"]:
        from .explain import fmt
        print(f"  wallet   {w['address']}  {fmt.amount(w['amount'], w['asset'])}  "
              f"{w['tier']}  confidence {fmt.prob(w['confidence'])}")
    print(f"  asks     {', '.join(letter['asks'])}")
    for note in letter["review_notes"]:
        print(f"  check    {note}")
    if req["receipt"]:
        print(f"  outbox   {req['receipt']['location']}")
    print(f"  letter   {out}" + ("   (DRAFT: officer review required)"
                                 if letter["watermark"] else ""))


def cmd_officer(args) -> None:
    """Officer accounts (data/officers.json). Once one exists, the API asks for a login."""
    from .auth.officers import Officers
    book = Officers()
    try:
        if args.do == "list":
            rows = book.list()
            for r in rows:
                print(f"  {r['username']:<20}{r['name']:<32}{r['post'] or '-':<28}"
                      f"{'disabled' if r['disabled'] else 'active'}")
            state = "not required (no account)" if not rows else \
                "required" if book.active() else \
                "required, and every account is disabled: nobody can sign in"
            print(f"{len(rows)} officer(s) in {book.path} | login {state}")
        elif args.do == "disable":
            book.disable(args.username)
            print(f"disabled {args.username}")
        elif args.do == "demo":
            spec = json.loads(Path(args.file).read_text())
            if book.get(spec["username"]) is None:
                book.add(spec["username"], spec["name"], spec["password"], spec.get("post"))
            print(f"demo officer {spec['username']} is in {book.path}; its password is in "
                  f"{args.file}. For demonstrations only.")
        else:
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\n")
            else:
                import getpass
                password = getpass.getpass("Password (10 characters or more): ")
                if getpass.getpass("Again: ") != password:
                    raise ValueError("The two passwords differ.")
            made = book.add(args.username, args.name, password, args.post)
            print(f"added {made['username']} ({made['name']}) to {book.path}; the API now "
                  f"asks for a login")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e


def cmd_audit(args) -> None:
    """The audit log: who looked up what, and when; `--verify` recomputes its hash chain."""
    from .store.audit import AuditLog
    log = AuditLog()
    if args.verify:
        check = log.verify_chain()
        head = check["head"]
        if check["ok"]:
            print(f"OK: {check['rows']} rows, every hash follows the one before it\n"
                  f"head: row {head['seq']}  {head['hash']}\n"
                  f"(note the head somewhere else: rows cut off the end are only caught "
                  f"against a head that was noted)")
        else:
            print(f"BROKEN at row {check['broken_at']}: {check['reason']}")
            raise SystemExit(1)
        return
    total, rows = log.list(limit=args.limit, officer=args.officer, action=args.action,
                           target=args.target)
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    for r in reversed(rows):
        print(f"  {r['seq']:>6}  {r['at']}  {r['officer'] or '(not signed in)':<18}"
              f"{r['action']:<16}{r['status']:<5}{r['target'] or ''}")
    print(f"{len(rows)} of {total} rows | {log.path}")


def cmd_serve(args) -> None:
    import uvicorn
    uvicorn.run("vaspfusion.api.main:app", host=args.host, port=args.port)


def cmd_openapi(args) -> None:
    from .api.main import app
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"wrote {out}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="vaspfusion")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("labels", help="build the label DB and print its stats")
    s.add_argument("--research", default=str(ROOT.parent / "research" / "data"))
    s.add_argument("--db", default=str(ROOT / "data" / "labels.duckdb"))
    s.add_argument("--derived", default=str(ROOT / "derived"),
                   help="folder of discovery CSVs (`discover` writes them); merged as tier=derived")
    s.add_argument("--model", default=str(ROOT / "artifacts" / "model_v1"),
                   help="folder of the deposit-address model: its <chain>/scores.csv set the "
                        "confidence of the derived labels it scored")
    s.set_defaults(fn=cmd_labels)

    research = ROOT.parent / "research" / "data"
    s = sub.add_parser("tagpacks", help="flatten the GraphSense exchange TagPacks into the CSV "
                                        "`labels` reads")
    s.add_argument("--packs", default=str(research / "graphsense-tagpacks" / "packs"))
    s.add_argument("--out", default=str(research / TAGPACKS_CSV))
    s.set_defaults(fn=cmd_tagpacks)

    s = sub.add_parser("fetch", help="fetch an address's transfers (cached; OFFLINE=1 = cache only)")
    s.add_argument("address")
    s.add_argument("--chain", help="tron, ethereum, polygon, arbitrum, base, optimism, bsc, "
                                   "bitcoin, solana (default: auto-detect; EVM -> ethereum)")
    s.add_argument("--direction", choices=("both", "in", "out"), default="both")
    s.add_argument("--since", help="ISO date/time (UTC if no zone)")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--json", action="store_true", help="one JSON transfer per line")
    s.add_argument("--refresh", action="store_true", help="ignore cached pages, re-fetch live")
    s.add_argument("--labels", choices=("auto", "none"), default="auto",
                   help="name labelled counterparties from the label DB")
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("trace", help="trace a wallet to its nearest exchange(s) and print the case")
    s.add_argument("address")
    s.add_argument("--chain", help="default: auto-detect (EVM -> ethereum)")
    s.add_argument("--max-hops", type=int, default=3, choices=range(1, 6))
    s.add_argument("--since", help="only the wallet's transfers from this ISO date/time on")
    s.add_argument("--json", action="store_true", help="print the CaseDetail JSON")
    s.add_argument("--save", action="store_true", help="store the case (data/case.duckdb)")
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_trace)

    s = sub.add_parser("discover", help="derive deposit addresses from labelled exchange "
                                        "wallets (sweep + gas-payer rules)")
    s.add_argument("--chain", default="tron")
    s.add_argument("--since", help="window start, ISO date/time (default 2026-09-24)")
    s.add_argument("--lookback-days", type=int, default=7)
    s.add_argument("--seed-limit", type=int, default=1000,
                   help="inbound transfers read per exchange wallet")
    s.add_argument("--candidate-limit", type=int, default=50)
    s.add_argument("--max-candidates", type=int, help="per exchange wallet")
    s.add_argument("--entities", help="comma-separated exchange names (default: all)")
    s.add_argument("--out", default=str(ROOT / "derived"),
                   help="folder for <chain>.csv and <chain>_report.json (tracked in git)")
    s.add_argument("--cache", default=str(ROOT / "data" / "discover_cache.duckdb"),
                   help="the crawl's own chain cache (OFFLINE=1 replays from it)")
    s.add_argument("--workers", type=int, default=6, help="parallel fetches")
    s.add_argument("--name", help="output file name (default: the chain); a second run "
                                  "with another window keeps its own files")
    s.add_argument("--max-hours", type=float, help="sweep rule: how long after arriving a "
                                                   "deposit may be forwarded")
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_discover)

    s = sub.add_parser("discover-eval", help="measure the discovery rules on held-out "
                                             "explorer-tagged deposit addresses")
    s.add_argument("--chain", default="ethereum")
    s.add_argument("--entity", default="Bitget")
    s.add_argument("--positives", type=int, default=300)
    s.add_argument("--negatives", type=int, default=300)
    s.add_argument("--seed", type=int, default=26182)
    s.add_argument("--limit", type=int, default=200, help="transfers read per address")
    s.add_argument("--max-hours", type=float, help="sweep rule time limit (default: the "
                                                   "rule's own)")
    s.add_argument("--name", help="output file name (default holdout_<chain>_<entity>)")
    s.add_argument("--out", default=str(ROOT / "derived"))
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_discover_eval)

    s = sub.add_parser("model-data", help="build the deposit-address model's training set "
                                          "(cached; OFFLINE=1 replays)")
    s.add_argument("--chain", default="tron")
    s.add_argument("--derived", default=str(ROOT / "derived"))
    s.add_argument("--out", default=str(ROOT / "artifacts" / "model_v1"))
    s.add_argument("--crawl-cache", default=str(ROOT / "data" / "discover_cache.duckdb"),
                   help="the discovery crawl's cache: it holds the positives")
    s.add_argument("--cache", default=str(ROOT / "data" / "model_cache.duckdb"),
                   help="the cache the negatives are fetched into")
    s.add_argument("--per-exchange", type=int, default=700, help="customers sampled per exchange")
    s.add_argument("--seed", type=int, default=26182)
    s.add_argument("--workers", type=int, default=6, help="parallel fetches")
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_model_data)

    s = sub.add_parser("model", help="train, calibrate and measure the deposit-address "
                                     "model on the dataset; score the derived labels")
    s.add_argument("--chain", default="tron")
    s.add_argument("--derived", default=str(ROOT / "derived"))
    s.add_argument("--out", default=str(ROOT / "artifacts" / "model_v1"))
    s.add_argument("--seed", type=int, default=26182)
    s.set_defaults(fn=cmd_model)

    s = sub.add_parser("abstain-eval", help="measure the abstain threshold on real exchange "
                                            "customers traced with the derived labels hidden")
    s.add_argument("--chain", default="tron")
    s.add_argument("--model", default=str(ROOT / "artifacts" / "model_v1"),
                   help="the deposit model's folder: its dataset.csv lists the customers")
    s.add_argument("--derived", default=str(ROOT / "derived"),
                   help="the discovery runs: each wallet is traced from its run's start")
    s.add_argument("--out", default=str(ROOT / "artifacts" / "abstain_v1"))
    s.add_argument("--cache", default=str(ROOT / "data" / "abstain_cache.duckdb"),
                   help="the cache the traces are fetched into (the main cache is read too)")
    s.add_argument("--per-exchange", type=int, default=40, help="wallets sampled per exchange")
    s.add_argument("--seed", type=int, default=26182)
    s.add_argument("--workers", type=int, default=6, help="wallets traced in parallel")
    s.add_argument("--from-claims", action="store_true",
                   help="no tracing: measure again from the tracked claims.csv")
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_abstain_eval)

    s = sub.add_parser("demo", help="run the demo wallets into the case store and check them")
    s.add_argument("--file", default=str(ROOT / "demo" / "cases.json"))
    s.add_argument("--watchlist", default=str(ROOT / "demo" / "watchlist.json"),
                   help="the demonstration watchlist ('' = leave the watchlist alone)")
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.add_argument("--golden", help="also require each case's findings fingerprint to equal "
                                    "the one in this file (tests/golden/fingerprints.json)")
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("demo-cache", help="build the demo's chain cache from the recorded "
                                          "fixtures (no network)")
    s.add_argument("--file", default=str(ROOT / "demo" / "cases.json"))
    s.add_argument("--watchlist", default=str(ROOT / "demo" / "watchlist.json"),
                   help="the demonstration watchlist ('' = leave the watchlist alone)")
    s.add_argument("--fixtures", default=str(ROOT / "tests" / "fixtures" / "demo"))
    s.add_argument("--out", default=str(ROOT / "data" / "demo_cache.duckdb"))
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_demo_cache)

    s = sub.add_parser("case-pdf", help="write a stored case's file (A4 PDF) and its receipt")
    s.add_argument("case_id")
    s.add_argument("--out", help="PDF path (default: data/exports/case-<id>.pdf)")
    s.set_defaults(fn=cmd_case_pdf)

    s = sub.add_parser("verify", help="trace a stored case again from the cache only and "
                                      "compare its findings fingerprint")
    s.add_argument("case_id", nargs="?")
    s.add_argument("--all", action="store_true", help="every finished case in the store")
    s.add_argument("--receipt", help="verify an exported receipt file instead of a stored case")
    s.add_argument("--json", action="store_true")
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("desk", help="the request desk: exchanges the finished cases route to")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_desk)

    s = sub.add_parser("request", help="draft one consolidated request to an exchange "
                                       "and write its letter PDF")
    s.add_argument("vasp")
    s.add_argument("--officer", required=True, help="who makes the request (name, post)")
    s.add_argument("--cases", help="comma-separated case ids (default: every finished case "
                                   "that routes a wallet to this exchange)")
    s.add_argument("--asks", default="kyc,transactions,freeze,preservation")
    s.add_argument("--approve", action="store_true", help="approve the draft (no watermark)")
    s.add_argument("--send", action="store_true",
                   help="approve and hand to the mock SAHYOG gateway (a local outbox)")
    s.add_argument("--out", help="PDF path (default: data/exports/<request id>.pdf)")
    s.set_defaults(fn=cmd_request)

    s = sub.add_parser("officer", help="officer accounts: add | list | disable | demo")
    s.add_argument("do", choices=("add", "list", "disable", "demo"))
    s.add_argument("username", nargs="?")
    s.add_argument("--name", help="as printed on letters, e.g. 'Insp. A. Rao'")
    s.add_argument("--post")
    s.add_argument("--password-stdin", action="store_true",
                   help="read the password from standard input instead of asking")
    s.add_argument("--file", default=str(ROOT / "demo" / "officer.json"),
                   help="demo: the demonstration account to create")
    s.set_defaults(fn=cmd_officer)

    s = sub.add_parser("audit", help="the audit log: who looked up what, and when")
    s.add_argument("--verify", action="store_true", help="recompute the hash chain")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--officer")
    s.add_argument("--action", help="an action (case.view) or a family (case)")
    s.add_argument("--target", help="e.g. a case id")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("serve", help="run the API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("openapi", help="write the OpenAPI schema")
    s.add_argument("--out", default=str(ROOT / "docs" / "openapi.json"))
    s.set_defaults(fn=cmd_openapi)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
