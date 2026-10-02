import { describe, expect, it } from 'vitest'
import type { CaseList } from '../api/models'
import { readMock } from '../test/files'
import { detectChain, inspectAddress, validate } from './addresses'

// Real addresses: the demo wallets in demo/cases.json (see PROGRESS.md), the two
// checksum examples printed in EIP-55, and Solana's wrapped-SOL mint.
const TRON = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c'
const ETH_LOWER = '0x8971dd825ba5dd32b60307773f71f6e3efb0eda9'
const ETH_EIP55 = '0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed'
const BTC_BECH32 = 'bc1qw75rzzczmu2ulmjnrat3kn8h2rrrlr6wt7q3x6'
const BTC_P2PKH = '19vP8bkaR5K9K5W12QyHoYd7TZpz16BxSV'
const BTC_P2PKH_2 = '1AQLXAB6aXSVbRMjbhSBudLf1kcsbWSEjg'
const SOLANA = 'So11111111111111111111111111111111111111112'

describe('validate / detectChain (the rules of vaspfusion/chains/addresses.py)', () => {
  it.each([
    [TRON, 'tron'],
    [ETH_LOWER, 'ethereum'],
    [ETH_EIP55, 'ethereum'],
    [ETH_LOWER.toUpperCase().replace('0X', '0x'), 'ethereum'],
    [BTC_BECH32, 'bitcoin'],
    [BTC_BECH32.toUpperCase(), 'bitcoin'],
    [BTC_P2PKH, 'bitcoin'],
    [BTC_P2PKH_2, 'bitcoin'],
    [SOLANA, 'solana'],
  ])('%s is %s', (address, chain) => {
    expect(detectChain(address)).toBe(chain)
  })

  it('an EVM address is valid on every EVM chain', () => {
    for (const chain of ['ethereum', 'bsc', 'polygon', 'arbitrum', 'base', 'optimism', 'avalanche'] as const)
      expect(validate(ETH_LOWER, chain)).toBe(true)
    expect(validate(ETH_LOWER, 'tron')).toBe(false)
  })

  it('refuses a mixed-case EVM address whose checksum is wrong', () => {
    const flipped = ETH_EIP55.replace('5aAeb', '5AAeb')
    expect(validate(flipped, 'ethereum')).toBe(false)
    expect(detectChain(flipped)).toBeNull()
  })

  it('refuses a Tron address with one character changed', () => {
    expect(detectChain(TRON.replace('ZKBN', 'ZKBM'))).toBeNull()
  })

  it('refuses mixed-case bech32 and a bech32 with one character changed', () => {
    expect(detectChain('bc1Qw75rzzczmu2ulmjnrat3kn8h2rrrlr6wt7q3x6')).toBeNull()
    expect(detectChain(BTC_BECH32.replace('zzc', 'zzq'))).toBeNull()
  })

  it('gives every mock case address the chain the fixture states', () => {
    for (const c of readMock<CaseList>('cases.json').items) expect(validate(c.address, c.chain), c.id).toBe(true)
  })
})

describe('inspectAddress (as the officer types)', () => {
  it('is empty for nothing or spaces', () => {
    expect(inspectAddress('')).toEqual({ state: 'empty' })
    expect(inspectAddress('   ')).toEqual({ state: 'empty' })
  })

  it.each([
    ['TYJD2hZKBN', 'tron'],
    ['T', 'tron'],
    ['0x8971dd', 'ethereum'],
    ['0x', 'ethereum'],
    ['bc1qw75', 'bitcoin'],
    ['19vP8bka', 'bitcoin'],
    ['3J98t1Wp', 'bitcoin'],
  ])('%s is still being typed, probably %s', (input, guess) => {
    expect(inspectAddress(input)).toEqual({ state: 'typing', guess })
  })

  it('a whole valid address is valid, trimmed, with its chain', () => {
    expect(inspectAddress(`  ${TRON}\n`)).toEqual({ state: 'valid', chain: 'tron', traceable: true, normalized: TRON })
    expect(inspectAddress(BTC_BECH32.toUpperCase())).toMatchObject({ state: 'valid', chain: 'bitcoin', normalized: BTC_BECH32 })
    expect(inspectAddress(ETH_EIP55)).toMatchObject({ state: 'valid', chain: 'ethereum', normalized: ETH_EIP55.toLowerCase() })
  })

  it('a Solana address is valid but cannot be traced yet', () => {
    expect(inspectAddress(SOLANA)).toMatchObject({ state: 'valid', chain: 'solana', traceable: false })
  })

  it('a full-length Tron address with a typo says the checksum does not match', () => {
    const r = inspectAddress(TRON.replace('ZKBN', 'ZKBM'))
    expect(r).toMatchObject({ state: 'invalid', guess: 'tron' })
    expect(r.state === 'invalid' && r.reason).toMatch(/checksum/i)
  })

  it('a mixed-case EVM address with a wrong checksum says so', () => {
    const r = inspectAddress(ETH_EIP55.replace('5aAeb', '5AAeb'))
    expect(r).toMatchObject({ state: 'invalid', guess: 'ethereum' })
    expect(r.state === 'invalid' && r.reason).toMatch(/capital/i)
  })

  it('an EVM address that is too long is invalid, not still typing', () => {
    expect(inspectAddress(`${ETH_LOWER}ab`)).toMatchObject({ state: 'invalid', guess: 'ethereum' })
  })

  it('a character no address uses is invalid at once', () => {
    expect(inspectAddress('0x89zz')).toMatchObject({ state: 'invalid', guess: 'ethereum' })
    expect(inspectAddress('hello world')).toMatchObject({ state: 'invalid', guess: null })
  })

  it('every reason is a sentence that says what to do', () => {
    for (const input of ['hello world', '0x89zz', `${ETH_LOWER}ab`, TRON.replace('ZKBN', 'ZKBM')]) {
      const r = inspectAddress(input)
      expect(r.state === 'invalid' && r.reason).toMatch(/^[A-Z].+\.$/)
    }
  })
})
