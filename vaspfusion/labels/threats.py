"""Threat tags: which addresses public sources tie to ransomware, darknet markets,
terrorism financing or fraud, with the source's own words kept as evidence.

Three raw sources are read, each with the rules of config/threats.yaml:

  * the OFAC SDN list (the official XML): an entry's sanctions programme codes, and for
    a handful of entries the Treasury press release of their designation;
  * the Ransomwhere export: ransomware payment addresses with the family named;
  * GraphSense TagPacks: packs whose `abuse` or `category` field says what they are.

`cli threats` flattens them into data/threat_tags.csv (tracked), one row per
(address, chain): where two sources tag one address, the more specific threat wins, then
the source listed first in the config. `make labels` joins that file onto the label table.
Nothing here guesses: an address no rule matches gets no tag.
"""
from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "threats.yaml"
DEFAULT_CSV = ROOT / "data" / "threat_tags.csv"
COLUMNS = ["address", "chain", "threat", "entity", "source", "source_url", "evidence", "also"]
OFAC_SOURCE = "ofac-sdn-xml"
UK_SOURCE = "uk-sanctions-list"
EU_SOURCE = "eu-fsf"
NBCTF_SOURCE = "il-nbctf"
# government lists of sanctioned parties: an address on one is filed `sanctioned`
SANCTIONS_SOURCES = (OFAC_SOURCE, UK_SOURCE, EU_SOURCE)
RANSOMWHERE_SOURCE = "ransomwhere"
TAGPACK_PREFIX = "graphsense-tagpack:"
THREAT_WORDS = {"terrorism_financing": "terrorism financing", "ransomware": "ransomware",
                "darknet_market": "a darknet market", "theft": "theft by hack or exploit",
                "fraud": "fraud",
                "sanctioned_other": "a sanctioned party"}
_ID_PREFIX = "Digital Currency Address - "
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@lru_cache(maxsize=4)
def _config(path: str) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    known = set(cfg["threats"])
    used = set(cfg["ofac"]["programmes"].values()) | set(cfg["graphsense"]["abuse"].values()) \
        | {e["threat"] for e in cfg["ofac"]["entities"].values()} \
        | {r["threat"] for r in (cfg.get("explorer_tags") or {}).get("rules", [])}
    if not used <= known:
        raise ValueError(f"config/threats.yaml maps to unknown threats: {sorted(used - known)}")
    for uid, e in cfg["ofac"]["entities"].items():
        if not e.get("basis") or not e.get("url"):
            raise ValueError(f"OFAC entity {uid} is tagged without a basis and a url")
    return cfg


def config(path: Path | str | None = None) -> dict:
    return _config(str(path or DEFAULT_CONFIG))


def threats(path: Path | str | None = None) -> list[str]:
    return list(config(path)["threats"])


def source_family(source: str) -> str:
    return "graphsense-tagpacks" if source.startswith(TAGPACK_PREFIX) else source


def source_name(source: str, path: Path | str | None = None) -> str:
    """How a threat source is named in a sentence: 'OFAC SDN list', 'Ransomwhere'."""
    short = {OFAC_SOURCE: "OFAC SDN list", RANSOMWHERE_SOURCE: "Ransomwhere",
             UK_SOURCE: "UK Sanctions List", EU_SOURCE: "EU financial sanctions list",
             NBCTF_SOURCE: "Israel NBCTF seizure order",
             "graphsense-tagpacks": "GraphSense TagPacks", "ofac-sdn": "OFAC SDN list",
             "mew-ethereum-lists": "MyEtherWallet scam list", "eth-labels": "explorer tag"}
    first = source.split("+")[0].strip()
    return short.get(source_family(first), first)


def _chain_by_form(address: str) -> str | None:
    from vaspfusion.chains.addresses import detect_chain
    from vaspfusion.chains.base import InvalidAddress
    try:
        return detect_chain(address)
    except InvalidAddress:
        return None


# ------------------------------------------------------------------ reading a tag
def tag_of(label) -> dict | None:
    """The threat tag of a label (a `Label`, or its dict), as the API's `ThreatTag`."""
    get = label.get if isinstance(label, dict) else lambda k: getattr(label, k, None)
    if label is None or not get("threat"):
        return None
    return {"threat": get("threat"), "entity": get("threat_entity"),
            "source": get("threat_source"), "url": get("threat_url"),
            "evidence": get("threat_evidence")}


def named(tag: dict) -> str:
    """'ransomware (Conti, Ransomwhere)': the threat in words, who, and who says so."""
    who = ", ".join(p for p in (tag.get("entity"), source_name(tag["source"])
                                if tag.get("source") else None) if p)
    return f"{THREAT_WORDS[tag['threat']]} ({who})" if who else THREAT_WORDS[tag["threat"]]


# ------------------------------------------------------------------ OFAC SDN XML
def _iso_date(us: str) -> str:
    """The list's own 'MM/DD/YYYY' as YYYY-MM-DD (left as it is if it is anything else)."""
    parts = us.split("/")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[2]}-{parts[0]:0>2}-{parts[1]:0>2}"
    return us


def read_ofac(xml_path: Path | str, cfg: dict | None = None) -> list[dict]:
    """One row per digital-currency address of the SDN list. The threat comes from the
    entry's uid (config `ofac.entities`), else its programme codes, else it is
    `sanctioned_other`. The evidence carries the entry's name, uid and programmes."""
    cfg = cfg or config()
    o = cfg["ofac"]
    order = cfg["threats"]
    root = ET.parse(str(xml_path)).getroot()
    ns = {"o": root.tag[1:root.tag.index("}")]} if root.tag.startswith("{") else {}
    q = (lambda tag: f"o:{tag}") if ns else (lambda tag: tag)

    def text(el, tag: str) -> str:
        return (el.findtext(q(tag), default="", namespaces=ns) or "").strip()

    published = _iso_date((root.findtext(f"{q('publshInformation')}/{q('Publish_Date')}",
                                         default="", namespaces=ns) or "").strip())
    rows = []
    for entry in root.findall(q("sdnEntry"), ns):
        ids = [(text(i, "idType"), text(i, "idNumber"))
               for i in entry.findall(f"{q('idList')}/{q('id')}", ns)]
        ids = [(t[len(_ID_PREFIX):], n) for t, n in ids if t.startswith(_ID_PREFIX) and n]
        if not ids:
            continue
        uid = int(text(entry, "uid"))
        name = " ".join(p for p in (text(entry, "firstName"), text(entry, "lastName")) if p)
        programmes = [(p.text or "").strip()
                      for p in entry.findall(f"{q('programList')}/{q('program')}", ns)]
        override = o["entities"].get(uid)
        by_programme = sorted({o["programmes"][p] for p in programmes if p in o["programmes"]},
                              key=order.index)
        threat = override["threat"] if override else \
            by_programme[0] if by_programme else "sanctioned_other"
        remarks = text(entry, "remarks")
        evidence = (f"OFAC SDN list (published {published}), uid {uid}: {name}; "
                    f"programme {', '.join(programmes)}.")
        if remarks:
            evidence += f" {remarks}."
        if override:
            evidence += f" {override['basis']}."
        url = override["url"] if override else \
            cfg["sources"][OFAC_SOURCE]["entry_url"].format(uid=uid)
        for currency, address in ids:
            chain = o["currencies"].get(currency)
            if chain is None and currency in o["by_address"]:
                chain = _chain_by_form(address)
                if chain == "ethereum" and currency == "BNB":
                    chain = "bsc"
            if chain is None:
                continue
            rows.append({"address": address, "chain": chain, "threat": threat, "entity": name,
                         "source": OFAC_SOURCE, "source_url": url,
                         "evidence": f"{evidence} Listed as: {currency}."})
    return rows


# ------------------------------------------------------------------ Ransomwhere
def read_ransomwhere(json_path: Path | str, cfg: dict | None = None) -> list[dict]:
    """The Ransomwhere export: every address is a ransomware payment address, and
    `family` is the name the reporters gave the ransomware."""
    doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    site = (cfg or config())["sources"][RANSOMWHERE_SOURCE]["url"]
    rows = []
    for r in doc["result"]:
        if r.get("blockchain") != "bitcoin" or not r.get("address"):
            continue
        family = (r.get("family") or "").strip() or "Unlabeled"
        paid = len(r.get("transactions") or [])
        rows.append({
            "address": r["address"].strip(), "chain": "bitcoin", "threat": "ransomware",
            "entity": family, "source": RANSOMWHERE_SOURCE, "source_url": site,
            "evidence": f"Ransomwhere: ransomware payment address, family {family}; "
                        f"{paid} payment{'' if paid == 1 else 's'} on record there."})
    return rows


# ------------------------------------------------------------------ GraphSense TagPacks
def read_tagpacks(packs_dir: Path | str, cfg: dict | None = None) -> list[dict]:
    """Tags whose own `abuse` field maps to a threat, and `category: market` tags of the
    packs listed as darknet-market packs. A pack's header fields are each tag's default."""
    g = (cfg or config())["graphsense"]
    rows = []
    for path in sorted(Path(packs_dir).glob("*.yaml")):
        if path.stem in g["skipped"]:
            continue
        pack = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
        for tag in pack.get("tags") or []:
            def field(name: str) -> str:
                value = tag.get(name, pack.get(name))
                return "" if value is None else str(value).strip()
            chain = g["currencies"].get(field("currency"))
            if chain is None or not field("address"):
                continue
            abuse, category = field("abuse"), field("category")
            if abuse in g["abuse"]:
                threat, said = g["abuse"][abuse], f"abuse: {abuse}"
            elif category == "market" and path.stem in g["market_packs"]:
                threat, said = "darknet_market", "category: market"
            else:
                continue
            label = field("label") or field("title")
            rows.append({
                "address": field("address"), "chain": chain, "threat": threat, "entity": label,
                "source": TAGPACK_PREFIX + path.stem, "source_url": field("source"),
                "evidence": f"GraphSense TagPack \"{field('title')}\" ({field('creator')}): "
                            f"{said}; label \"{label}\"."})
    return rows


# ------------------------------------------------------------------ other governments (E7)
# Crypto addresses on the UK and EU lists sit in free text (UK `OtherInformation`, EU
# `remark`), and NBCTF's orders list them among an order's assets beside phone numbers.
# Every candidate is kept only when it is a valid address on a chain (`_chain_by_form`).
_ADDRESS = re.compile(r"(?<![0-9A-Za-z])(T[1-9A-HJ-NP-Za-km-z]{33}|0x[0-9a-fA-F]{40}|"
                      r"bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})(?![0-9A-Za-z])")


def _addresses(text: str) -> list[tuple[str, str]]:
    """(address, chain) for each valid address in a piece of free text, in order, once."""
    out, seen = [], set()
    for a in _ADDRESS.findall(text or ""):
        chain = _chain_by_form(a)
        if chain is not None and a not in seen:
            seen.add(a)
            out.append((a, chain))
    return out


def _regime_threat(regime: str, cfg: dict, key: str) -> str:
    words = cfg[key]["terrorism_regimes"]
    return "terrorism_financing" if any(w.lower() in regime.lower() for w in words) \
        else "sanctioned_other"


def read_uk(xml_path: Path | str, cfg: dict | None = None) -> list[dict]:
    """The UK Sanctions List (FCDO, XML): addresses an entry's `OtherInformation` names.
    The threat comes from the entry's regime (config `uk.terrorism_regimes`)."""
    cfg = cfg or config()
    root = ET.parse(str(xml_path)).getroot()
    generated = (root.findtext("DateGenerated") or "").strip()
    page = cfg["sources"][UK_SOURCE]["url"]
    rows = []
    for d in root.iter("Designation"):
        info = d.findtext("OtherInformation") or ""
        found = _addresses(info)
        if not found:
            continue
        uid = (d.findtext("UniqueID") or "").strip()
        regime = (d.findtext("RegimeName") or "").strip()
        names = [n for n in d.iter("Name")
                 if (n.findtext("NameType") or "").strip() == "Primary Name"] or list(d.iter("Name"))
        name = " ".join(t.strip() for t in (names[0].findtext(f"Name{i}") or "" for i in (1, 2, 3, 4, 5, 6))
                        if t.strip()) if names else uid
        evidence = (f"UK Sanctions List (generated {generated}), {uid}: {name}; regime "
                    f"{regime}. The entry names the address in its other information.")
        threat = _regime_threat(regime, cfg, "uk")
        rows += [{"address": a, "chain": c, "threat": threat, "entity": name, "source": UK_SOURCE,
                  "source_url": page, "evidence": evidence} for a, c in found]
    return rows


def read_eu(xml_path: Path | str, cfg: dict | None = None) -> list[dict]:
    """The EU Financial Sanctions File (XML): addresses an entry's remarks name. The threat
    comes from the regulation's programme (config `eu.terrorism_programmes`)."""
    cfg = cfg or config()
    root = ET.parse(str(xml_path)).getroot()
    ns = {"e": root.tag[1:root.tag.index("}")]} if root.tag.startswith("{") else {}
    q = (lambda t: f"e:{t}") if ns else (lambda t: t)
    generated = root.get("generationDate", "")[:10]
    terror = set(cfg["eu"]["terrorism_programmes"])
    rows = []
    for ent in root.findall(q("sanctionEntity"), ns):
        text = " ".join(r.text or "" for r in ent.iter(f"{{{ns['e']}}}remark" if ns else "remark"))
        found = _addresses(text)
        if not found:
            continue
        ref = ent.get("euReferenceNumber", "")
        reg = ent.find(q("regulation"), ns)
        programme = reg.get("programme", "") if reg is not None else ""
        url = (reg.findtext(q("publicationUrl"), default="", namespaces=ns) or "").strip() \
            if reg is not None else ""
        alias = ent.find(q("nameAlias"), ns)
        name = alias.get("wholeName", ref) if alias is not None else ref
        threat = "terrorism_financing" if programme in terror else "sanctioned_other"
        evidence = (f"EU financial sanctions list (generated {generated}), {ref}: {name}; "
                    f"programme {programme}. The entry's remarks name the address.")
        rows += [{"address": a, "chain": c, "threat": threat, "entity": name, "source": EU_SOURCE,
                  "source_url": url or cfg["sources"][EU_SOURCE]["url"], "evidence": evidence}
                 for a, c in found]
    return rows


def read_nbctf(csv_path: Path | str, cfg: dict | None = None, today: str | None = None) -> list[dict]:
    """Israel's NBCTF seizure (ASO) and forfeiture (FO) orders, as its own export gives
    them: the crypto addresses among each order's assets. A cancelled order is skipped; an
    order past its validity date is kept and says so. Personal names are not read."""
    cfg = cfg or config()
    page = cfg["sources"][NBCTF_SOURCE]["url"]
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as fh:
        text = fh.read().lstrip("\ufeff")
    rows = []
    for r in csv.DictReader(text.splitlines(keepends=True)):
        if (r.get("Is Canceled") or "").strip().lower() == "true":
            continue
        found = _addresses(r.get("Assets") or "")
        if not found:
            continue
        kind, number = r["Order Type"].strip(), r["Order Number"].strip()
        dated, valid = r["Order Date"].strip(), r["Validity Date"].strip()
        lapsed = f" (that date has passed)" if today and valid and valid < today else ""
        evidence = (f"Israel National Bureau for Counter Terror Financing (NBCTF): {kind} order "
                    f"{number}, dated {dated}, valid until {valid}{lapsed}. The order lists the "
                    "address among its assets.")
        rows += [{"address": a, "chain": c, "threat": "terrorism_financing",
                  "entity": f"NBCTF order {number}", "source": NBCTF_SOURCE, "source_url": page,
                  "evidence": evidence} for a, c in found]
    return rows


# ------------------------------------------------------------------ one row per address
def _normal(row: dict) -> dict | None:
    """The row with its address as the label store spells it, on the chain it is valid on;
    None when the address is valid nowhere."""
    from .normalize import address_chain, normalize_address
    address = row["address"].strip()
    chain = address_chain(address, row["chain"])
    if chain is None:
        return None
    return {**row, "address": normalize_address(address, chain), "chain": chain}


def merge(rows: list[dict], cfg: dict | None = None) -> list[dict]:
    """One row per (address, chain): the most specific threat, then the source listed
    first in the config, then the source name. Sorted, so the file is deterministic. An
    address that several sources (or entries) list keeps the others in `also` (JSON:
    source, entity, threat, url, evidence), so each listing can be shown."""
    cfg = cfg or config()
    t_rank = {t: i for i, t in enumerate(cfg["threats"])}
    s_rank = {s: i for i, s in enumerate(cfg["sources"])}
    best: dict[tuple[str, str], tuple] = {}
    seen: dict[tuple[str, str], list] = {}
    for raw in rows:
        r = _normal(raw)
        if r is None:
            continue
        rank = (t_rank[r["threat"]], s_rank[source_family(r["source"])], r["source"],
                r["entity"])
        key = (r["address"], r["chain"])
        seen.setdefault(key, []).append((rank, r))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, r)
    out = []
    for k in sorted(best, key=lambda k: (k[1], k[0])):
        top = best[k][1]
        others = {(r["source"], r["entity"]): {"source": r["source"], "entity": r["entity"],
                                               "threat": r["threat"], "url": r["source_url"] or None,
                                               "evidence": r["evidence"]}
                  for _, r in sorted(seen[k], key=lambda x: x[0])
                  if (r["source"], r["entity"]) != (top["source"], top["entity"])}
        out.append({**top, "also": json.dumps(list(others.values()), ensure_ascii=False,
                                              sort_keys=True) if others else ""})
    return out


def write_csv(rows: list[dict], out: Path | str) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path | str | None) -> list[dict]:
    """data/threat_tags.csv as written by `cli threats`. No file, no tags."""
    if path is None or not Path(path).is_file():
        return []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def counts(rows: list[dict]) -> dict:
    """Counts per threat, per (threat, chain) and per (threat, source family)."""
    out = {"total": len(rows), "by_threat": {}, "by_chain": {}, "by_source": {}}
    for r in rows:
        for key, sub in (("by_threat", None), ("by_chain", r["chain"]),
                         ("by_source", source_family(r["source"]))):
            if sub is None:
                out[key][r["threat"]] = out[key].get(r["threat"], 0) + 1
            else:
                d = out[key].setdefault(r["threat"], {})
                d[sub] = d.get(sub, 0) + 1
    return out
