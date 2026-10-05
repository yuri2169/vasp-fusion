"""Batch intake on the real pipeline: many wallets in, one result table out. A bad row
never stops the batch. Replays the recorded demo wallets; no network."""
import csv
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion import batch as B  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402

COINDCX = SPECS["tron-coindcx"]["address"]
BITGET = SPECS["eth-bitget"]["address"]
OFAC = SPECS["tron-ofac"]["address"]
ABSTAIN = SPECS["eth-abstain"]["address"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "DESK_DB", tmp_path / "desk.duckdb")
    monkeypatch.setattr(main, "make_fetcher", lambda: demo_fetcher(tmp_path / "cache.duckdb"))
    monkeypatch.setattr(main, "WORKERS", 0)
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    main._ROW_RESULTS.clear()
    return TestClient(main.app)


def rows(*wallets) -> list[dict]:
    return [w if isinstance(w, dict) else {"address": w} for w in wallets]


# ------------------------------------------------------------------ reading a CSV
def test_a_csv_with_a_header_is_read_by_column_name_in_any_order():
    text = "Case Reference,Chain,Wallet\nFIR 1/2026,tron,Tabc\n\n,,0xdef\n"
    assert B.parse_csv(text) == [
        {"row": 2, "address": "Tabc", "chain": "tron", "case_ref": "FIR 1/2026"},
        {"row": 4, "address": "0xdef", "chain": None, "case_ref": None}]


def test_a_csv_without_a_header_is_address_chain_reference():
    assert B.parse_csv("Tabc;tron;FIR 2\n0xdef\n") == [
        {"row": 1, "address": "Tabc", "chain": "tron", "case_ref": "FIR 2"},
        {"row": 2, "address": "0xdef", "chain": None, "case_ref": None}]
    assert B.parse_csv("﻿address\nTabc\n")[0] == {"row": 2, "address": "Tabc",
                                                       "chain": None, "case_ref": None}


def test_an_upload_too_large_or_empty_is_refused_whole():
    with pytest.raises(B.BatchError, match="no wallet"):
        B.check_size(B.parse_csv("address\n\n"))
    with pytest.raises(B.BatchError, match="at most 2000"):
        B.check_size([{"row": i} for i in range(B.MAX_ROWS + 1)])
    with pytest.raises(B.BatchError, match="larger than 2 MB"):
        B.parse_csv("x" * (B.MAX_CSV_BYTES + 1))


def test_the_result_csv_never_hands_a_spreadsheet_a_formula():
    row = B.result_row({"row": 1, "address": "Tabc", "chain": "tron",
                        "case_ref": "=HYPERLINK(1)", "error": "+bad"}, None, None)
    line = list(csv.reader(io.StringIO(B.to_csv([row]))))[1]
    assert line[3] == "'=HYPERLINK(1)" and line[-1] == "'+bad" and line[4] == "refused"


# ------------------------------------------------------------------ the routes
def test_a_batch_is_traced_and_its_table_comes_back(client):
    r = client.post("/api/cases/batch", json={"name": "Complaint 14", "rows": rows(
        {"address": COINDCX, "case_ref": "FIR 12/2026"}, BITGET, OFAC, ABSTAIN)})
    assert r.status_code == 202, r.text
    first = S.BatchDetail.model_validate(r.json())
    assert first.progress.total == first.progress.accepted == first.progress.queued == 4
    assert not first.progress.finished and first.workers == 0

    # the test client returns once the background queue has run: every wallet is traced
    batch = client.get(f"/api/batches/{first.id}").json()
    S.BatchDetail.model_validate(batch)
    p = batch["progress"]
    assert (p["done"], p["queued"], p["running"], p["failed"], p["finished"]) == (4, 0, 0, 0, True)
    assert p["by_outcome"] == {"ATTRIBUTED": 2, "INSUFFICIENT_EVIDENCE": 1,
                               "SANCTIONED_OR_MIXER_REACHED": 1}
    one, two, three, four = batch["rows"]
    assert (one["row"], one["address"], one["chain"], one["case_ref"]) == \
        (1, COINDCX, "tron", "FIR 12/2026")
    assert (one["outcome"], one["top_vasp"], one["hops"], one["proximity_rank"]) == \
        ("ATTRIBUTED", "CoinDCX", 1, 1)
    assert 0.6 <= one["confidence"] <= 1 and 0 < one["share_of_funds"] <= 1
    assert one["risk_class"] == "low" and one["case_url"] == f"/cases/{one['case_id']}"
    assert (two["chain"], two["top_vasp"]) == ("ethereum", "Bitget")
    assert (three["outcome"], three["top_vasp"], three["risk_class"]) == \
        ("SANCTIONED_OR_MIXER_REACHED", None, "severe")
    assert (four["outcome"], four["top_vasp"], four["hops"], four["confidence"]) == \
        ("INSUFFICIENT_EVIDENCE", None, None, None)
    assert not any(r["budget_ended"] for r in batch["rows"])

    # each row's case is an ordinary case
    case = client.get(f"/api/cases/{one['case_id']}").json()
    assert (case["status"], case["case_ref"], case["top_vasp"]) == ("done", "FIR 12/2026", "CoinDCX")

    listed = client.get("/api/batches").json()
    S.BatchList.model_validate(listed)
    assert listed["total"] == 1 and listed["items"][0]["name"] == "Complaint 14"
    assert "rows" not in listed["items"][0] and listed["items"][0]["progress"]["done"] == 4


def test_bad_rows_are_reported_with_reasons_and_never_stop_the_batch(client):
    text = ("address,chain,case_ref\n"
            f"{COINDCX},tron,FIR 1\n"
            "not-an-address,,FIR 2\n"
            f"{BITGET},dogecoin,FIR 3\n"
            ",tron,FIR 4\n"
            f"{COINDCX[:-1]}x,tron,FIR 5\n"
            f"{BITGET},,FIR 6\n")
    r = client.post("/api/cases/batch", json={"csv": text})
    assert r.status_code == 202, r.text
    batch = client.get(f"/api/batches/{r.json()['id']}").json()
    p = batch["progress"]
    assert (p["total"], p["accepted"], p["refused"], p["done"], p["finished"]) == (6, 2, 4, 2, True)
    by_row = {row["row"]: row for row in batch["rows"]}
    assert [n for n, row in by_row.items() if row["accepted"]] == [2, 7]
    assert "Could not tell which chain" in by_row[3]["error"]
    assert by_row[4]["error"].startswith("dogecoin is not a chain this tool traces.")
    assert by_row[5]["error"] == "This row has no address."
    assert "is not a valid tron address" in by_row[6]["error"]
    assert all(by_row[n]["case_id"] is None and by_row[n]["status"] is None for n in (3, 4, 5, 6))
    assert (by_row[2]["top_vasp"], by_row[7]["top_vasp"]) == ("CoinDCX", "Bitget")


def test_a_wallet_given_twice_is_traced_once_and_both_rows_point_at_its_case(client):
    r = client.post("/api/cases/batch", json={"rows": rows(BITGET, COINDCX, BITGET.upper()
                                                           .replace("0X", "0x"))})
    batch = client.get(f"/api/batches/{r.json()['id']}").json()
    a, _, again = batch["rows"]
    assert again["duplicate_of"] == 1 and again["case_id"] == a["case_id"]
    assert again["top_vasp"] == "Bitget" and again["accepted"]
    p = batch["progress"]
    assert (p["total"], p["accepted"], p["duplicates"], p["done"]) == (3, 2, 1, 2)
    assert client.get("/api/cases").json()["total"] == 2 + len(main._demo_cases())


def test_a_wallet_that_already_has_a_case_is_linked_not_traced_again(client, monkeypatch):
    cid = client.post("/api/cases", json={"address": COINDCX}).json()["id"]
    traced = []
    real = main._run_case
    monkeypatch.setattr(main, "_run_case", lambda *a, **k: (traced.append(a[0]), real(*a, **k))[1])
    r = client.post("/api/cases/batch", json={"rows": rows(COINDCX, BITGET)})
    batch = client.get(f"/api/batches/{r.json()['id']}").json()
    assert batch["rows"][0]["case_id"] == cid and batch["rows"][0]["top_vasp"] == "CoinDCX"
    assert traced == [batch["rows"][1]["case_id"]]          # only the new wallet
    assert batch["progress"]["done"] == 2


def test_a_failed_trace_is_one_failed_row_and_the_rest_finish(client, monkeypatch):
    real = main._run_case

    def run(case_id, *a, **k):
        if main._cases().get(case_id)["address"] == BITGET:
            main._cases().set_status(case_id, "failed", error="ProviderError: upstream is down")
            return "ProviderError: upstream is down"
        return real(case_id, *a, **k)

    monkeypatch.setattr(main, "_run_case", run)
    r = client.post("/api/cases/batch", json={"rows": rows(COINDCX, BITGET, OFAC)})
    batch = client.get(f"/api/batches/{r.json()['id']}").json()
    p = batch["progress"]
    assert (p["done"], p["failed"], p["finished"]) == (2, 1, True)
    bad = batch["rows"][1]
    assert (bad["status"], bad["error"]) == ("failed", "ProviderError: upstream is down")
    assert bad["accepted"] and bad["outcome"] is None


def test_the_result_table_downloads_as_csv(client):
    r = client.post("/api/cases/batch", json={"rows": rows(
        {"address": COINDCX, "case_ref": "FIR 12/2026"}, "nonsense", OFAC)})
    bid = r.json()["id"]
    out = client.get(f"/api/batches/{bid}/results.csv")
    assert out.status_code == 200 and out.headers["content-type"].startswith("text/csv")
    assert f'filename="batch-{bid}.csv"' in out.headers["content-disposition"]
    table = list(csv.DictReader(io.StringIO(out.text)))
    assert list(table[0]) == list(B.RESULT_COLUMNS) and len(table) == 3
    one, bad, three = table
    assert (one["wallet"], one["chain"], one["case_reference"], one["status"]) == \
        (COINDCX, "tron", "FIR 12/2026", "done")
    assert (one["outcome"], one["named_exchange"], one["hops"], one["risk_class"]) == \
        ("ATTRIBUTED", "CoinDCX", "1", "low")
    assert 0.6 <= float(one["confidence"]) <= 1 and one["budget_ended_trace"] == "no"
    assert one["case"].endswith(f"/cases/{r.json()['rows'][0]['case_id']}")
    assert one["case"].startswith("http")
    assert (bad["status"], bad["case"], bad["outcome"]) == ("refused", "", "")
    assert "Could not tell which chain" in bad["error"]
    assert (three["outcome"], three["named_exchange"], three["risk_class"]) == \
        ("SANCTIONED_OR_MIXER_REACHED", "", "severe")


def test_the_batch_budget_reaches_every_case(client):
    r = client.post("/api/cases/batch", json={"rows": rows(ABSTAIN), "max_wallets": 1})
    batch = client.get(f"/api/batches/{r.json()['id']}").json()
    assert batch["max_wallets"] == 1 and batch["rows"][0]["budget_ended"] is True
    case = client.get(batch["rows"][0]["case_url"].replace("/cases/", "/api/cases/")).json()
    assert case["provenance"]["input"]["max_wallets"] == 1
    assert case["provenance"]["budget"]["ended_by"] == "wallets"


def test_what_a_batch_must_be(client):
    for bad in ({}, {"rows": rows(COINDCX), "csv": COINDCX}, {"rows": []}, {"csv": "\n\n"},
                {"rows": rows(COINDCX), "max_wallets": 5000}):
        assert client.post("/api/cases/batch", json=bad).status_code == 422, bad
    assert client.get("/api/batches/b-nope").status_code == 404
    assert client.get("/api/batches/b-nope/results.csv").status_code == 404
    assert client.get("/api/batches/..%2Fx").status_code == 404
    assert client.get("/api/batches").json() == {"total": 0, "items": []}


def test_a_complaint_with_many_wallets_goes_through_the_same_queue(client, monkeypatch):
    monkeypatch.setenv("SAHYOG_API_KEY", "k" * 40)
    claimed = []
    real = main.work_one
    monkeypatch.setattr(main, "work_one", lambda *a, **k: (claimed.append(a), real(*a, **k))[1])
    r = client.post("/api/sahyog/complaints", headers={"X-SAHYOG-Key": "k" * 40}, json={
        "complaint_ref": "NCRP-2026-0009", "agency": "Test Cyber Cell", "officer": "Insp. T",
        "wallets": [{"address": a} for a in (COINDCX, BITGET, OFAC)]})
    assert r.status_code == 202 and len(claimed) == 3
    jobs = main._queue().finished()
    assert [j["state"] for j in jobs] == ["done"] * 3
    assert {j["case_id"] for j in jobs} == {w["case_id"] for w in r.json()["wallets"]}
    assert all(j["stats"]["transfers_read"] > 0 and j["stats"]["seconds"] > 0 for j in jobs)


# ------------------------------------------------------------------ measured figures
def test_scale_figures_come_from_the_bench_file_or_say_not_measured(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "SCALE_METRICS", tmp_path / "none.json")
    out = client.get("/api/scale").json()
    S.ScaleMetrics.model_validate(out)
    assert out["status"] == "not_measured" and out["runs"] == [] and "bench-scale" in out["notes"][0]
    (tmp_path / "m.json").write_text(
        '{"measured_on": "2026-10-05", "machine": "test", "wallets": 12, "runs": [{"workers": 1, '
        '"cases": 12, "seconds": 6.0, "cases_per_minute": 120.0, "median_seconds_per_case": 0.3, '
        '"p95_seconds_per_case": 0.6, "transfers_per_second": 48.0, "peak_memory_mb": 400.0, '
        '"speedup": 1.0}]}')
    monkeypatch.setattr(main, "SCALE_METRICS", tmp_path / "m.json")
    out = client.get("/api/scale").json()
    S.ScaleMetrics.model_validate(out)
    assert out["status"] == "measured" and out["runs"][0]["cases_per_minute"] == 120.0


def test_the_committed_scale_figures_are_valid():
    """The file the Model page and the README read, as `make bench-scale` last wrote it."""
    import json
    path = main.ROOT / "artifacts" / "scale" / "metrics.json"
    doc = json.loads(path.read_text())
    S.ScaleMetrics.model_validate({"status": "measured", **doc})
    assert [r["workers"] for r in doc["runs"]] == [1, 2, 4, 8]
    assert doc["runs"][0]["speedup"] == 1.0 and doc["machine"] and doc["measured_on"]
