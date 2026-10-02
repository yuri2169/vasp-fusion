/** Address checks, in the browser, by the same rules as vaspfusion/chains/addresses.py:
 *  Tron base58check (0x41), EVM with EIP-55 when mixed case, Bitcoin base58check and
 *  bech32/bech32m, Solana 32-byte base58. The server checks again; this is so the search
 *  bar can name the chain while the officer is still typing, and catch a typo before a trace. */
import { keccak_256 } from '@noble/hashes/sha3.js'
import { sha256 } from '@noble/hashes/sha2.js'
import { base58, bech32, bech32m, createBase58check } from '@scure/base'
import type { Chain } from '../api/models'
import { CHAINS } from './chains'

const base58check = createBase58check(sha256)
const BASE58 = /^[1-9A-HJ-NP-Za-km-z]+$/
const BECH32_BODY = /^[02-9ac-hj-np-z]*$/
const EVM = /^0x[0-9a-fA-F]{40}$/

function b58check(address: string): Uint8Array | null {
  try {
    return base58check.decode(address)
  } catch {
    return null
  }
}

function tronOk(a: string): boolean {
  const raw = b58check(a)
  return raw !== null && raw.length === 21 && raw[0] === 0x41
}

function eip55(address: string): string {
  const body = address.slice(2).toLowerCase()
  const hash = keccak_256(new TextEncoder().encode(body))
  let out = '0x'
  for (let i = 0; i < 40; i++) {
    const nibble = i % 2 === 0 ? hash[i >> 1] >> 4 : hash[i >> 1] & 15
    out += nibble >= 8 ? body[i].toUpperCase() : body[i]
  }
  return out
}

function evmOk(a: string): boolean {
  if (!EVM.test(a)) return false
  const body = a.slice(2)
  if (body === body.toLowerCase() || body === body.toUpperCase()) return true
  return eip55(a) === a
}

function segwitOk(address: string): boolean {
  if (address.toLowerCase() !== address && address.toUpperCase() !== address) return false
  const a = address.toLowerCase() as `${string}1${string}`
  for (const codec of [bech32, bech32m]) {
    try {
      const { prefix, words } = codec.decode(a, 90)
      if (prefix !== 'bc' || words.length === 0) return false
      const version = words[0]
      if ((version === 0) !== (codec === bech32)) return false
      const program = codec.fromWords(words.slice(1))
      if (version > 16 || program.length < 2 || program.length > 40) return false
      return !(version === 0 && program.length !== 20 && program.length !== 32)
    } catch {
      /* wrong checksum for this encoding: try the other */
    }
  }
  return false
}

function btcOk(a: string): boolean {
  if (a.toLowerCase().startsWith('bc1')) return segwitOk(a)
  const raw = b58check(a)
  return raw !== null && raw.length === 21 && (raw[0] === 0x00 || raw[0] === 0x05)
}

function solanaOk(a: string): boolean {
  if (a.length < 32 || a.length > 44 || !BASE58.test(a)) return false
  try {
    return base58.decode(a).length === 32
  } catch {
    return false
  }
}

export function validate(address: string, chain: Chain): boolean {
  const a = address.trim()
  switch (CHAINS[chain].family) {
    case 'tron':
      return tronOk(a)
    case 'evm':
      return evmOk(a)
    case 'bitcoin':
      return btcOk(a)
    case 'solana':
      return solanaOk(a)
  }
}

/** Tron, Bitcoin and Solana are unambiguous. An EVM address is valid on every EVM
 *  chain, so 'ethereum' is returned; the officer picks another chain if it is one. */
export function detectChain(address: string): Chain | null {
  for (const chain of ['tron', 'ethereum', 'bitcoin', 'solana'] as const) if (validate(address, chain)) return chain
  return null
}

export type Inspection =
  | { state: 'empty' }
  /** A prefix that could still become an address. */
  | { state: 'typing'; guess: Chain | null }
  | { state: 'valid'; chain: Chain; traceable: boolean; normalized: string }
  /** `reason` is a sentence for the officer: what is wrong and what to do. */
  | { state: 'invalid'; guess: Chain | null; reason: string }

const NOT_AN_ADDRESS =
  'This is not a wallet address. Paste a Tron (T…), EVM (0x…) or Bitcoin (1…, 3…, bc1…) address.'

/** What the search bar shows while the officer types. */
export function inspectAddress(input: string): Inspection {
  const a = input.trim()
  if (!a) return { state: 'empty' }

  const chain = detectChain(a)
  if (chain) {
    // Stored forms: EVM and bech32 lowercase, Tron and legacy Bitcoin as written.
    const lower = chain === 'ethereum' || a.toLowerCase().startsWith('bc1')
    return { state: 'valid', chain, traceable: CHAINS[chain].traceable, normalized: lower ? a.toLowerCase() : a }
  }

  if (/^0x?/i.test(a) && (a.length === 1 || /^0x/i.test(a))) {
    const body = a.slice(2)
    if (!/^[0-9a-fA-F]*$/.test(body))
      return {
        state: 'invalid',
        guess: 'ethereum',
        reason: 'After 0x an EVM address has only the digits 0-9 and the letters a-f. Check the address for a typo.',
      }
    if (body.length < 40) return { state: 'typing', guess: 'ethereum' }
    if (body.length > 40)
      return {
        state: 'invalid',
        guess: 'ethereum',
        reason: `An EVM address has 40 characters after 0x; this has ${body.length}. Check for extra characters.`,
      }
    return {
      state: 'invalid',
      guess: 'ethereum',
      reason: 'The capital letters do not match this address’s checksum. Paste it again, or type it all in lower case.',
    }
  }

  if (/^bc1/i.test(a)) {
    if (!BECH32_BODY.test(a.slice(3).toLowerCase()))
      return {
        state: 'invalid',
        guess: 'bitcoin',
        reason: 'A bc1 Bitcoin address does not use the characters 1, b, i or o after the prefix. Check the address for a typo.',
      }
    if (a.length !== 42 && a.length < 62) return { state: 'typing', guess: 'bitcoin' }
    return {
      state: 'invalid',
      guess: 'bitcoin',
      reason:
        a.length > 62
          ? 'Too long for a Bitcoin address. Check for extra characters.'
          : 'The checksum of this Bitcoin address does not match. Check it for a typo, or paste it again.',
    }
  }

  if (!BASE58.test(a)) return { state: 'invalid', guess: null, reason: NOT_AN_ADDRESS }

  const guess: Chain | null = a[0] === 'T' ? 'tron' : a[0] === '1' || a[0] === '3' ? 'bitcoin' : null
  if (a.length < 34) return { state: 'typing', guess }
  if (a.length === 34 && guess)
    return {
      state: 'invalid',
      guess,
      reason: `The checksum of this ${CHAINS[guess].name} address does not match. Check it for a typo, or paste it again.`,
    }
  // Only Solana addresses are longer than 34 base58 characters.
  if (a.length < 44) return { state: 'typing', guess: 'solana' }
  return {
    state: 'invalid',
    guess: a.length === 44 ? 'solana' : null,
    reason:
      a.length === 44
        ? 'This is not a valid Solana address. Check it for a typo, or paste it again.'
        : 'Too long for a wallet address. Check for extra characters.',
  }
}
