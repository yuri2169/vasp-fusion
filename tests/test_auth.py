"""Officer accounts and login tokens. Standard library only (HS256, scrypt)."""
import base64
import json
import stat

import pytest

from vaspfusion.auth import officers as O
from vaspfusion.auth import tokens as T

SECRET = b"k" * 32
GOOD = "correct horse battery"


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


# ------------------------------------------------------------------ tokens
def test_a_token_round_trips_its_claims():
    token = T.issue({"sub": "a.rao", "name": "Insp. A. Rao"}, SECRET, ttl_s=600, now=1000)
    claims = T.check(token, SECRET, now=1500)
    assert claims["sub"] == "a.rao" and claims["name"] == "Insp. A. Rao"
    assert (claims["iat"], claims["exp"]) == (1000, 1600)
    assert token.count(".") == 2


def test_an_expired_token_is_refused():
    token = T.issue({"sub": "a.rao"}, SECRET, ttl_s=600, now=1000)
    with pytest.raises(T.TokenError, match="expired"):
        T.check(token, SECRET, now=1600)


def test_a_token_signed_with_another_secret_is_refused():
    token = T.issue({"sub": "a.rao"}, b"x" * 32, ttl_s=600, now=1000)
    with pytest.raises(T.TokenError, match="signature"):
        T.check(token, SECRET, now=1001)


def test_a_changed_payload_is_refused():
    head, body, sig = T.issue({"sub": "a.rao"}, SECRET, ttl_s=600, now=1000).split(".")
    forged = ".".join([head, _b64({"sub": "admin", "iat": 1000, "exp": 1600}), sig])
    with pytest.raises(T.TokenError, match="signature"):
        T.check(forged, SECRET, now=1001)


@pytest.mark.parametrize("alg", ["none", "None", "HS512", "RS256"])
def test_only_hs256_is_accepted(alg):
    """The classic downgrade: a token that names its own (weaker, or no) algorithm."""
    body = _b64({"sub": "admin", "iat": 1000, "exp": 9999999999})
    for sig in ("", "AAAA"):
        with pytest.raises(T.TokenError):
            T.check(f"{_b64({'alg': alg, 'typ': 'JWT'})}.{body}.{sig}", SECRET, now=1001)


@pytest.mark.parametrize("junk", ["", "a.b", "a.b.c.d", "....", "not a token", "a.b.c"])
def test_junk_is_refused_not_raised_as_something_else(junk):
    with pytest.raises(T.TokenError):
        T.check(junk, SECRET, now=1)


def test_a_token_without_an_expiry_is_refused():
    head = _b64({"alg": "HS256", "typ": "JWT"})
    body = _b64({"sub": "a.rao"})
    sig = T._sign(f"{head}.{body}".encode(), SECRET)
    with pytest.raises(T.TokenError, match="expiry"):
        T.check(f"{head}.{body}.{sig}", SECRET, now=1)


def test_the_secret_comes_from_the_environment_or_a_private_file(tmp_path, monkeypatch):
    monkeypatch.delenv("VASPFUSION_JWT_SECRET", raising=False)
    path = tmp_path / "auth_secret"
    first = T.load_secret(path)
    assert len(first) >= 32 and T.load_secret(path) == first            # made once, then kept
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    monkeypatch.setenv("VASPFUSION_JWT_SECRET", "s" * 40)
    assert T.load_secret(path) == b"s" * 40


def test_a_short_secret_in_the_environment_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("VASPFUSION_JWT_SECRET", "short")
    with pytest.raises(ValueError, match="at least 32"):
        T.load_secret(tmp_path / "s")


# ------------------------------------------------------------------ officers
@pytest.fixture
def book(tmp_path):
    clock = {"t": 1_000_000.0}
    b = O.Officers(tmp_path / "officers.json", clock=lambda: clock["t"])
    b.clock_state = clock
    b.add("a.rao", "Insp. A. Rao", GOOD, post="Cyber Crime PS")
    return b


def test_the_right_password_signs_in_and_a_wrong_one_does_not(book):
    officer = book.verify("a.rao", GOOD)
    assert officer == {"username": "a.rao", "name": "Insp. A. Rao", "post": "Cyber Crime PS"}
    assert book.verify("a.rao", "wrong password") is None
    assert book.verify("nobody", GOOD) is None


def test_the_file_holds_no_password(book):
    text = book.path.read_text()
    assert GOOD not in text and "correct" not in text
    row = json.loads(text)["officers"][0]
    assert set(row) >= {"username", "name", "salt", "hash", "scrypt"} and len(row["hash"]) == 64
    assert stat.S_IMODE(book.path.stat().st_mode) == 0o600


def test_two_officers_with_one_password_have_different_hashes(book):
    book.add("b.sen", "SI B. Sen", GOOD)
    rows = {r["username"]: r for r in json.loads(book.path.read_text())["officers"]}
    assert rows["a.rao"]["hash"] != rows["b.sen"]["hash"]


def test_five_wrong_passwords_lock_the_account_for_five_minutes(book):
    for _ in range(5):
        assert book.verify("a.rao", "wrong password") is None
    with pytest.raises(O.Locked, match="5 minutes"):
        book.verify("a.rao", GOOD)                      # even the right one, while locked
    book.clock_state["t"] += 301
    assert book.verify("a.rao", GOOD)["username"] == "a.rao"


def test_a_good_sign_in_clears_the_count(book):
    for _ in range(4):
        book.verify("a.rao", "wrong password")
    assert book.verify("a.rao", GOOD)
    for _ in range(4):
        assert book.verify("a.rao", "wrong password") is None    # no lock: count restarted


def test_a_disabled_officer_cannot_sign_in(book):
    book.disable("a.rao")
    assert book.verify("a.rao", GOOD) is None
    assert book.list() == [{"username": "a.rao", "name": "Insp. A. Rao",
                            "post": "Cyber Crime PS", "disabled": True}]
    assert book.active() is False


@pytest.mark.parametrize("username", ["A.Rao", "a rao", "a", "x" * 33, "../etc", "a/b", ""])
def test_user_names_are_plain(book, username):
    with pytest.raises(ValueError, match="user name"):
        book.add(username, "Name", GOOD)


def test_a_short_password_a_duplicate_and_a_non_latin_name_are_refused(book):
    with pytest.raises(ValueError, match="at least 10"):
        book.add("b.sen", "SI B. Sen", "short")
    with pytest.raises(ValueError, match="already"):
        book.add("a.rao", "Someone Else", GOOD)
    with pytest.raises(ValueError, match="Latin"):
        book.add("c.das", "निरीक्षक", GOOD)


def test_no_file_means_no_officers(tmp_path):
    b = O.Officers(tmp_path / "none.json")
    assert b.list() == [] and b.active() is False and b.verify("a.rao", GOOD) is None
    assert not (tmp_path / "none.json").exists()         # reading never creates it
