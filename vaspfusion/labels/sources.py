"""Where the labels come from, and under what licence we hold them.

Only what is on record in this project is stated. The wallet-attribution set releases
its code under MIT and says of its data that each upstream source "retains its own
upstream license"; a licence that was not read at its source reads as not recorded
(None), never as MIT. GraphSense TagPacks are MIT (`SOURCE.json` beside the packs), and
so is the eth-labels repository (its licence file, read 8 Oct 2026).

The links are citations shown beside a source's name. Nothing here is ever fetched.
"""
from __future__ import annotations

WALLET_ATTRIBUTION = "wallet-attribution set"

ETH_LABELS_SOURCE_URL = "https://github.com/dawsbot/eth-labels"
DEFILLAMA_SOURCE_URL = "https://github.com/DefiLlama/DefiLlama-Adapters"
OFAC_SOURCE_URL = "https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses"
MEW_SOURCE_URL = "https://github.com/MyEtherWallet/ethereum-lists"
CEX_LIST_SOURCE_URL = "https://github.com/tradezon/cex-list"
DUNE_SOURCE_URL = "https://github.com/duneanalytics/spellbook"
TAGPACKS_SOURCE_URL = "https://github.com/graphsense/graphsense-tagpacks"
OFAC_XML_SOURCE_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"
RANSOMWHERE_SOURCE_URL = "https://ransomwhe.re"

# Explorer deposit tags that upstream files under another exchange's name, named after
# the tag once checked on chain (tagcheck.py). Counted apart from the other explorer tags.
TAG_CHECKED_SOURCE = "eth-labels-checked-deposit-tags"
ETH_LABELS_LICENCE = "MIT (the eth-labels repository, read 8 Oct 2026; the tags are Etherscan's)"

# family -> (name, obtained from, licence or None, link)
SOURCES: dict[str, tuple[str, str, str | None, str | None]] = {
    "eth-labels": ("eth-labels: public tags of block explorers", WALLET_ATTRIBUTION,
                   ETH_LABELS_LICENCE, ETH_LABELS_SOURCE_URL),
    TAG_CHECKED_SOURCE: ("eth-labels: Etherscan \"Binance Dep\" tags, filed upstream under "
                         "another name and checked on chain here", WALLET_ATTRIBUTION,
                         ETH_LABELS_LICENCE, ETH_LABELS_SOURCE_URL),
    "defillama-cex": ("DefiLlama adapters: reserve wallets the exchanges published",
                      WALLET_ATTRIBUTION, None, DEFILLAMA_SOURCE_URL),
    "ofac-sdn": ("OFAC SDN list of sanctioned addresses", WALLET_ATTRIBUTION,
                 "US-government public record", OFAC_SOURCE_URL),
    "mew-ethereum-lists": ("MyEtherWallet ethereum-lists: scam addresses", WALLET_ATTRIBUTION,
                           None, MEW_SOURCE_URL),
    "cex-list": ("cex-list: exchange hot wallets", WALLET_ATTRIBUTION, None,
                 CEX_LIST_SOURCE_URL),
    "dune-spellbook": ("Dune spellbook: Indian exchanges' wallets", "Dune spellbook extract",
                       None, DUNE_SOURCE_URL),
    "graphsense-tagpacks": ("GraphSense TagPacks: exchange, darknet-market, ransomware and "
                            "fraud packs", "GraphSense TagPacks", "MIT", TAGPACKS_SOURCE_URL),
    "ofac-sdn-xml": ("OFAC SDN list, the official XML with sanctions programme codes",
                     "US Treasury, OFAC", "US-government public record", OFAC_XML_SOURCE_URL),
    "ransomwhere": ("Ransomwhere: crowdsourced ransomware payment addresses", "Ransomwhere",
                    "CC BY 4.0", RANSOMWHERE_SOURCE_URL),
    "vaspfusion-discover": ("Deposit addresses derived by VASP-FUSION (sweep and gas-payer "
                            "rules)", "Computed by this tool", "Not a third-party set: "
                            "computed here", None),
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
    for row in out.values():   # the table's groups come in no fixed order: largest tier first
        row["tiers"] = dict(sorted(row["tiers"].items(), key=lambda kv: (-kv[1], kv[0])))
    return sorted(out.values(), key=lambda r: (-r["labels"], r["source"]))
