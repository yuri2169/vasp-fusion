"""Address validation and chain detection, stdlib only.

* Tron: base58check, 25 bytes, version byte 0x41.
* EVM: 0x + 40 hex; mixed case must match the EIP-55 checksum (Keccak-256).
* Bitcoin: base58check P2PKH (0x00) / P2SH (0x05), or segwit bech32 (v0, BIP-173)
  / bech32m (v1+, BIP-350).
* Solana: base58 that decodes to 32 bytes (no checksum exists).

hashlib's sha3_256 is NIST SHA-3, not Ethereum's Keccak (different padding), so
Keccak-256 is implemented here; it is only used on 20-byte hex strings.
"""
from __future__ import annotations

import hashlib
import re

from .base import InvalidAddress

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(B58)}
EVM_FAMILY = ("ethereum", "bsc", "polygon", "arbitrum", "base", "optimism", "avalanche")


# ------------------------------------------------------------------ base58
def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        if c not in _B58_INDEX:
            raise InvalidAddress(f"not base58: {c!r}")
        n = n * 58 + _B58_INDEX[c]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def _checksum(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]


def b58check_decode(s: str) -> bytes:
    raw = b58decode(s)
    if len(raw) < 5 or _checksum(raw[:-4]) != raw[-4:]:
        raise InvalidAddress("bad base58check checksum")
    return raw[:-4]


def tron_hex_to_base58(hex_addr: str) -> str:
    """TronGrid's raw transactions give addresses as hex '41' + 20 bytes."""
    payload = bytes.fromhex(hex_addr.removeprefix("0x"))
    if len(payload) != 21 or payload[0] != 0x41:
        raise InvalidAddress(f"not a Tron hex address: {hex_addr}")
    return b58encode(payload + _checksum(payload))


# ------------------------------------------------------------------ keccak
_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
        [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M64 = (1 << 64) - 1


def _rol(v: int, n: int) -> int:
    return ((v << n) | (v >> (64 - n))) & _M64 if n else v


def _keccak_f(a: list[list[int]]) -> None:
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                a[x][y] ^= d[x]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        for x in range(5):
            for y in range(5):
                a[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])
        a[0][0] ^= rc


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\0" * (-len(msg) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        _keccak_f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out


def eip55(address: str) -> str:
    h = address.lower().removeprefix("0x")
    digest = keccak256(h.encode()).hex()
    return "0x" + "".join(c.upper() if c.isalpha() and int(digest[i], 16) >= 8 else c
                          for i, c in enumerate(h))


# ------------------------------------------------------------------ bech32
_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST, _BECH32M_CONST = 1, 0x2BC830A3


def _polymod(values: list[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def _convertbits(data: list[int], frombits: int, tobits: int) -> list[int] | None:
    acc = bits = 0
    out = []
    for v in data:
        acc = (acc << frombits) | v
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & ((1 << tobits) - 1))
    if bits >= frombits or ((acc << (tobits - bits)) & ((1 << tobits) - 1)):
        return None
    return out


def _segwit_ok(addr: str, hrp: str = "bc") -> bool:
    if addr.lower() != addr and addr.upper() != addr:
        return False
    a = addr.lower()
    pos = a.rfind("1")
    if a[:pos] != hrp or pos + 7 > len(a) or len(a) > 90:
        return False
    try:
        data = [_BECH32.index(c) for c in a[pos + 1:]]
    except ValueError:
        return False
    const = _polymod([ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + data)
    version = data[0]
    if const != (_BECH32_CONST if version == 0 else _BECH32M_CONST):
        return False
    prog = _convertbits(data[1:-6], 5, 8)
    if prog is None or version > 16 or not 2 <= len(prog) <= 40:
        return False
    return not (version == 0 and len(prog) not in (20, 32))


# ------------------------------------------------------------------ public
_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _tron_ok(a: str) -> bool:
    try:
        raw = b58check_decode(a)
    except InvalidAddress:
        return False
    return len(raw) == 21 and raw[0] == 0x41


def _evm_ok(a: str) -> bool:
    if not _EVM_RE.match(a):
        return False
    body = a[2:]
    if body == body.lower() or body == body.upper():
        return True
    return eip55(a) == a


def _btc_ok(a: str) -> bool:
    if a.lower().startswith("bc1"):
        return _segwit_ok(a)
    try:
        raw = b58check_decode(a)
    except InvalidAddress:
        return False
    return len(raw) == 21 and raw[0] in (0x00, 0x05)


def _solana_ok(a: str) -> bool:
    if not 32 <= len(a) <= 44:
        return False
    try:
        return len(b58decode(a)) == 32
    except InvalidAddress:
        return False


def validate(address: str, chain: str) -> bool:
    a = address.strip()
    if chain == "tron":
        return _tron_ok(a)
    if chain in EVM_FAMILY or chain == "evm":
        return _evm_ok(a)
    if chain == "bitcoin":
        return _btc_ok(a)
    if chain == "solana":
        return _solana_ok(a)
    raise InvalidAddress(f"unsupported chain: {chain}")


def detect_chain(address: str) -> str:
    """Tron, Bitcoin and Solana are unambiguous. An EVM address is valid on every
    EVM chain, so 'ethereum' is returned; callers pass --chain for the others."""
    a = address.strip()
    for chain in ("tron", "ethereum", "bitcoin", "solana"):
        if validate(a, chain):
            return chain
    raise InvalidAddress(f"not a valid Tron, EVM, Bitcoin or Solana address: {a[:64]!r}")
