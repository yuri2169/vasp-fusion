import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'
import { mockSettings } from '../api/mock'

/** A demo wallet's case opens at once in tests; a test of the trace screen sets its own time. */
beforeEach(() => {
  mockSettings.traceMs = 0
})

afterEach(() => {
  cleanup()
  document.documentElement.removeAttribute('data-theme')
  localStorage.clear()
})

/** jsdom has no matchMedia. Tests that care call `setMedia('(prefers-reduced-motion: reduce)')`. */
const matching = new Set<string>()
export function setMedia(...queries: string[]) {
  matching.clear()
  for (const q of queries) matching.add(q)
}
afterEach(() => matching.clear())

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    get matches() {
      return matching.has(query)
    },
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
})

/** jsdom's <dialog> has no showModal/close. Enough of both for the Dialog component. */
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  })
}
