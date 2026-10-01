"""Command line: `python -m vaspfusion.cli <command>`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _table(title: str, counts: dict, total: int) -> str:
    lines = [f"  {title}"]
    for k, v in counts.items():
        lines.append(f"    {k:<22}{v:>9,}  {100 * v / max(total, 1):5.1f}%")
    return "\n".join(lines)


def cmd_labels(args) -> None:
    from .labels.load import build_labels
    research = Path(args.research)
    stats = build_labels(Path(args.db), research / "wallet-attribution" / "data",
                         research / "indian_vasps_dune_spellbook.csv")
    t = stats["total"]
    print(f"labels -> {args.db}")
    print(f"  raw rows {stats['raw_rows']:,}  duplicates dropped "
          f"{stats['duplicates_dropped']:,}  unique (address, chain) {t:,}")
    print(f"  unusable addresses dropped {stats['invalid_dropped']:,} (valid on no chain, e.g. "
          f"truncated upstream)  re-filed to their real chain {stats['chain_refiled']:,}")
    ex = stats["by_category"].get("exchange", 0)
    print(f"  exchange rows {ex:,} = {ex - stats['exchange_tag_promoted']:,} upstream + Dune "
          f"exchange rows + {stats['exchange_tag_promoted']:,} promoted by Etherscan's Exchange tag")
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
                               for k in ("TRONGRID_API_KEY", "ETHERSCAN_API_KEY")))
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
    print(f"{case['chain']}  {case['address']}  ->  {case['outcome']}"
          + (f"  {case['top_vasp']}  rule confidence {case['confidence']:.2f}"
             if case["top_vasp"] else ""))
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
    if ok != len(specs):
        raise SystemExit(1)


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
    s.set_defaults(fn=cmd_labels)

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

    s = sub.add_parser("demo", help="run the demo wallets into the case store and check them")
    s.add_argument("--file", default=str(ROOT / "demo" / "cases.json"))
    s.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    s.set_defaults(fn=cmd_demo)

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
