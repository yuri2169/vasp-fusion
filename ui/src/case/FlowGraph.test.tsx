import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CaseDetail } from '../api/models'
import { readCase, readMock } from '../test/files'
import { bigCase } from '../../scripts/big-graph.mjs'
import { FlowGraph } from './FlowGraph'

/** jsdom has no canvas, so Cytoscape itself is stood in for here: the test checks what the
 *  component asks of it. That Cytoscape accepts the elements and the stylesheet is checked
 *  with the real library in flowStyle.test.ts; how it looks is checked in the browser. */
const fake = vi.hoisted(() => {
  type Handler = (event: { target: unknown }) => void
  const state = {
    handlers: [] as { event: string; selector?: string; handler: Handler }[],
    added: [] as { data: { id: string } }[][],
    calls: [] as string[],
  }
  const collection = () => {
    const c = {
      remove: () => c,
      removeClass: () => c,
      addClass: () => c,
      forEach: () => c,
      nonempty: () => false,
    }
    return c
  }
  const cy = {
    on: (event: string, a: string | Handler, b?: Handler) => {
      state.handlers.push(typeof a === 'string' ? { event, selector: a, handler: b! } : { event, handler: a })
      return cy
    },
    batch: (fn: () => void) => fn(),
    elements: collection,
    nodes: collection,
    getElementById: collection,
    add: (elements: { data: { id: string } }[]) => {
      state.added.push(elements)
    },
    style: () => state.calls.push('style'),
    fit: () => state.calls.push('fit'),
    zoom: (level?: unknown) => (level === undefined ? 1 : (state.calls.push('zoom'), cy)),
    center: () => state.calls.push('center'),
    resize: () => state.calls.push('resize'),
    width: () => 800,
    height: () => 500,
    png: () => (state.calls.push('png'), 'data:image/png;base64,AAAA'),
    destroy: () => state.calls.push('destroy'),
  }
  return { state, cy }
})

vi.mock('cytoscape', () => ({ default: () => fake.cy }))
const downloads = vi.hoisted(() => ({ url: vi.fn(), text: vi.fn() }))
vi.mock('../lib/download', () => ({ downloadUrl: downloads.url, downloadText: downloads.text }))

const hero = readCase<CaseDetail>('tron-coindcx')
const okx = readMock<CaseDetail>('cases/demo-tron-okx.json')

const fire = (event: string, selector: string | undefined, target: unknown) =>
  act(() => fake.state.handlers.filter((h) => h.event === event && h.selector === selector).forEach((h) => h.handler({ target })))
const element = (id: string, extra: Record<string, unknown> = {}) => ({
  id: () => id,
  data: (key: string) => (key === 'id' ? id : undefined),
  addClass: () => {},
  removeClass: () => {},
  renderedPosition: () => ({ x: 10, y: 10 }),
  renderedBoundingBox: () => ({ x1: 0, y1: 0, x2: 20, y2: 20 }),
  ...extra,
})

beforeEach(() => {
  fake.state.handlers.length = 0
  fake.state.added.length = 0
  fake.state.calls.length = 0
  downloads.url.mockClear()
  downloads.text.mockClear()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as never)
})

describe('FlowGraph', () => {
  it('hands Cytoscape one element per wallet, per caption and per pair of wallets', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const ids = fake.state.added.at(-1)!.map((e) => e.data.id)
    expect(ids.filter((id) => !id.startsWith('caption:') && !id.includes('>'))).toHaveLength(hero.graph.nodes.length)
    expect(ids.filter((id) => id.includes('>'))).toHaveLength(6)
  })

  it('describes itself to a screen reader and points to the Wallets tab', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    expect(screen.getByRole('img', { name: /7 wallets and 8 transfers.*Wallets tab/ })).toBeInTheDocument()
  })

  it('selects the wallet that is clicked, and nothing when the background is', () => {
    const onSelect = vi.fn()
    render(<FlowGraph c={hero} selected={null} onSelect={onSelect} />)
    const deposit = hero.graph.nodes[1].id
    fire('tap', 'node', element(deposit))
    expect(onSelect).toHaveBeenLastCalledWith(deposit)
    fire('tap', undefined, fake.cy)
    expect(onSelect).toHaveBeenLastCalledWith(null)
  })

  it('fits the picture, and the main path, on request', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const fits = () => fake.state.calls.filter((c) => c === 'fit').length
    const before = fits()
    await userEvent.click(screen.getByRole('button', { name: 'Fit' }))
    await userEvent.click(screen.getByRole('button', { name: 'Focus path' }))
    expect(fits()).toBe(before + 2)
  })

  it('offers to group exchange wallets only when an exchange has several here', async () => {
    const { unmount } = render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    expect(screen.queryByRole('button', { name: /Group exchange wallets/ })).not.toBeInTheDocument()
    unmount()

    render(<FlowGraph c={okx} selected={null} onSelect={() => {}} />)
    const group = screen.getByRole('button', { name: 'Group exchange wallets' })
    expect(group).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(group)
    expect(group).toHaveAttribute('aria-pressed', 'true')
    expect(fake.state.added.at(-1)!.map((e) => e.data.id)).toContain('cluster:OKX')
  })

  it('exports the picture as a PNG and the graph as GraphML, named after the case', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Export PNG' }))
    expect(downloads.url).toHaveBeenCalledWith('case-tron-coindcx-graph.png', 'data:image/png;base64,AAAA')
    await userEvent.click(screen.getByRole('button', { name: 'Export GraphML' }))
    expect(downloads.text).toHaveBeenCalledWith('case-tron-coindcx.graphml', expect.stringContaining('<graphml'), 'application/graphml+xml')
  })

  it('shows what a transfer carried when it is pointed at', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const funder = hero.graph.edges.find((e) => e.direction === 'inbound' && e.amount === 941)!
    fire('mouseover', 'edge', element(`${funder.source}>${hero.address}`, { renderedMidpoint: () => ({ x: 10, y: 10 }) }))
    const card = screen.getByRole('tooltip')
    expect(card).toHaveTextContent('3 transfers')
    expect(card).toHaveTextContent('2,332 USDT')
    expect(card).toHaveTextContent(funder.tx_hash)
    fire('mouseout', 'edge', element('x'))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('shows whose wallet it is when a wallet is pointed at', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const deposit = hero.graph.nodes[1].id
    fire('mouseover', 'node', element(deposit))
    const card = screen.getByRole('tooltip')
    expect(card).toHaveTextContent(deposit)
    expect(card).toHaveTextContent('CoinDCX')
    expect(card).toHaveTextContent('Deposit address')
    expect(card).toHaveTextContent('Derived by VASP-FUSION')
  })

  it('says where the same content is when the browser cannot draw', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    expect(screen.getByText(/cannot draw the graph\. The Wallets and Transfers tabs list everything/)).toBeInTheDocument()
    expect(fake.state.added).toHaveLength(0)
  })

  it('explains its shapes and borders in words', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const legend = screen.getByRole('group', { name: 'How to read the graph' })
    for (const words of ['Suspect wallet', 'Deposit address', 'Exchange wallet', 'Busy wallet, where the trail stops', 'Derived by VASP-FUSION', 'Curated list', 'Unlabelled'])
      expect(within(legend).getByText(words)).toBeInTheDocument()
    expect(within(legend).getByText(/CoinDCX, the exchange this case names/)).toBeInTheDocument()
    // not in this case, so not in its legend
    expect(within(legend).queryByText('Mixer')).not.toBeInTheDocument()
  })
})

describe('FlowGraph on a large graph (2,000 wallets, a synthetic shape)', () => {
  const big = bigCase(2000)
  const walletsDrawn = () => fake.state.added.at(-1)!.filter((e) => !e.data.id.startsWith('caption:') && !e.data.id.includes('>') && !e.data.id.startsWith('more:'))

  it('draws a bounded part, says how much, and where the rest is', () => {
    render(<FlowGraph c={big} selected={null} onSelect={() => {}} />)
    expect(fake.state.added.at(-1)!.length).toBeLessThan(400)
    const note = screen.getByRole('group', { name: 'Parts of the graph not drawn' })
    expect(note).toHaveTextContent(new RegExp(`Drawing ${walletsDrawn().length} wallets of 2,000`))
    expect(note).toHaveTextContent('Every wallet is in the Wallets tab')
    expect(screen.getByRole('img', { name: /of 2000 wallets drawn.*Wallets tab/ })).toBeInTheDocument()
  })

  it('draws the next hop, and more of one hop, when asked by button or by a click on the fold', async () => {
    const onSelect = vi.fn()
    render(<FlowGraph c={big} selected={null} onSelect={onSelect} />)
    const before = walletsDrawn().length
    await userEvent.click(screen.getByRole('button', { name: /^Draw 50 more of hop 2/ }))
    expect(walletsDrawn().length).toBe(before + 50)
    fire('tap', 'node', element('more:2'))
    expect(walletsDrawn().length).toBe(before + 100)
    expect(onSelect).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /^Draw hop 3/ }))
    expect(fake.state.added.at(-1)!.some((e) => e.data.id === 'more:3')).toBe(true)
    expect(screen.getByRole('button', { name: /^Draw hop 4/ })).toBeInTheDocument()
  })

  it('draws a wallet that is selected from the Wallets tab, however small', () => {
    const last = big.graph.nodes.filter((n) => n.hop === 2).at(-1)!.id
    const { rerender } = render(<FlowGraph c={big} selected={null} onSelect={() => {}} />)
    expect(walletsDrawn().some((e) => e.data.id === last)).toBe(false)
    rerender(<FlowGraph c={big} selected={last} onSelect={() => {}} />)
    expect(walletsDrawn().some((e) => e.data.id === last)).toBe(true)
  })

  it('leaves a small case exactly as it was: no note, every wallet drawn', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    expect(screen.queryByRole('group', { name: 'Parts of the graph not drawn' })).not.toBeInTheDocument()
  })
})
