"""Regression tests for the B9 code review: each one is a way a false "verified", a
false sentence or an unlogged request got through before it was fixed."""
import copy
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from demokit import DemoLabels, run_demo
from refresh_golden import golden_case
from vaspfusion import provenance as P
from vaspfusion.auth import officers as O
from vaspfusion.auth import tokens as T
from vaspfusion.cases import verify_receipt, verify_stored
from vaspfusion.chains.cache import ChainCache, Fetcher
from vaspfusion.explain import case_file as CF
from vaspfusion.explain.case_pdf import case_pdf
from vaspfusion.store.audit import AuditLog

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def stored(tmp_path_factory):
    cache = tmp_path_factory.mktemp("rv") / "cache.duckdb"
    return run_demo("tron-coindcx", cache), cache


@pytest.fixture(scope="module")
def hero(tmp_path_factory):
    return golden_case("tron-coindcx", tmp_path_factory.mktemp("rh") / "c.duckdb")


def offline(cache) -> Fetcher:
    return Fetcher(ChainCache(cache), None, offline=True)


def check(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


# ================================================================== C1: a forged receipt
def reissue(doc: dict) -> dict:
    """What a forger does: change fields, then recompute the receipt's own digest."""
    doc = {k: v for k, v in doc.items() if k != "receipt_sha256"}
    return {**doc, "receipt_sha256": P.sha256_of(doc)}


@pytest.mark.parametrize("forged", [
    {"top_vasp": "Binance"}, {"confidence": 0.99}, {"outcome": "INSUFFICIENT_EVIDENCE"},
    {"top_vasp": "Binance", "confidence": 0.99}])
def test_a_receipt_with_a_forged_headline_does_not_verify(stored, forged):
    case, cache = stored
    doc = reissue({**P.receipt(case), **forged})
    result = verify_receipt(doc, offline(cache), DemoLabels(), now=NOW, key="test-key")
    assert result["matches"] is False
    assert check(result, "findings")["result"] == "different"
    assert "headline stated is not what the trace gives" in result["summary"]


def test_a_receipt_with_its_pages_removed_does_not_verify(stored):
    case, cache = stored
    doc = reissue({**P.receipt(case), "pages": 0, "responses": []})
    result = verify_receipt(doc, offline(cache), DemoLabels(), now=NOW, key="test-key")
    assert result["matches"] is False and check(result, "stored_case")["result"] == "different"
    assert "The same 0 chain responses" not in json.dumps(result)   # never a count it did not read
    assert "page count" in check(result, "stored_case")["detail"] \
        or "list of chain responses" in check(result, "stored_case")["detail"]
    emptied = reissue({**P.receipt(case), "pages": 0, "responses": [],
                       "responses_sha256": P.responses_sha256([])})
    result = verify_receipt(emptied, offline(cache), DemoLabels(), now=NOW, key="test-key")
    assert result["matches"] is False and check(result, "responses")["result"] == "different"


@pytest.mark.parametrize("missing", ["pages", "responses", "responses_sha256", "input_sha256",
                                     "findings_sha256", "input"])
def test_a_receipt_with_a_part_missing_is_no_receipt_not_a_crash(stored, missing):
    case, cache = stored
    doc = {k: v for k, v in P.receipt(case).items() if k != missing}
    result = verify_receipt(doc, offline(cache), DemoLabels(), now=NOW, key="test-key")
    assert result["matches"] is False and "no receipt" in result["summary"]


def test_an_honest_receipt_still_verifies(stored):
    case, cache = stored
    result = verify_receipt(json.loads(json.dumps(P.receipt(case))), offline(cache),
                            DemoLabels(), now=NOW, key="test-key")
    assert result["matches"] is True


# ================================================================== C3: what the digests cover
def edit_times(c):
    c["graph"]["edges"][0]["block_time"] = "2031-01-01T00:00:00Z"


def edit_rail_time(c):
    c["hop_rail"][0]["block_time"] = "2031-01-01T00:00:00Z"


def edit_reached(c):
    c["candidates"][0]["request_wallets"][0]["reached_at"] = "2031-01-01T00:00:00Z"


def edit_weight(c):
    c["candidates"][0]["evidence"][0]["weight"] = 0.123


def edit_time_to_reach(c):
    c["candidates"][0]["time_to_reach_s"] = 999999


def edit_label(c):
    node = next(n for n in c["graph"]["nodes"] if n["label"])
    node["label"]["category"] = "sanctioned"


@pytest.mark.parametrize("edit", [edit_times, edit_rail_time, edit_reached, edit_weight,
                                  edit_time_to_reach, edit_label])
def test_times_weights_and_label_fields_are_in_the_fingerprint(stored, edit):
    case, _ = stored
    other = copy.deepcopy(case)
    edit(other)
    assert P.findings_sha256(other) != P.findings_sha256(case)


def edit_narrative(c):
    c["narrative"] = "The funds went to Binance."


def edit_evidence_text(c):
    c["candidates"][0]["evidence"][0]["text"] = "This address belongs to a named person."


def edit_next_steps(c):
    c["next_steps"] = ["Arrest the account holder."]


@pytest.mark.parametrize("edit", [edit_narrative, edit_evidence_text, edit_next_steps])
def test_edited_wording_in_a_stored_case_does_not_verify(stored, edit):
    case, cache = stored
    other = copy.deepcopy(case)
    edit(other)
    assert P.findings_sha256(other) == P.findings_sha256(case)       # wording is not a figure
    result = verify_stored(other, offline(cache), DemoLabels(), now=NOW, key="test-key")
    assert result["matches"] is False
    assert "text is not the text its content digest was taken from" in result["summary"]


@pytest.mark.parametrize("edit", [edit_narrative, edit_next_steps])
def test_edited_wording_with_a_recomputed_digest_is_caught_by_the_replay(stored, edit):
    case, cache = stored
    other = copy.deepcopy(case)
    edit(other)
    other["provenance"]["content_sha256"] = P.content_sha256(other)
    result = verify_stored(other, offline(cache), DemoLabels(), now=NOW, key="test-key")
    assert check(result, "stored_case")["result"] == "same"
    assert check(result, "content")["result"] == "different" and result["matches"] is False
    assert "text of the result is different from the stored one" in result["summary"]


def test_wording_that_differs_because_the_code_changed_is_said_not_failed(stored, monkeypatch):
    case, cache = stored
    older = copy.deepcopy(case)
    older["narrative"] = "An earlier version worded this differently."
    older["provenance"]["content_sha256"] = P.content_sha256(older)
    older["provenance"]["git_commit"] = "1" * 40
    monkeypatch.setenv("VASPFUSION_GIT_COMMIT", "2" * 40)
    P.git_state.cache_clear()
    try:
        result = verify_stored(older, offline(cache), DemoLabels(), now=NOW, key="test-key")
    finally:
        monkeypatch.delenv("VASPFUSION_GIT_COMMIT")
        P.git_state.cache_clear()
    assert result["matches"] is True
    assert check(result, "content")["result"] == "different"
    assert "the code changed since" in check(result, "content")["detail"]


def test_the_officers_entries_are_not_part_of_either_digest(stored):
    case, cache = stored
    refiled = {**copy.deepcopy(case), "case_ref": "FIR 99/2026", "complaint_no": "1930-1",
               "amount_lost_inr": 5.0, "status": "done"}
    assert P.content_sha256(refiled) == P.content_sha256(case)
    assert verify_stored(refiled, offline(cache), DemoLabels(), now=NOW,
                         key="test-key")["matches"] is True


def test_a_receipt_that_contradicts_itself_is_caught_in_a_stored_case(stored):
    case, cache = stored
    other = copy.deepcopy(case)
    other["provenance"]["responses"] = other["provenance"]["responses"][:1]
    result = verify_stored(other, offline(cache), DemoLabels(), now=NOW, key="test-key")
    assert result["matches"] is False
    assert "list of chain responses does not match" in check(result, "stored_case")["detail"]


def test_a_handed_in_commit_does_not_claim_a_clean_tree(monkeypatch):
    P.git_state.cache_clear()
    monkeypatch.setenv("VASPFUSION_GIT_COMMIT", "a" * 40)
    monkeypatch.delenv("VASPFUSION_GIT_DIRTY", raising=False)
    assert P.git_state() == ("a" * 40, None)
    P.git_state.cache_clear()
    monkeypatch.setenv("VASPFUSION_GIT_DIRTY", "1")
    assert P.git_state() == ("a" * 40, True)
    P.git_state.cache_clear()


# ================================================================== C2, I6, I8: the case file
def test_a_sanctioned_result_that_also_names_an_exchange_says_so(hero):
    """`attribute()` keeps the nearest exchange when a sanctioned address was also reached."""
    case = copy.deepcopy(hero)
    case["outcome"] = "SANCTIONED_OR_MIXER_REACHED"
    case["typology_flags"].insert(0, {
        "code": "sanctioned_contact", "severity": "high", "wallet": case["hop_rail"][0]["to_address"],
        "text": "42% of the funds reached an OFAC-listed address", "figures": {}, "tx_hashes": []})
    text = " ".join(CF.case_file_text(case).split())
    assert "SANCTIONED OR MIXING ADDRESS REACHED" in text
    assert "No exchange is named" not in text
    assert "Nearest exchange: CoinDCX. Confidence 0.85" in text
    assert case_pdf(case).startswith(b"%PDF-")


def test_a_sanctioned_result_with_no_exchange_still_says_none_is_named(tmp_path):
    case = golden_case("tron-ofac", tmp_path / "c.duckdb")
    assert case["top_vasp"] is None
    assert "No exchange is named." in CF.case_file_text(case)


def test_a_wallet_that_is_itself_an_exchange_address_is_described_as_that(hero):
    case = copy.deepcopy(hero)
    c = case["candidates"][0]
    c.update(hops=0, amount=0.0, share_of_funds=1.0, deposit_address=case["address"],
             path=[case["address"]], request_wallets=[], time_to_reach_s=None)
    text = " ".join(CF.case_file_text(case).split())
    assert f"The traced wallet itself is labelled CoinDCX" in text
    assert "reached it in 0 hops" not in text and "(0)" not in text
    assert case_pdf(case).startswith(b"%PDF-")


def test_a_top_exchange_under_the_renderers_bar_does_not_crash(hero):
    from vaspfusion.attribute.rules import RuleConfig
    blocks = CF.case_file(hero, rules=RuleConfig(attribute_min=0.99))
    result = next(b for b in blocks if b["t"] == "result")
    assert "Nearest exchange: CoinDCX" in result["lines"][0]


def test_a_short_address_in_a_sentence_is_never_replaced_by_a_guess(hero):
    """A look-alike (same first and last six characters, as address poisoning makes) of a
    wallet in the case, mentioned in a sentence: the file must not print the case's wallet
    in its place."""
    case = copy.deepcopy(hero)
    inside = case["candidates"][0]["deposit_address"]
    short = f"{inside[:6]}…{inside[-6:]}"
    case["narrative"] = f"It swept into {short}, a wallet outside this case."
    text = CF.case_file_text(case)
    assert f"It swept into {short}, a wallet outside this case." in " ".join(text.split())
    assert "first six and last six characters" in " ".join(text.split())


# ================================================================== I1: the audit log
def test_a_rewritten_and_rehashed_log_does_not_verify_without_the_key(tmp_path):
    log = AuditLog(tmp_path / "audit.duckdb")
    for i, action in enumerate(("auth.login", "case.view", "case.export", "case.view")):
        log.append(officer="a.rao", action=action, target=f"c-{i}", method="GET",
                   path="/api/x", status=200)
    assert log.verify_chain()["ok"] is True
    # the forger: drop the export, rename the officer, renumber, rehash with the public recipe
    from vaspfusion.store.audit import COLS, FIELDS, GENESIS, row_hash
    con = duckdb.connect(str(log.path))
    rows = [dict(zip(FIELDS + ("hash",), r)) for r in
            con.execute(f"SELECT {COLS} FROM audit ORDER BY seq").fetchall()]
    kept = [r for r in rows if r["action"] != "case.export"]
    con.execute("DELETE FROM audit")
    prev = GENESIS
    for seq, r in enumerate(kept, 1):
        r.update(seq=seq, officer="someone.else", prev_hash=prev)
        r["hash"] = prev = row_hash(r)                        # no key: all a forger has
        con.execute("INSERT INTO audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [r[k] for k in FIELDS] + [r["hash"]])
    con.close()
    result = log.verify_chain()
    assert result["ok"] is False and result["broken_at"] == 1


def test_the_audit_key_is_private_and_made_once(tmp_path, monkeypatch):
    import stat
    monkeypatch.delenv("VASPFUSION_AUDIT_KEY", raising=False)
    log = AuditLog(tmp_path / "audit.duckdb")
    key_file = tmp_path / "audit.duckdb.key"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600 and len(key_file.read_text().strip()) == 64
    first = key_file.read_text()
    log.append(action="case.view", method="GET", path="/x", status=200)
    assert AuditLog(tmp_path / "audit.duckdb").verify_chain()["ok"] is True
    assert key_file.read_text() == first


def test_a_log_checked_with_another_key_says_the_key_may_be_wrong(tmp_path, monkeypatch):
    monkeypatch.setenv("VASPFUSION_AUDIT_KEY", "k" * 40)
    log = AuditLog(tmp_path / "audit.duckdb")
    log.append(action="case.view", method="GET", path="/x", status=200)
    assert log.verify_chain()["ok"] is True
    assert not (tmp_path / "audit.duckdb.key").exists()       # the key stays off the disk
    monkeypatch.setenv("VASPFUSION_AUDIT_KEY", "z" * 40)
    result = AuditLog(tmp_path / "audit.duckdb").verify_chain()
    assert result["ok"] is False and "audit key" in result["reason"]


# ================================================================== I4, I5: officers
PASSWORD = "correct horse battery"


def test_disabling_the_only_officer_does_not_switch_the_login_off(tmp_path):
    book = O.Officers(tmp_path / "officers.json")
    assert book.exists() is False
    book.add("a.rao", "Insp. A. Rao", PASSWORD)
    book.disable("a.rao")
    assert book.exists() is True and book.active() is False


def test_parallel_wrong_guesses_cannot_outrun_the_lock(tmp_path):
    book = O.Officers(tmp_path / "officers.json")
    book.add("a.rao", "Insp. A. Rao", PASSWORD)
    evaluated, locked = [], []

    def guess(i):
        try:
            book.verify("a.rao", f"wrong guess {i}")
            evaluated.append(i)
        except O.Locked:
            locked.append(i)
    threads = [threading.Thread(target=guess, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(evaluated) == O.MAX_FAILS and len(locked) == 40 - O.MAX_FAILS


def test_an_unknown_user_name_locks_the_same_way_as_a_real_one(tmp_path):
    book = O.Officers(tmp_path / "officers.json")
    book.add("a.rao", "Insp. A. Rao", PASSWORD)

    def answers(username):
        out = []
        for _ in range(7):
            try:
                out.append(book.verify(username, "wrong password") is None)
            except O.Locked:
                out.append("locked")
        return out
    assert answers("a.rao") == answers("nobody") == [True] * 5 + ["locked"] * 2


def test_the_failure_memory_is_bounded(tmp_path):
    book = O.Officers(tmp_path / "officers.json")
    book.add("a.rao", "Insp. A. Rao", PASSWORD)
    for i in range(O.MAX_TRACKED + 50):
        O._note_attempt((str(book.path), f"user{i}"), now=1000.0)
    assert len(O._FAILS) <= O.MAX_TRACKED + 1


# ================================================================== I3 + minor: tokens
SECRET = b"k" * 32


@pytest.mark.parametrize("sig", ["é", "☃", "a" * 5000])
def test_a_token_with_a_strange_signature_is_refused_not_an_error(sig):
    head, body, _ = T.issue({"sub": "a.rao"}, SECRET, now=1000).split(".")
    with pytest.raises(T.TokenError):
        T.check(f"{head}.{body}.{sig}", SECRET, now=1001)


def test_a_deeply_nested_token_is_refused_not_an_error():
    import base64
    deep = base64.urlsafe_b64encode(("[" * 100000 + "]" * 100000).encode()).rstrip(b"=").decode()
    head = T.issue({"sub": "a.rao"}, SECRET, now=1000).split(".")[0]
    with pytest.raises(T.TokenError):
        T.check(f"{deep}.{deep}.{T._sign(f'{deep}.{deep}'.encode(), SECRET)}", SECRET, now=1001)
    with pytest.raises(T.TokenError):
        T.check(f"{head}.{deep}.{T._sign(f'{head}.{deep}'.encode(), SECRET)}", SECRET, now=1001)


@pytest.mark.parametrize("content", ["", "short", " \n"])
def test_an_empty_or_short_secret_file_is_refused(tmp_path, monkeypatch, content):
    monkeypatch.delenv("VASPFUSION_JWT_SECRET", raising=False)
    path = tmp_path / "auth_secret"
    path.write_text(content)
    with pytest.raises(ValueError, match="at least 32"):
        T.load_secret(path)


# ================================================================== I7: reproduce
def test_reproduce_forgives_only_the_top_level_timestamp_of_a_metrics_file():
    import reproduce as R
    a = {"trained_at": "2026-10-02T00:00:00Z", "n": 1, "nested": {"trained_at": "x"}}
    blob = lambda d: (json.dumps(d, indent=1) + "\n").encode()   # noqa: E731
    metrics = "artifacts/model_v1/tron/metrics.json"
    assert R.classify(metrics, blob(a), blob({**a, "trained_at": "2026-10-03T00:00:00Z"})) == \
        "only_timestamp"
    assert R.classify(metrics, blob(a), blob({**a, "nested": {"trained_at": "y"}})) == "changed"
    assert R.classify(metrics, blob(a), blob({**a, "n": True})) == "changed"       # 1 is not true
    assert R.classify(metrics, blob(a), blob({**a, "trained_at": 5})) == "changed"
    # a schema file that merely has a property called trained_at gets no such allowance
    assert R.classify("docs/openapi.json", blob(a),
                      blob({**a, "trained_at": "2026-10-03T00:00:00Z"})) == "changed"
    assert R.classify("mocks/model.json", blob(a),
                      blob({**a, "trained_at": "2026-10-03T00:00:00Z"})) == "only_timestamp"
