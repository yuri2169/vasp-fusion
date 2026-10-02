"""`verify`: a stored case is traced again from the cached chain responses only, and
its findings fingerprint must come out the same. Recorded demo wallets; no network."""
import copy
import json
from datetime import datetime, timezone

import pytest

from demokit import SPECS, DemoLabels, DemoTransport, run_demo
from vaspfusion import chains
from vaspfusion import provenance as P
from vaspfusion.api import schemas as S
from vaspfusion.cases import verify_stored
from vaspfusion.chains.cache import ChainCache, Fetcher

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


def offline(cache_path) -> Fetcher:
    return Fetcher(ChainCache(cache_path), None, offline=True)


def verify(case, cache_path, **kw):
    return verify_stored(case, offline(cache_path), DemoLabels(), now=NOW, key="test-key", **kw)


@pytest.fixture(scope="module")
def stored(tmp_path_factory):
    cache = tmp_path_factory.mktemp("v") / "cache.duckdb"
    return run_demo("tron-coindcx", cache), cache


@pytest.mark.parametrize("case_id", list(SPECS))
def test_every_demo_case_verifies_from_the_cache_alone(case_id, tmp_path):
    cache = tmp_path / "cache.duckdb"
    case = run_demo(case_id, cache)
    result = verify(case, cache)
    S.VerifyResult.model_validate(result)
    assert result["matches"] is True, result["summary"]
    core = {c["name"]: c["result"] for c in result["checks"]}
    assert (core["stored_case"], core["responses"], core["findings"]) == ("same",) * 3
    assert result["summary"].startswith("Verified")
    assert result["case_id"] == case_id and result["checked_at"] == "2026-10-02T09:00:00Z"


def test_a_stored_case_that_was_edited_fails_on_itself(stored):
    case, cache = stored
    edited = copy.deepcopy(case)
    edited["candidates"][0]["confidence"] = 0.99
    result = verify(edited, cache)
    core = {c["name"]: c for c in result["checks"]}
    assert result["matches"] is False
    assert core["stored_case"]["result"] == "different"
    assert "changed after it was computed" in result["summary"]
    assert core["findings"]["result"] == "same"        # the replay still gives the receipt's


def test_an_edited_receipt_is_caught_by_the_replay(stored):
    case, cache = stored
    edited = copy.deepcopy(case)
    edited["candidates"][0]["confidence"] = edited["confidence"] = 0.99
    edited["provenance"]["findings_sha256"] = P.findings_sha256(edited)   # receipt forged too
    edited["provenance"]["content_sha256"] = P.content_sha256(edited)
    result = verify(edited, cache)
    core = {c["name"]: c for c in result["checks"]}
    assert result["matches"] is False
    assert core["stored_case"]["result"] == "same" and core["findings"]["result"] == "different"
    assert "confidence 0.99 -> 0.8491" in core["findings"]["detail"]


class Reformatting(DemoTransport):
    """The same recorded answers, with one page's bytes changed (its JSON is the same)."""

    def __init__(self, case_id, nth=0):
        super().__init__(case_id)
        self.nth, self.changed = nth, None

    def get(self, url, params, headers):
        status, body = super().get(url, params, headers)
        if self.calls - 1 == self.nth:
            self.changed = chains.cache.request_key(url, params)
            body = body + b" "
        return status, body


def test_a_changed_cached_page_is_named(stored, tmp_path):
    case, _ = stored
    spec = SPECS["tron-coindcx"]
    transport = Reformatting("tron-coindcx")
    fetcher = Fetcher(ChainCache(tmp_path / "other.duckdb"), transport, offline=False,
                      sleep=lambda s: None)
    from vaspfusion.cases import replay_case
    replay_case(case["provenance"]["input"], fetcher, DemoLabels(), key="test-key")
    result = verify(case, tmp_path / "other.duckdb")
    core = {c["name"]: c for c in result["checks"]}
    assert result["matches"] is False
    assert core["responses"]["result"] == "different"
    assert "1 changed" in core["responses"]["detail"] and transport.changed in core["responses"]["detail"]
    assert core["findings"]["result"] == "same"        # same JSON, so the same findings
    assert spec["address"] in json.dumps(case["provenance"]["input"])


def test_a_page_missing_from_the_cache_means_not_verified(stored, tmp_path):
    case, _ = stored
    result = verify(case, tmp_path / "empty.duckdb")
    assert result["matches"] is False
    replay = next(c for c in result["checks"] if c["name"] == "replay")
    assert replay["result"] == "not_checked" and "CacheMiss" in replay["detail"]
    assert result["summary"].startswith("Not verified")


def test_a_changed_label_database_is_reported_beside_the_result(stored):
    case, cache = stored
    was = {**case, "provenance": {**case["provenance"], "label_db_sha256": "a" * 64}}
    result = verify(was, cache, label_db_sha256="b" * 64)
    labels = next(c for c in result["checks"] if c["name"] == "labels")
    assert labels["result"] == "different" and (labels["stored"], labels["now"]) == ("a" * 64, "b" * 64)
    assert result["matches"] is True               # the findings are what is verified


def test_a_case_without_a_receipt_says_so(stored):
    case, cache = stored
    old = {**case, "provenance": {"seed": 26182, "code_version": "b8-desk-1"}}
    result = verify(old, cache)
    S.VerifyResult.model_validate(result)
    assert result["matches"] is False and result["checks"] == []
    assert "no receipt" in result["summary"]


def test_verify_refuses_a_fetcher_that_could_go_live(stored):
    case, cache = stored
    live = Fetcher(ChainCache(cache), DemoTransport("tron-coindcx"), offline=False)
    with pytest.raises(ValueError, match="cache only"):
        verify_stored(case, live, DemoLabels())


def test_the_cache_only_fetcher_is_offline_whatever_the_environment_says(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.setenv("VASPFUSION_CHAIN_CACHE", str(tmp_path / "c.duckdb"))
    f = chains.cache_only_fetcher()
    assert f.offline is True and f.transport is None


# ------------------------------------------------------------------ from a receipt alone
def test_a_receipt_alone_can_be_verified(stored):
    case, cache = stored
    from vaspfusion.cases import verify_receipt
    receipt = json.loads(json.dumps(P.receipt(case)))          # as exported to a file
    result = verify_receipt(receipt, offline(cache), DemoLabels(), now=NOW, key="test-key")
    S.VerifyResult.model_validate(result)
    assert result["matches"] is True
    forged = {**receipt, "findings_sha256": "0" * 64}
    result = verify_receipt(forged, offline(cache), DemoLabels(), now=NOW, key="test-key")
    assert result["matches"] is False
    assert next(c for c in result["checks"] if c["name"] == "stored_case")["result"] == "different"
