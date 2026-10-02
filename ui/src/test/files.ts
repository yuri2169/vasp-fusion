import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Vitest runs from ui/. The B1 fixtures are one level up, in mocks/. */
export const readUi = (path: string): string => readFileSync(resolve(process.cwd(), path), 'utf8')

/** A mock fixture as the API would return it: without the `_demo` / `_notice` keys. */
export function readMock<T>(path: string): T {
  const raw = JSON.parse(readFileSync(resolve(process.cwd(), '..', 'mocks', path), 'utf8')) as Record<string, unknown>
  return Object.fromEntries(Object.entries(raw).filter(([k]) => !k.startsWith('_'))) as T
}
