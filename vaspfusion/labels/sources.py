"""Where the labels come from, and under what licence we hold them.

Only what is on record in this project is stated. The wallet-attribution set releases
its code under MIT and says of its data that each upstream source "retains its own
upstream license"; those licences are not recorded here, so they read as not recorded
(None), never as MIT. GraphSense TagPacks are MIT (`SOURCE.json` beside the packs).
"""
from __future__ import annotations

WALLET_ATTRIBUTION = "wallet-attribution set"

# family -> (name, obtained from, licence or None, url)
SOURCES: dict[str, tuple[str, str, str | None, str | None]] = {
    "eth-labels": ("eth-labels: public tags of block explorers", WALLET_ATTRIBUTION, None,
                   "https://github.com/dawsbot/eth-labels"),
    "defillama-cex": ("DefiLlama adapters: reserve wallets the exchanges published",
                      WALLET_ATTRIBUTION, None,
                      "https://github.com/DefiLlama/DefiLlama-Adapters"),
    "ofac-sdn": ("OFAC SDN list of sanctioned addresses", WALLET_ATTRIBUTION,
                 "US-government public record",
                 "https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses"),
    "mew-ethereum-lists": ("MyEtherWallet ethereum-lists: scam addresses", WALLET_ATTRIBUTION,
                           None, "https://github.com/MyEtherWallet/ethereum-lists"),
    "cex-list": ("cex-list: exchange hot wallets", WALLET_ATTRIBUTION, None,
                 "https://github.com/tradezon/cex-list"),
    "dune-spellbook": ("Dune spellbook: Indian exchanges' wallets", "Dune spellbook extract",
                       None, "https://github.com/duneanalytics/spellbook"),
    "graphsense-tagpacks": ("GraphSense TagPacks: exchange packs", "GraphSense TagPacks", "MIT",
                            "https://github.com/graphsense/graphsense-tagpacks"),
    "vaspfusion-discover": ("Deposit addresses derived by VASP-FUSION (sweep and gas-payer "
                            "rules)", "computed by this tool", "computed here, not a "
                            "third-party set", None),
}


def family(source: str) -> str:
    """The source a label row is counted under: the first named source of a merged row."""
    parts = [p.strip() for p in source.split("+")]
    for p in parts:
        if p.startswith("graphsense-tagpack:"):
            return "graphsense-tagpacks"
        if p in SOURCES:
            return p
    return parts[0]


def by_source(rows: list[tuple[str, str, int]]) -> list[dict]:
    """`rows` are (source, tier, count) groups of the label table. Largest first."""
    out: dict[str, dict] = {}
    for source, tier, n in rows:
        key = family(source)
        name, obtained, licence, url = SOURCES.get(key, (key, None, None, None))
        row = out.setdefault(key, {"source": key, "name": name, "obtained_from": obtained,
                                   "licence": licence, "url": url, "labels": 0, "tiers": {}})
        row["labels"] += n
        row["tiers"][tier] = row["tiers"].get(tier, 0) + n
    return sorted(out.values(), key=lambda r: (-r["labels"], r["source"]))
