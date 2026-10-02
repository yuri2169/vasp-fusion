import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Vitest runs from ui/. The B1 fixtures are one level up, in mocks/. */
export const readUi = (path: string): string => readFileSync(resolve(process.cwd(), path), 'utf8')

/** A mock fixture as the API would return it: without the `_demo` / `_notice` keys. */
export function readMock<T>(path: string): T {
  const raw = JSON.parse(readFileSync(resolve(process.cwd(), '..', 'mocks', path), 'utf8')) as Record<string, unknown>
  return Object.fromEntries(Object.entries(raw).filter(([k]) => !k.startsWith('_'))) as T
}

/** A stored result of one of the real demo wallets (src/test/fixtures/cases/README.md). */
export function readCase<T>(id: string): T {
  return JSON.parse(readFileSync(resolve(process.cwd(), 'src', 'test', 'fixtures', 'cases', `${id}.json`), 'utf8')) as T
}

export const MOCK_CASES = ['demo-tron-okx', 'demo-eth-abstain', 'demo-tron-sanctioned'] as const
export const REAL_CASES = ['tron-coindcx', 'tron-htx-coindcx', 'tron-abstain', 'tron-ofac', 'eth-bridge'] as const
