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
