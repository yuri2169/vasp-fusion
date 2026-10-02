import { expect, it } from 'vitest'
import { addressUrl, txUrl } from './explorers'

it('links a Tron address and transaction to Tronscan', () => {
  expect(addressUrl('tron', 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c')).toBe(
    'https://tronscan.org/#/address/TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c',
  )
  expect(txUrl('tron', 'c09b2c24')).toBe('https://tronscan.org/#/transaction/c09b2c24')
})

it('links an Ethereum address and transaction to Etherscan, adding 0x to a bare hash', () => {
  expect(addressUrl('ethereum', '0x8971dd825ba5dd32b60307773f71f6e3efb0eda9')).toBe(
    'https://etherscan.io/address/0x8971dd825ba5dd32b60307773f71f6e3efb0eda9',
  )
  expect(txUrl('ethereum', 'abc123')).toBe('https://etherscan.io/tx/0xabc123')
  expect(txUrl('ethereum', '0xabc123')).toBe('https://etherscan.io/tx/0xabc123')
})

it('links Bitcoin to the explorer the backend reads from', () => {
  expect(addressUrl('bitcoin', '19vP8bkaR5K9K5W12QyHoYd7TZpz16BxSV')).toBe(
    'https://blockstream.info/address/19vP8bkaR5K9K5W12QyHoYd7TZpz16BxSV',
  )
  expect(txUrl('bitcoin', 'f96b97dd')).toBe('https://blockstream.info/tx/f96b97dd')
})

it('has an explorer for every chain in the contract', () => {
  for (const chain of ['tron', 'ethereum', 'bsc', 'polygon', 'arbitrum', 'base', 'optimism', 'avalanche', 'bitcoin', 'solana'] as const)
    expect(addressUrl(chain, 'x')).toMatch(/^https:\/\//)
})
