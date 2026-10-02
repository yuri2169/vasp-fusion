"""The VASP directory (`data/vasp_directory.yaml`): who a request is addressed to.

Only facts with a source. The loader refuses a fact that names no source, a source
the file does not define, a note without its own source, and a registration whose
date is not the date its source was published. So a blank field always means "we
could not cite it", never "we forgot".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "vasp_directory.yaml"
# fields that state something about the exchange, and so need a source under `cites`
FACT_FIELDS = ("legal_name", "fiu_ind_registered", "jurisdiction", "le_request_channel")
TEXT_FIELDS = ("legal_name", "jurisdiction", "le_request_channel")
# official = a government or regulator document; exchange = the exchange's own page;
# news = a press report
SOURCE_KINDS = ("official", "exchange", "news")


class DirectoryError(ValueError):
    """The directory file breaks its own rule (a fact without a source)."""


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def _check(v: dict, sources: dict) -> None:
    name = v.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DirectoryError("an entry has no name")
    cites = v["cites"] = v.get("cites") or {}

    def known(field: str, ids) -> None:
        if not isinstance(ids, list) or not ids:
            raise DirectoryError(f"{name}: {field} has no source")
        for sid in ids:
            if sid not in sources:
                raise DirectoryError(f"{name}: {field} cites unknown source {sid}")

    for field in TEXT_FIELDS:
        if v.get(field) is not None and not isinstance(v[field], str):
            raise DirectoryError(f"{name}: {field} must be text")
    for field in FACT_FIELDS:
        if v.get(field) is not None:
            known(field, cites.get(field))
    for field in cites:
        if field not in FACT_FIELDS:
            raise DirectoryError(f"{name}: cites names {field}, which is not a fact field")
        if v.get(field) is None:
            raise DirectoryError(f"{name}: a source is cited for an empty {field}")
    for note in v.get("notes") or []:
        if not isinstance(note, dict) or not isinstance(note.get("text"), str):
            raise DirectoryError(f"{name}: a note must be {{text, cites}}")
        known("a note", note.get("cites"))

    reg, as_of = v.get("fiu_ind_registered"), v.get("fiu_ind_as_of")
    if reg is None:
        if as_of is not None:
            raise DirectoryError(f"{name}: fiu_ind_as_of without fiu_ind_registered")
        return
    if not isinstance(reg, bool):
        raise DirectoryError(f"{name}: fiu_ind_registered must be true or false")
    if not isinstance(as_of, date):
        raise DirectoryError(f"{name}: fiu_ind_registered needs fiu_ind_as_of, the date "
                             "its source speaks for")
    published = [sources[sid].get("published") for sid in cites["fiu_ind_registered"]]
    if as_of not in published:
        raise DirectoryError(f"{name}: fiu_ind_as_of {as_of} is not the date its source was "
                             f"published ({', '.join(str(p) for p in published)})")


class Directory:
    def __init__(self, vasps: list[dict], sources: dict[str, dict]):
        self.sources = sources
        self._vasps: dict[str, dict] = {}
        self._index: dict[str, str] = {}
        for v in vasps:
            if v["name"] in self._vasps:
                raise DirectoryError(f"{v['name']} is listed twice")
            self._vasps[v["name"]] = v
            for alias in (v["name"], *v.get("aliases", [])):
                if self._index.setdefault(_key(alias), v["name"]) != v["name"]:
                    raise DirectoryError(f"{alias!r} names two exchanges")

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PATH) -> "Directory":
        path = Path(path)
        if not path.exists():
            return cls([], {})
        doc = yaml.safe_load(path.read_text()) or {}
        sources = doc.get("sources") or {}
        for sid, src in sources.items():
            for need in ("title", "url", "accessed", "kind"):
                if not src.get(need):
                    raise DirectoryError(f"source {sid} has no {need}")
            if src["kind"] not in SOURCE_KINDS:
                raise DirectoryError(f"source {sid}: kind must be one of {SOURCE_KINDS}")
        vasps = doc.get("vasps") or []
        for v in vasps:
            _check(v, sources)
        return cls(vasps, sources)

    def names(self) -> list[str]:
        return sorted(self._vasps)

    def canonical(self, name: str) -> str:
        """The directory's spelling of an exchange, for a name or alias in any case."""
        return self._index.get(_key(name), name)

    def raw(self, name: str) -> dict:
        return self._vasps[self.canonical(name)]

    def _source(self, field: str, sid: str) -> dict:
        s = self.sources[sid]
        return {"field": field, "title": s["title"], "publisher": s.get("publisher"),
                "kind": s["kind"], "url": s["url"], "published": s.get("published"),
                "accessed": s["accessed"]}

    def get(self, name: str) -> dict:
        """The entry as the API returns it (`VaspDirectoryEntry`). An exchange the file
        does not list comes back with its name and nothing else."""
        v = self._vasps.get(self.canonical(name))
        if v is None:
            return {"name": name, "legal_name": None, "fiu_ind_registered": None,
                    "fiu_ind_as_of": None, "jurisdiction": None, "le_request_channel": None,
                    "notes": [], "sources": [], "source_urls": []}
        notes = v.get("notes") or []
        cited = [self._source(field, sid)
                 for field in FACT_FIELDS for sid in v["cites"].get(field, [])]
        cited += [self._source("notes", sid) for n in notes for sid in n["cites"]]
        seen, sources = set(), []
        for s in cited:                      # two notes may share a source
            if (s["field"], s["url"]) not in seen:
                seen.add((s["field"], s["url"]))
                sources.append(s)
        return {"name": v["name"], "legal_name": v.get("legal_name"),
                "fiu_ind_registered": v.get("fiu_ind_registered"),
                "fiu_ind_as_of": v.get("fiu_ind_as_of"),
                "jurisdiction": v.get("jurisdiction"),
                "le_request_channel": v.get("le_request_channel"),
                "notes": [n["text"] for n in notes], "sources": sources,
                "source_urls": sorted({s["url"] for s in sources})}
