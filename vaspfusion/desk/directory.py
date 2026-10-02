"""The VASP directory (`data/vasp_directory.yaml`): who a request is addressed to.

Only facts with a source. The loader refuses a fact field that names no source, and a
source that an entry cites but the file does not define, so a blank field always
means "we could not cite it", never "we forgot".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "vasp_directory.yaml"
# fields that state something about the exchange, and so need a source
FACT_FIELDS = ("legal_name", "fiu_ind_registered", "jurisdiction", "le_request_channel",
               "notes")


class DirectoryError(ValueError):
    """The directory file breaks its own rule (a fact without a source)."""


def _key(name: str) -> str:
    return " ".join(name.lower().split())


class Directory:
    def __init__(self, vasps: list[dict], sources: dict[str, dict]):
        self.sources = sources
        self._vasps = {v["name"]: v for v in vasps}
        self._index: dict[str, str] = {}
        for v in vasps:
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
            for need in ("title", "url", "accessed"):
                if not src.get(need):
                    raise DirectoryError(f"source {sid} has no {need}")
        vasps = doc.get("vasps") or []
        for v in vasps:
            v.setdefault("cites", {})
            for field in FACT_FIELDS:
                if v.get(field) is not None and not v["cites"].get(field):
                    raise DirectoryError(f"{v['name']}: {field} has no source")
            for field, ids in v["cites"].items():
                if v.get(field) is None:
                    raise DirectoryError(f"{v['name']}: a source is cited for an empty {field}")
                for sid in ids:
                    if sid not in sources:
                        raise DirectoryError(f"{v['name']}: {field} cites unknown source {sid}")
            if v.get("fiu_ind_registered") is not None and not isinstance(
                    v.get("fiu_ind_as_of"), date):
                raise DirectoryError(f"{v['name']}: fiu_ind_registered needs fiu_ind_as_of, "
                                     "the date its source speaks for")
        return cls(vasps, sources)

    def names(self) -> list[str]:
        return sorted(self._vasps)

    def canonical(self, name: str) -> str:
        """The label store's spelling of an exchange, for a name or alias in any case."""
        return self._index.get(_key(name), name)

    def raw(self, name: str) -> dict:
        return self._vasps[self.canonical(name)]

    def get(self, name: str) -> dict:
        """The entry as the API returns it (`VaspDirectoryEntry`). An exchange the file
        does not list comes back with its name and nothing else."""
        v = self._vasps.get(self.canonical(name))
        if v is None:
            return {"name": name, "legal_name": None, "fiu_ind_registered": None,
                    "fiu_ind_as_of": None, "jurisdiction": None, "le_request_channel": None,
                    "notes": [], "sources": [], "source_urls": []}
        cited = [{"field": field, "title": self.sources[sid]["title"],
                  "publisher": self.sources[sid].get("publisher"),
                  "url": self.sources[sid]["url"],
                  "published": self.sources[sid].get("published"),
                  "accessed": self.sources[sid]["accessed"]}
                 for field in FACT_FIELDS for sid in v["cites"].get(field, [])]
        return {"name": v["name"], "legal_name": v.get("legal_name"),
                "fiu_ind_registered": v.get("fiu_ind_registered"),
                "fiu_ind_as_of": v.get("fiu_ind_as_of"),
                "jurisdiction": v.get("jurisdiction"),
                "le_request_channel": v.get("le_request_channel"),
                "notes": list(v.get("notes") or []), "sources": cited,
                "source_urls": sorted({s["url"] for s in cited})}
