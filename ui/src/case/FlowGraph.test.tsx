import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CaseContext, CaseDetail } from '../api/models'
import { readCase, readMock } from '../test/files'
import { bigCase, fanCase } from '../../scripts/big-graph.mjs'
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
    options: {} as Record<string, unknown>,
    placed: [] as [string, { x: number; y: number }][],
    hidden: [] as string[],
  }
  const collection = (id = '') => {
    const c = {
      remove: () => c,
      removeClass: () => c,
      addClass: () => c,
      forEach: (fn?: (el: unknown) => void) => {
        // every element last handed over, so that the component's class passes can be seen
        if (fn && id === '*')
          for (const e of state.added.at(-1) ?? [])
            fn({ id: () => e.data.id, data: (key: string) => (e.data as Record<string, unknown>)[key], addClass: (name: string) => name === 'ahead' && state.hidden.push(e.data.id) })
        return c
      },
      nonempty: () => id !== '',
      position: (at?: { x: number; y: number }) => {
        if (at) state.placed.push([id, at])
        return at ? c : { x: 0, y: 0 }
      },
      data: () => '',
      source: () => c,
      target: () => c,
      style: () => c,
      animate: () => c,
      stop: () => c,
      removeStyle: () => c,
    }
    return c
  }
  const cy = {
    on: (event: string, a: string | Handler, b?: Handler) => {
      state.handlers.push(typeof a === 'string' ? { event, selector: a, handler: b! } : { event, handler: a })
      return cy
    },
    batch: (fn: () => void) => fn(),
    elements: () => collection('*'),
    nodes: () => collection(),
    getElementById: (id: string) => collection(id),
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

vi.mock('cytoscape', () => ({ default: (options: Record<string, unknown>) => ((fake.state.options = options), fake.cy) }))
// The 3D view draws with WebGL, which jsdom has not: what it is asked to draw is checked here,
// how it draws it in flowSpace.test.ts and in a real browser (scripts/graph-shots.mjs).
const space = vi.hoisted(() => ({ props: [] as Record<string, unknown>[], reset: vi.fn(), zoom: vi.fn() }))
vi.mock('./Flow3D', () => ({
  default: (props: Record<string, unknown> & { ref?: { current: unknown } }) => {
    space.props.push(props)
    if (props.ref) props.ref.current = { reset: space.reset, zoom: space.zoom }
    return <div data-testid="flow-3d" />
  },
}))
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
  fake.state.placed.length = 0
  fake.state.hidden.length = 0
  space.props.length = 0
  space.reset.mockClear()
  space.zoom.mockClear()
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

describe('FlowGraph: dragging', () => {
  it('lets a wallet be dragged, and a drag is not a click', () => {
    const onSelect = vi.fn()
    render(<FlowGraph c={hero} selected={null} onSelect={onSelect} />)
    expect(fake.state.options.autoungrabify).toBe(false)
    const id = hero.graph.nodes[1].id
    fire('grab', 'node', element(id))
    fire('dragfree', 'node', element(id, { position: () => ({ x: 400, y: -120 }) }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('keeps a dragged wallet where it was put when the picture is drawn again, without refitting', async () => {
    const { rerender } = render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const id = hero.graph.nodes[1].id
    fire('dragfree', 'node', element(id, { position: () => ({ x: 400, y: -120 }) }))
    fake.state.calls.length = 0
    fake.state.placed.length = 0
    // the theme changes, a selection is made: the same case is handed over again
    rerender(<FlowGraph c={{ ...hero }} selected={id} onSelect={() => {}} />)
    expect(fake.state.placed).toContainEqual([id, { x: 400, y: -120 }])
    expect(fake.state.calls).not.toContain('fit')
  })

  it('moves the name over a wallet with the wallet', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    fake.state.placed.length = 0
    fire('position', 'node', element('TXYZ', { position: () => ({ x: 50, y: 100 }), data: (key: string) => (key === 'side' ? 36 : undefined) }))
    expect(fake.state.placed).toEqual([['caption:TXYZ', { x: 50, y: 100 - 18 - 9 }]])
    // a caption moving does not move anything else
    fake.state.placed.length = 0
    fire('position', 'node', element('caption:TXYZ', { position: () => ({ x: 0, y: 0 }) }))
    expect(fake.state.placed).toEqual([])
  })

  it('puts every wallet back on Reset layout', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const id = hero.graph.nodes[1].id
    fire('dragfree', 'node', element(id, { position: () => ({ x: 400, y: -120 }) }))
    fake.state.placed.length = 0
    fake.state.calls.length = 0
    await userEvent.click(screen.getByRole('button', { name: 'Reset layout' }))
    const back = fake.state.placed.find(([at]) => at === id)!
    expect(back[1]).not.toEqual({ x: 400, y: -120 })
    expect(fake.state.calls).toContain('fit')
  })
})

describe('FlowGraph: replay the money', () => {
  const replay = () => screen.getByRole('group', { name: 'Replay the money' })
  const nowText = () => screen.getByTestId('replay-now').textContent
  const total = () => Number(within(replay()).getByRole('slider').getAttribute('max'))

  it('starts complete: every transfer drawn, nothing hidden', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const slider = within(replay()).getByRole('slider', { name: 'Transfers drawn, in time order' })
    expect(Number((slider as HTMLInputElement).value)).toBe(total())
    expect(fake.state.hidden).toEqual([])
    expect(nowText()).toContain(`Transfer ${total()} of ${total()}`)
  })

  it('steps back and forward one transfer at a time, hiding what has not moved yet', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const n = total()
    await userEvent.click(within(replay()).getByRole('button', { name: 'Previous transfer' }))
    expect(nowText()).toContain(`Transfer ${n - 1} of ${n}`)
    expect(fake.state.hidden.length).toBeGreaterThan(0)
    await userEvent.click(within(replay()).getByRole('button', { name: 'Next transfer' }))
    expect(nowText()).toContain(`Transfer ${n} of ${n}`)
    expect(within(replay()).getByRole('button', { name: 'Next transfer' })).toBeDisabled()
  })

  it('plays from the start to the end and stops there, on the real amounts', () => {
    vi.useFakeTimers()
    try {
      render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
      const n = total()
      act(() => within(replay()).getByRole('button', { name: /^Play/ }).click())
      expect(nowText()).toContain(`Before the first of ${n} transfers`)
      expect(within(replay()).getByRole('button', { name: 'Pause the replay' })).toBeInTheDocument()
      for (let i = 0; i < n + 2; i++) act(() => void vi.advanceTimersByTime(800))
      expect(nowText()).toContain(`Transfer ${n} of ${n}`)
      expect(within(replay()).getByRole('button', { name: /^Play/ })).toBeInTheDocument()
      // every amount the replay says is one a drawn edge carries
      expect(within(replay()).getByRole('slider').getAttribute('aria-valuetext')).toMatch(new RegExp(`^Transfer ${n} of ${n}: `))
    } finally {
      vi.useRealTimers()
    }
  })

  it('answers to the keyboard: space plays and pauses, arrows step', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const n = total()
    const slider = within(replay()).getByRole('slider')
    slider.focus()
    await userEvent.keyboard(' ')
    expect(within(replay()).getByRole('button', { name: 'Pause the replay' })).toBeInTheDocument()
    await userEvent.keyboard(' ')
    expect(within(replay()).getByRole('button', { name: /^Play/ })).toBeInTheDocument()
    within(replay()).getByRole('button', { name: 'Next transfer' }).focus()
    await userEvent.keyboard('{ArrowRight}{ArrowRight}')
    expect(nowText()).toContain(`Transfer 2 of ${n}`)
    await userEvent.keyboard('{ArrowLeft}')
    expect(nowText()).toContain(`Transfer 1 of ${n}`)
  })

  it('with reduced motion, is a step-by-step control: no play, nothing animated', async () => {
    const animate = vi.fn()
    const original = fake.cy.getElementById
    fake.cy.getElementById = ((id: string) => ({ ...original(id), animate })) as typeof original
    const media = vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({ matches: query.includes('reduced-motion'), media: query, addEventListener: () => {}, removeEventListener: () => {} }) as unknown as MediaQueryList)
    try {
      render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
      const n = total()
      expect(within(replay()).queryByRole('button', { name: /^Play/ })).not.toBeInTheDocument()
      await userEvent.click(within(replay()).getByRole('button', { name: 'Previous transfer' }))
      await userEvent.click(within(replay()).getByRole('button', { name: 'Next transfer' }))
      expect(nowText()).toContain(`Transfer ${n} of ${n}`)
      expect(animate).not.toHaveBeenCalled()
    } finally {
      media.mockRestore()
      fake.cy.getElementById = original
    }
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
    expect(note).toHaveTextContent('Every wallet and transfer is in the tabs below')
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

  it('draws as far as a selected wallet that sits past the hops drawn, and does not refit for a selection', () => {
    const deep = big.graph.nodes.filter((n) => n.hop === 4).at(-1)!.id
    const { rerender } = render(<FlowGraph c={big} selected={null} onSelect={() => {}} />)
    const fits = fake.state.calls.filter((x) => x === 'fit').length
    rerender(<FlowGraph c={big} selected={deep} onSelect={() => {}} />)
    expect(walletsDrawn().some((e) => e.data.id === deep)).toBe(true)
    expect(fake.state.calls.filter((x) => x === 'fit').length).toBe(fits)
  })

  it('leaves a small case exactly as it was: no note, every wallet drawn', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    expect(screen.queryByRole('group', { name: 'Parts of the graph not drawn' })).not.toBeInTheDocument()
  })
})

describe('FlowGraph: a fan of payers (a synthetic shape of 10)', () => {
  const ten = fanCase(10)
  const fan = `fan:in:${ten.address}`
  const drawn = () => fake.state.added.at(-1)!.map((e) => e.data.id).filter((id) => /^p\d+$/.test(id))

  it('draws four payers and one group, and says so in the legend', () => {
    render(<FlowGraph c={ten} selected={null} onSelect={() => {}} />)
    expect(drawn()).toHaveLength(4)
    expect(fake.state.added.at(-1)!.some((e) => e.data.id === fan)).toBe(true)
    expect(within(screen.getByRole('group', { name: 'How to read the graph' })).getByText(/Several small wallets drawn as one/)).toBeInTheDocument()
  })

  it('opens the group in place on a click, without selecting anything, and Collapse closes it', async () => {
    const onSelect = vi.fn()
    render(<FlowGraph c={ten} selected={null} onSelect={onSelect} />)
    fire('tap', 'node', element(fan))
    expect(onSelect).not.toHaveBeenCalled()
    expect(drawn()).toHaveLength(10)
    expect(fake.state.added.at(-1)!.some((e) => e.data.id === fan)).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Collapse the wallets that paid the suspect wallet' }))
    expect(drawn()).toHaveLength(4)
    expect(screen.queryByRole('button', { name: /^Collapse the wallets/ })).not.toBeInTheDocument()
  })

  it('counts every wallet for a screen reader, grouped or not', () => {
    render(<FlowGraph c={ten} selected={null} onSelect={() => {}} />)
    expect(screen.getByRole('img', { name: new RegExp(`${ten.graph.nodes.length} wallets and ${ten.graph.edges.length} transfers`) })).toBeInTheDocument()
  })
})

describe('FlowGraph: what the trace saw', () => {
  it('says how much was seen and followed, and why the rest was not, in the trace\u2019s own figures', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    const line = screen.getByTestId('trace-summary')
    expect(line).toHaveTextContent('Followed 8 of 160 transfers seen. 13 wallets not followed: 8 below the dust limit, 1 high-activity hub, 2 already labelled (the trail ends there), 2 at the hop limit.')
    expect(line.textContent!.replace(/\s+/g, ' ')).toContain(hero.trace_summary!.text)
  })

  it('lists the wallets of a reason, and shows one that is on the graph when it is chosen', async () => {
    const onSelect = vi.fn()
    render(<FlowGraph c={hero} selected={null} onSelect={onSelect} />)
    const hub = screen.getByRole('button', { name: '1 high-activity hub' })
    expect(hub).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(hub)
    expect(hub).toHaveAttribute('aria-expanded', 'true')
    const wallet = hero.trace_summary!.not_followed.find((r) => r.reason === 'hub')!.wallet_ids[0]
    await userEvent.click(within(screen.getByTestId('trace-summary')).getByRole('button', { name: new RegExp(`^Show ${wallet.slice(0, 6)}.* in the graph$`) }))
    expect(onSelect).toHaveBeenLastCalledWith(wallet)
    // a wallet under the dust limit is not on the graph: it is listed, and cannot be shown there
    await userEvent.click(screen.getByRole('button', { name: '8 below the dust limit' }))
    expect(within(screen.getByTestId('trace-summary')).queryByRole('button', { name: /in the graph$/ })).not.toBeInTheDocument()
    expect(screen.getByText(/No traced money reached them/)).toBeInTheDocument()
  })

  it('says nothing for a case stored before this was counted', () => {
    render(<FlowGraph c={{ ...hero, trace_summary: null }} selected={null} onSelect={() => {}} />)
    expect(screen.queryByTestId('trace-summary')).not.toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: /Show all context/ })).not.toBeInTheDocument()
  })
})

describe('FlowGraph: context on demand (a recorded case and its recorded context)', () => {
  const context = readCase<CaseContext>('tron-coindcx.context')
  const drawn = () => fake.state.added.at(-1)! as unknown as { data: { id: string; context?: number } }[]
  const contextDrawn = () => drawn().filter((e) => e.data.context)
  const trailDrawn = () => drawn().filter((e) => !e.data.context).map((e) => e.data.id)
  const all = () => vi.fn(async () => context)

  it('is off by default, and the switch says what it would add', () => {
    const load = all()
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} loadContext={load} />)
    const toggle = screen.getByRole('switch', { name: 'Show all context (adds 152 transfers)' })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(contextDrawn()).toHaveLength(0)
    expect(load).not.toHaveBeenCalled()
  })

  it('draws the context greyed when switched on, names it in the legend, and leaves the trail as it was', async () => {
    const load = all()
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} loadContext={load} />)
    const trail = trailDrawn()
    await userEvent.click(screen.getByRole('switch', { name: /Show all context/ }))
    expect(load).toHaveBeenCalledWith(hero.id, null)
    expect(await screen.findByText(/152 other transfers of the 3 wallets this trace read/)).toBeInTheDocument()
    expect(contextDrawn().length).toBeGreaterThan(10)
    expect(trailDrawn()).toEqual(trail)
    expect(screen.getByRole('switch', { name: 'Show all context' })).toHaveAttribute('aria-checked', 'true')
    expect(within(screen.getByRole('group', { name: 'How to read the graph' })).getByText('Other transfers (context, not the suspect\u2019s money)'.replace('\u2019', "'"))).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /7 wallets and 8 transfers.*other transfers are drawn greyed as context/ })).toBeInTheDocument()
  })

  it('goes back to exactly the default view on Hide context', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} loadContext={all()} />)
    const before = JSON.stringify(drawn())
    await userEvent.click(screen.getByRole('switch', { name: /Show all context/ }))
    await screen.findByText(/152 other transfers/)
    await userEvent.click(screen.getByRole('button', { name: 'Hide context' }))
    expect(JSON.stringify(drawn())).toBe(before)
    expect(screen.queryByRole('button', { name: 'Hide context' })).not.toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Show all context (adds 152 transfers)' })).toHaveAttribute('aria-checked', 'false')
  })

  it('replays the suspect\u2019s money only, with context on', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} loadContext={all()} />)
    const before = screen.getByTestId('replay-now').textContent
    await userEvent.click(screen.getByRole('switch', { name: /Show all context/ }))
    await screen.findByText(/152 other transfers/)
    expect(screen.getByTestId('replay-now').textContent).toBe(before)
    expect(screen.getByRole('slider', { name: 'Transfers drawn, in time order' })).toHaveAttribute('max', '6')
  })

  it('opens one wallet\u2019s other transfers from the wallet that is selected', async () => {
    const mine = { ...context, wallet: hero.address, edges: context.edges.filter((e) => e.source === hero.address || e.target === hero.address) }
    const load = vi.fn(async () => mine)
    render(<FlowGraph c={hero} selected={hero.address} onSelect={() => {}} loadContext={load} />)
    await userEvent.click(screen.getByRole('button', { name: 'Show this wallet\u2019s other transfers' }))
    expect(load).toHaveBeenCalledWith(hero.id, hero.address)
    expect(await screen.findByRole('button', { name: 'Hide this wallet\u2019s other transfers' })).toHaveAttribute('aria-pressed', 'true')
    expect(contextDrawn().length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: 'Hide this wallet\u2019s other transfers' }))
    expect(contextDrawn()).toHaveLength(0)
  })

  it('does not offer a wallet\u2019s other transfers for a group of wallets', () => {
    render(<FlowGraph c={okx} selected="cluster:OKX" onSelect={() => {}} loadContext={all()} />)
    expect(screen.queryByRole('button', { name: /this wallet\u2019s other transfers/ })).not.toBeInTheDocument()
  })

  it('says so when a wallet was not recorded, and draws nothing', async () => {
    const reason = 'This wallet\u2019s other transfers were not recorded with the case: the trace did not read it. Online, they are read from the chain.'
    const load = vi.fn(async (): Promise<CaseContext> => ({ case_id: hero.id, wallet: hero.graph.nodes[1].id, recorded: false, live: false, reason, transfers: 0, truncated: false, nodes: [], edges: [], text: reason }))
    render(<FlowGraph c={hero} selected={hero.graph.nodes[1].id} onSelect={() => {}} loadContext={load} />)
    await userEvent.click(screen.getByRole('button', { name: 'Show this wallet\u2019s other transfers' }))
    expect(await screen.findByRole('status')).toHaveTextContent(reason)
    expect(contextDrawn()).toHaveLength(0)
  })

  it('shows the reason when the context cannot be read', async () => {
    const load = vi.fn(async () => Promise.reject(new Error('The chain responses this case was traced from are no longer in the cache.')))
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} loadContext={load} />)
    await userEvent.click(screen.getByRole('switch', { name: /Show all context/ }))
    expect(await screen.findByRole('status')).toHaveTextContent('no longer in the cache')
  })

  it('draws more of a wallet\u2019s context on a click on its group, and names a context wallet on a click, selecting nothing', async () => {
    const onSelect = vi.fn()
    render(<FlowGraph c={hero} selected={null} onSelect={onSelect} loadContext={all()} />)
    await userEvent.click(screen.getByRole('switch', { name: /Show all context/ }))
    await screen.findByText(/152 other transfers/)
    const group = contextDrawn().find((e) => e.data.id.startsWith('ctxmore:'))!
    const before = contextDrawn().length
    fire('tap', 'node', element(group.data.id))
    expect(contextDrawn().length).toBeGreaterThan(before)
    const toggled = vi.fn()
    const other = contextDrawn().find((e) => !e.data.id.includes('>') && !e.data.id.startsWith('ctxmore:'))!
    fire('tap', 'node', element(other.data.id, { data: (key: string) => (key === 'context' ? 1 : undefined), toggleClass: toggled }))
    expect(toggled).toHaveBeenCalledWith('named')
    expect(onSelect).not.toHaveBeenCalled()
  })
})

describe('FlowGraph: the optional 3D view', () => {
  const choose3d = async () => {
    await userEvent.click(screen.getByRole('radio', { name: '3D' }))
    return screen.findByTestId('flow-3d')
  }

  it('opens in 2D, with 3D one choice away', () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    expect(screen.getByRole('radio', { name: '2D' })).toBeChecked()
    expect(screen.getByRole('radio', { name: '3D' })).not.toBeChecked()
    expect(screen.queryByTestId('flow-3d')).not.toBeInTheDocument()
    expect(space.props).toHaveLength(0)
  })

  it('shows the same wallets and transfers in 3D as the 2D canvas was given', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    await choose3d()
    const given = space.props.at(-1)!
    expect((given.elements as { data: { id: string } }[]).map((e) => e.data.id)).toEqual(fake.state.added.at(-1)!.map((e) => e.data.id))
    expect(screen.getByRole('img', { hidden: true })).toHaveClass('hidden')
  })

  it('says 3D is a visual aid, and takes away what belongs to the 2D picture', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    await choose3d()
    expect(screen.getByTestId('note-3d')).toHaveTextContent('3D is a visual aid')
    expect(screen.getByTestId('note-3d')).toHaveTextContent('pictures for the file come from the 2D view')
    expect(screen.getByRole('button', { name: 'Export PNG' })).toBeDisabled()
    expect(screen.queryByRole('group', { name: 'Replay the money' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reset layout' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: '2D' }))
    expect(screen.queryByTestId('flow-3d')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export PNG' })).toBeEnabled()
    expect(screen.getByRole('group', { name: 'Replay the money' })).toBeInTheDocument()
  })

  it('selects in both views at once: a click in 3D selects, and the selection is marked there', async () => {
    const onSelect = vi.fn()
    const deposit = hero.graph.nodes[1].id
    const { rerender } = render(<FlowGraph c={hero} selected={null} onSelect={onSelect} />)
    await choose3d()
    act(() => (space.props.at(-1)!.onTap as (id: string | null, context: boolean) => void)(deposit, false))
    expect(onSelect).toHaveBeenLastCalledWith(deposit)
    rerender(<FlowGraph c={hero} selected={deposit} onSelect={onSelect} />)
    expect(space.props.at(-1)!.shown).toBe(deposit)
    act(() => (space.props.at(-1)!.onTap as (id: string | null, context: boolean) => void)(null, false))
    expect(onSelect).toHaveBeenLastCalledWith(null)
  })

  it('has Reset view and zoom on buttons', async () => {
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    await choose3d()
    await userEvent.click(screen.getByRole('button', { name: 'Reset view' }))
    expect(space.reset).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    await userEvent.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(space.zoom.mock.calls.map((c) => c[0] < 1)).toEqual([true, false])
  })

  it('opens a fan from 3D as a click in 2D does', async () => {
    const ten = fanCase(10)
    render(<FlowGraph c={ten} selected={null} onSelect={() => {}} />)
    await choose3d()
    act(() => (space.props.at(-1)!.onTap as (id: string | null, context: boolean) => void)(`fan:in:${ten.address}`, false))
    expect((space.props.at(-1)!.elements as { data: { id: string } }[]).filter((e) => /^p\d+$/.test(e.data.id))).toHaveLength(10)
  })

  it('tells the 3D view to hold still under reduced motion', async () => {
    vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({ matches: query.includes('reduce'), media: query, addEventListener: () => {}, removeEventListener: () => {} }) as unknown as MediaQueryList)
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    await choose3d()
    expect(space.props.at(-1)!.still).toBe(true)
  })

  it('is switched off, with the reason, where the browser has no WebGL', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((kind: string) => (kind === '2d' ? {} : null)) as never)
    render(<FlowGraph c={hero} selected={null} onSelect={() => {}} />)
    expect(screen.getByRole('radio', { name: '3D' })).toBeDisabled()
    expect(screen.getByText(/The 3D view needs WebGL, which this browser does not offer here/)).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '2D' })).toBeChecked()
  })
})
