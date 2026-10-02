"""Property tests on address validation (Hypothesis).

Addresses are generated from their specifications with encoders written here,
independently of `vaspfusion.chains.addresses`: base58check (Bitcoin, Tron), EIP-55
(the checksum casing comes from the module's own Keccak, which is
checked against the published EIP-55 vectors in test_addresses.py), and bech32 /
bech32m (BIP-173 / BIP-350 reference encoder).
"""
import hashlib

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from vaspfusion.chains.addresses import (EVM_FAMILY, InvalidAddress, detect_chain, eip55,
                                         validate)

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
CHAINS = ("tron", "ethereum", "bitcoin", "solana", "polygon", "evm")

bytes20 = st.binary(min_size=20, max_size=20)
bytes32 = st.binary(min_size=32, max_size=32)


# ------------------------------------------------------------------ reference encoders
def b58(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def b58check(version: int, payload: bytes) -> str:
    body = bytes([version]) + payload
    return b58(body + hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4])


def _polymod(values):
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def segwit(version: int, program: bytes, const: int | None = None, hrp: str = "bc") -> str:
    """BIP-173 (v0, constant 1) / BIP-350 (v1+, constant 0x2bc830a3)."""
    acc, bits, data = 0, 0, [version]
    for b in program:
        acc, bits = (acc << 8) | b, bits + 8
        while bits >= 5:
            bits -= 5
            data.append((acc >> bits) & 31)
    if bits:
        data.append((acc << (5 - bits)) & 31)
    const = (1 if version == 0 else 0x2bc830a3) if const is None else const
    exp = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    mod = _polymod(exp + data + [0] * 6) ^ const
    check = [(mod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(BECH[d] for d in data + check)


def swap_one(address: str, index: int, alphabet: str) -> str:
    """The address with the character at `index` replaced by the next one in `alphabet`."""
    i = index % len(address)
    old = address[i]
    new = alphabet[(alphabet.index(old) + 1) % len(alphabet)] if old in alphabet else alphabet[0]
    return address[:i] + new + address[i + 1:]


# ------------------------------------------------------------------ Tron
@given(bytes20)
def test_a_generated_tron_address_is_valid_and_detected(payload):
    a = b58check(0x41, payload)
    assert a.startswith("T") and len(a) == 34
    assert validate(a, "tron") and detect_chain(a) == "tron"
    assert not validate(a, "bitcoin") and not validate(a, "ethereum")


@given(bytes20, st.integers(min_value=0, max_value=33))
def test_one_changed_character_breaks_a_tron_address(payload, index):
    a = b58check(0x41, payload)
    assert not validate(swap_one(a, index, B58), "tron")


@given(bytes20, st.integers(min_value=0, max_value=255).filter(lambda v: v != 0x41))
def test_base58check_with_another_version_byte_is_not_tron(payload, version):
    assert not validate(b58check(version, payload), "tron")


# ------------------------------------------------------------------ EVM
@given(bytes20)
def test_a_generated_evm_address_is_valid_in_all_three_spellings(raw):
    lower = "0x" + raw.hex()
    for a in (lower, "0x" + raw.hex().upper(), eip55(lower)):
        assert validate(a, "ethereum") and detect_chain(a) == "ethereum"
        assert all(validate(a, chain) for chain in EVM_FAMILY)
    assert eip55(eip55(lower)) == eip55(lower)                    # checksumming is stable
    assert eip55(lower).lower() == lower


@given(bytes20, st.integers(min_value=0, max_value=39))
def test_one_wrong_letter_case_breaks_an_eip55_address(raw, index):
    good = eip55("0x" + raw.hex())
    body = good[2:]
    i = index % 40
    assume(body[i].isalpha())
    bad = body[:i] + body[i].swapcase() + body[i + 1:]
    assume(bad != bad.lower() and bad != bad.upper())             # those spellings carry no checksum
    assert not validate("0x" + bad, "ethereum")


@given(st.binary(min_size=0, max_size=40).filter(lambda b: len(b) != 20))
def test_an_evm_address_of_the_wrong_length_is_invalid(raw):
    assert not validate("0x" + raw.hex(), "ethereum")


# ------------------------------------------------------------------ Bitcoin
@given(bytes20, st.sampled_from([0x00, 0x05]))
def test_a_generated_base58_bitcoin_address_is_valid_and_detected(payload, version):
    a = b58check(version, payload)
    assert a[0] in "13"
    assert validate(a, "bitcoin") and detect_chain(a) == "bitcoin"
    assert not validate(a, "tron")


@given(bytes20, st.sampled_from([0x00, 0x05]), st.integers(min_value=0, max_value=33))
def test_one_changed_character_breaks_a_base58_bitcoin_address(payload, version, index):
    a = b58check(version, payload)
    assert not validate(swap_one(a, index, B58), "bitcoin")


@given(st.one_of(bytes20, bytes32))
def test_a_generated_segwit_v0_address_is_valid(program):
    a = segwit(0, program)
    assert validate(a, "bitcoin") and detect_chain(a) == "bitcoin"
    assert not validate(segwit(0, program, const=0x2bc830a3), "bitcoin")   # v0 needs bech32


@given(bytes32)
def test_a_generated_taproot_address_is_valid(program):
    a = segwit(1, program)
    assert a.startswith("bc1p") and validate(a, "bitcoin") and detect_chain(a) == "bitcoin"
    assert not validate(segwit(1, program, const=1), "bitcoin")            # v1 needs bech32m


@given(st.one_of(bytes20, bytes32), st.integers(min_value=4, max_value=61))
def test_one_changed_character_breaks_a_segwit_address(program, index):
    a = segwit(0, program)
    i = 4 + index % (len(a) - 4)                                  # after "bc1q"
    assert not validate(swap_one(a, i, BECH), "bitcoin")


@given(st.binary(min_size=1, max_size=40).filter(lambda b: len(b) not in (20, 32)))
def test_a_v0_program_of_the_wrong_length_is_invalid(program):
    assert not validate(segwit(0, program), "bitcoin")


# ------------------------------------------------------------------ Solana
@given(bytes32)
def test_a_generated_solana_address_is_valid_and_detected(raw):
    a = b58(raw)
    assume(32 <= len(a) <= 44)                    # many leading zero bytes give a shorter one
    assert validate(a, "solana") and detect_chain(a) == "solana"
    assert not validate(a, "tron") and not validate(a, "bitcoin")


# ------------------------------------------------------------------ anything at all
@settings(max_examples=400)
@given(st.text(max_size=120), st.sampled_from(CHAINS))
def test_validate_answers_yes_or_no_for_any_text(text, chain):
    assert validate(text, chain) in (True, False)


@settings(max_examples=400)
@given(st.one_of(st.text(max_size=120), st.text(alphabet=B58 + "0xOIl", min_size=20, max_size=64)))
def test_detect_chain_names_a_chain_the_text_is_valid_on_or_refuses(text):
    try:
        chain = detect_chain(text)
    except InvalidAddress:
        assert not any(validate(text, c) for c in ("tron", "ethereum", "bitcoin", "solana"))
    else:
        assert validate(text, chain)


@given(bytes20, st.sampled_from(["", " ", "\n", "\t ", "  \r\n"]),
       st.sampled_from(["", " ", "\n", " \t"]))
def test_surrounding_whitespace_does_not_matter(payload, before, after):
    a = b58check(0x41, payload)
    assert validate(before + a + after, "tron") and detect_chain(before + a + after) == "tron"


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12)
       .filter(lambda c: c not in CHAINS + EVM_FAMILY))
def test_an_unknown_chain_is_refused_not_guessed(chain):
    try:
        validate("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", chain)
    except InvalidAddress:
        return
    raise AssertionError(f"validate accepted the unknown chain {chain!r}")
