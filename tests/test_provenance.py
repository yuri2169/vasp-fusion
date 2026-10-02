"""The provenance receipt: what a case was computed from, as digests anyone can
recompute. Runs on the recorded demo wallets; no network."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from demokit import SPECS, run_demo
from vaspfusion import provenance as P
from vaspfusion.api import schemas as S

GOLDEN = json.loads((Path(__file__).parent / "golden" / "fingerprints.json").read_text())
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def hero(tmp_path_factory):
    return run_demo("tron-coindcx", tmp_path_factory.mktemp("p") / "cache.duckdb", now=NOW)


# ------------------------------------------------------------------ canonical form
def test_canonical_json_sorts_keys_and_rounds_floats():
    assert P.canonical({"b": 1, "a": [0.1 + 0.2, 1.0, -0.0]}) == '{"a":[0.3,1.0,0.0],"b":1}'
    assert P.canonical({"t": NOW}) == '{"t":"2026-10-02T09:00:00Z"}'
    assert P.canonical({"x": (1, 2)}) == P.canonical({"x": [1, 2]})


def test_a_difference_under_the_seventh_decimal_is_not_a_difference():
    assert P.sha256_of({"p": 0.85000001}) == P.sha256_of({"p": 0.85000002})
    assert P.sha256_of({"p": 0.85}) != P.sha256_of({"p": 0.86})


# ------------------------------------------------------------------ the receipt on a case
def test_a_case_carries_its_receipt(hero):
    prov = hero["provenance"]
    S.Provenance.model_validate(prov)
    assert prov["input"] == {"address": SPECS["tron-coindcx"]["address"], "chain": "tron",
                             "max_hops": 3, "since": None}
    assert prov["input_sha256"] == P.sha256_of(prov["input"])
    assert prov["pages"] == len(prov["responses"]) > 0
    assert all(set(r) == {"query", "sha256"} and len(r["sha256"]) == 64
               for r in prov["responses"])
    assert prov["responses_sha256"] == P.responses_sha256(prov["responses"])
    assert prov["findings_sha256"] == P.findings_sha256(hero)
    assert prov["model_version"] == "model_v1/tron" and len(prov["model_sha256"]) == 64
    assert prov["seed"] == 26182 and prov["code_version"].startswith("b9-")


def test_no_api_key_is_in_a_receipt(hero):
    text = json.dumps(hero["provenance"]).lower()
    assert "apikey" not in text and "api_key" not in text and "test-key" not in text


def test_an_ethereum_case_names_no_model(tmp_path):
    case = run_demo("eth-bitget", tmp_path / "c.duckdb", now=NOW)
    assert case["provenance"]["model_version"] is None
    assert case["provenance"]["model_sha256"] is None


@pytest.mark.parametrize("case_id", list(SPECS))
def test_each_demo_wallet_reproduces_its_golden_fingerprint(case_id, tmp_path):
    cache = tmp_path / "cache.duckdb"
    live = run_demo(case_id, cache, now=NOW)
    replay = run_demo(case_id, cache, offline=True)
    assert live["provenance"]["findings_sha256"] == GOLDEN[case_id]["findings_sha256"]
    for key in ("findings_sha256", "responses_sha256", "input_sha256", "pages"):
        assert replay["provenance"][key] == live["provenance"][key], key
    assert live["provenance"]["responses_sha256"] == GOLDEN[case_id]["responses_sha256"]


# ------------------------------------------------------------------ what the fingerprint covers
def test_the_fingerprint_follows_the_findings_not_the_wording(hero):
    same = copy.deepcopy(hero)
    same["narrative"] = "Reworded."
    same["created_at"] = "2030-01-01T00:00:00Z"
    same["candidates"][0]["evidence"][0]["text"] = "Reworded."
    same["provenance"]["offline_replay"] = True
    assert P.findings_sha256(same) == P.findings_sha256(hero)


@pytest.mark.parametrize("change", [
    lambda c: c["candidates"][0].__setitem__("confidence", 0.99),
    lambda c: c.__setitem__("outcome", "INSUFFICIENT_EVIDENCE"),
    lambda c: c["graph"]["edges"][0].__setitem__("tx_hash", "00" * 32),
    lambda c: c["graph"]["edges"][0].__setitem__("traced_amount", 1.0),
    lambda c: c["hop_rail"][0].__setitem__("to_address", "TXXvb9hWwZr6CaYGPG3c9DpoUmGmBCz4pW"),
    lambda c: c["candidates"][0]["request_wallets"][0].__setitem__("amount", 1.0),
    lambda c: c["candidates"][0]["evidence"][0]["tx_hashes"].append("ab" * 32),
    lambda c: c["typology_flags"].pop(),
])
def test_the_fingerprint_changes_with_any_finding(hero, change):
    other = copy.deepcopy(hero)
    change(other)
    assert P.findings_sha256(other) != P.findings_sha256(hero)


def test_the_responses_digest_ignores_order_and_repeats():
    a = {"query": "https://x/1?a=1", "sha256": "1" * 64, "source": "live"}
    b = {"query": "https://x/2", "sha256": "2" * 64, "source": "cache"}
    one, two = P.responses([a, b, a]), P.responses([b, a])
    assert one == two == [{"query": a["query"], "sha256": a["sha256"]},
                          {"query": b["query"], "sha256": b["sha256"]}]
    changed = P.responses([a, {**b, "sha256": "3" * 64}])
    assert P.responses_sha256(changed) != P.responses_sha256(one)


def test_the_input_digest_changes_with_the_hop_limit():
    a = P.case_input("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", "tron", 3, None)
    b = P.case_input("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", "tron", 4, None)
    c = P.case_input("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", "tron", 3,
                     datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert len({P.sha256_of(a), P.sha256_of(b), P.sha256_of(c)}) == 3
    assert c["since"] == "2026-09-01T00:00:00Z"


# ------------------------------------------------------------------ the code that ran
def test_the_commit_comes_from_the_environment_first(monkeypatch):
    P.git_state.cache_clear()
    monkeypatch.setenv("VASPFUSION_GIT_COMMIT", "a" * 40)
    assert P.git_state() == ("a" * 40, None)       # whether the tree was clean was not said
    P.git_state.cache_clear()


def test_the_commit_is_read_from_git_when_this_is_a_checkout(monkeypatch):
    P.git_state.cache_clear()
    monkeypatch.delenv("VASPFUSION_GIT_COMMIT", raising=False)
    commit, dirty = P.git_state()
    assert commit is None or (len(commit) == 40 and isinstance(dirty, bool))
    P.git_state.cache_clear()


def test_outside_a_checkout_the_commit_is_unknown(tmp_path, monkeypatch):
    P.git_state.cache_clear()
    monkeypatch.delenv("VASPFUSION_GIT_COMMIT", raising=False)
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert P.git_state() == (None, None)
    P.git_state.cache_clear()


# ------------------------------------------------------------------ the receipt as a document
def test_the_receipt_document_is_the_case_and_its_digests(hero):
    r = P.receipt(hero)
    S.Receipt.model_validate(r)
    assert r["case_id"] == "tron-coindcx" and r["outcome"] == "ATTRIBUTED"
    assert r["top_vasp"] == "CoinDCX" and r["created_at"] == hero["created_at"]
    assert r["findings_sha256"] == hero["provenance"]["findings_sha256"]
    assert r["responses"] == hero["provenance"]["responses"]
    assert r["receipt_sha256"] == P.sha256_of({k: v for k, v in r.items()
                                               if k != "receipt_sha256"})


def test_a_case_stored_before_b9_has_no_receipt():
    old = {"id": "c-1", "status": "done", "provenance": {"seed": 26182, "code_version": "b8-desk-1"}}
    assert P.receipt(old) is None
