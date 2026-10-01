"""`cli discover` and `cli labels --derived`, on the recorded real crawl: what
`make discover && make labels` does, with the network replaced by the recording."""
import csv
import json
from functools import partial
from pathlib import Path

import duckdb
import pytest

from discoverkit import ReplayTransport, load
from vaspfusion import cli
from vaspfusion.chains.cache import Fetcher
from vaspfusion.labels.load import _DDL, LABEL_COLUMNS
from vaspfusion.labels.lookup import LabelStore

LABEL_FIX = Path(__file__).parent / "fixtures" / "labels"
ARGS = ["--entities", "CoinDCX,KuCoin", "--seed-limit", "200", "--max-candidates", "5",
        "--workers", "3"]


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A label DB holding the rows the crawl touched, an empty crawl cache, no keys."""
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.setattr("vaspfusion.chains.UrllibTransport",
                        lambda: ReplayTransport("crawl_tron"))
    # keyless TronGrid is throttled to one request a second; the replay need not wait
    monkeypatch.setattr("vaspfusion.chains.Fetcher", partial(Fetcher, sleep=lambda s: None))
    db = tmp_path / "labels.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute(_DDL)
        con.executemany(f"INSERT INTO labels VALUES ({', '.join('?' * len(LABEL_COLUMNS))})",
                        [[r.get(c) for c in LABEL_COLUMNS]
                         for r in load("crawl_tron")["labels"].values()])
    return tmp_path, ["--labels-db", str(db), "--out", str(tmp_path / "derived"),
                      "--cache", str(tmp_path / "discover_cache.duckdb")]


def test_discover_writes_the_csv_the_report_and_a_table(machine, capsys):
    tmp, paths = machine
    cli.main(["discover", *ARGS, *paths])
    out = capsys.readouterr().out
    assert "CoinDCX" in out and "KuCoin" in out and "not calibrated" in out
    total = next(line for line in out.splitlines() if line.startswith("TOTAL"))
    # 37 labelled wallets (13 CoinDCX, 24 KuCoin), 4 took USDT, 10 candidates, 10 fired
    assert total.split()[:5] == ["TOTAL", "37", "4", "10", "10"]
    with (tmp / "derived" / "tron.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 10 and {r["status"] for r in rows} == {"derived"}
    report = json.loads((tmp / "derived" / "tron_report.json").read_text())
    assert report["totals"]["derived"] == 10 and report["config"]["seed_limit"] == 200


def test_a_second_run_replays_offline_to_the_same_bytes(machine, monkeypatch):
    tmp, paths = machine
    cli.main(["discover", *ARGS, *paths])
    first = (tmp / "derived" / "tron.csv").read_bytes()
    monkeypatch.setenv("OFFLINE", "1")
    cli.main(["discover", *ARGS, *paths, "--name", "again"])
    assert (tmp / "derived" / "again.csv").read_bytes() == first


def test_labels_merges_the_derived_rows(machine, capsys):
    tmp, paths = machine
    cli.main(["discover", *ARGS, *paths])
    capsys.readouterr()
    db = tmp / "merged.duckdb"
    research = tmp / "research"
    (research / "wallet-attribution").mkdir(parents=True)
    (research / "wallet-attribution" / "data").symlink_to(LABEL_FIX / "wa")
    (research / "indian_vasps_dune_spellbook.csv").symlink_to(LABEL_FIX / "dune.csv")
    cli.main(["labels", "--research", str(research), "--db", str(db),
              "--derived", str(tmp / "derived")])
    out = capsys.readouterr().out
    assert "derived deposit addresses merged" in out and ": 10 (of 10" in out
    with LabelStore(db) as store:
        hit = store.lookup("TTTZH6nWX8tk1b73xHfCJk3x9aBRgWbeEK", "tron")
    assert (hit.entity, hit.tier, hit.kind, hit.confidence) == \
        ("CoinDCX", "derived", "deposit", 0.8075)
