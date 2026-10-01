"""The derived-label artefact: data/derived/<chain>.csv and <chain>_report.json."""
import json

from test_discover_crawl import LABELS, Chain, Labels, deposit_and_sweep, ev
from tracekit import CHAIN, T0, tx
from vaspfusion.discover.crawl import CrawlConfig, discover
from vaspfusion.discover.store import read_findings, write_result


def crawl():
    rows = (deposit_and_sweep(1, "D1", "HOT", 0) + deposit_and_sweep(3, "D2", "HOT", 10)
            + deposit_and_sweep(5, "D3", "HOT", 20) + [tx(9, "U9", "W", 50, 30),
                                                         tx(10, "W", "HOT", 1, 31)])
    chain = Chain(rows, {"D1": [ev("GASA", 4)], "D2": [ev("BHOT", 14)]})
    return discover(CHAIN, chain, chain, Labels(LABELS), CrawlConfig(window_start=T0))


def test_findings_survive_a_round_trip_through_the_csv(tmp_path):
    result = crawl()
    csv_path, _ = write_result(tmp_path, result)
    assert csv_path == tmp_path / f"{CHAIN}.csv"
    assert read_findings(csv_path) == result.findings
    statuses = {f.address: f.status for f in read_findings(csv_path)}
    assert statuses == {"D1": "derived", "D2": "conflict", "D3": "derived"}


def test_the_report_holds_config_stats_and_stations(tmp_path):
    result = crawl()
    _, report_path = write_result(tmp_path, result)
    report = json.loads(report_path.read_text())
    assert report["chain"] == CHAIN and report["totals"]["derived"] == 2
    assert report["config"]["window_start"] == "2026-01-01T00:00:00Z"
    assert report["config"]["rules"]["min_share"] == 0.9
    assert report["stats"]["ExA"]["rejected"] == {"forwards under 90% of what it receives": 1}
    assert report["stations"] == []
    assert "not calibrated" in report["note"]


def test_writing_twice_gives_the_same_bytes(tmp_path):
    a = [p.read_bytes() for p in write_result(tmp_path / "a", crawl())]
    b = [p.read_bytes() for p in write_result(tmp_path / "b", crawl())]
    assert a == b
