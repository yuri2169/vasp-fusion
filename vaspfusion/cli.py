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
    print(f"{len(rows)} transfers | pages: {s['live']} live, {s['hits']} cached | "
          f"OFFLINE={1 if fetcher.offline else 0} | cache {fetcher.cache.path}")


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
