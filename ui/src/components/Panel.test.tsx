import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setMedia } from '../test/setup'
import { Bar, Counter, Frame, Panel } from './Panel'

afterEach(() => vi.useRealTimers())

describe('Panel', () => {
  it('draws one frame: a panel inside a panel is filled, not bordered again', () => {
    render(
      <Panel weight="primary" aria-label="outer">
        <Panel aria-label="inner">leaf</Panel>
      </Panel>,
    )
    expect(screen.getByRole('region', { name: 'outer' })).toHaveClass('panel-primary')
    expect(screen.getByRole('region', { name: 'inner' })).toHaveClass('panel-sub')
    expect(screen.getByRole('region', { name: 'inner' })).not.toHaveClass('panel')
  })

  it('goes flat inside a hand-drawn frame too', () => {
    render(
      <Frame>
        <Panel aria-label="inner">leaf</Panel>
      </Frame>,
    )
    expect(screen.getByRole('region', { name: 'inner' })).toHaveClass('panel-sub')
  })

  it('has three weights and no more', () => {
    render(
      <>
        <Panel aria-label="a">a</Panel>
        <Panel weight="primary" aria-label="b">b</Panel>
        <Panel weight="sub" aria-label="c">c</Panel>
      </>,
    )
    expect(screen.getByRole('region', { name: 'a' })).toHaveClass('panel')
    expect(screen.getByRole('region', { name: 'b' })).toHaveClass('panel-primary')
    expect(screen.getByRole('region', { name: 'c' })).toHaveClass('panel-sub')
  })
})

describe('Bar', () => {
  it('is as long as its share of the maximum, and never longer than the track', () => {
    const { container, rerender } = render(<Bar value={3} max={12} label="3 of 12" />)
    expect(screen.getByRole('img', { name: '3 of 12' })).toBeInTheDocument()
    expect((container.querySelector('.anim-bar') as HTMLElement).style.width).toBe('25%')
    rerender(<Bar value={40} max={12} label="40 of 12" />)
    expect((container.querySelector('.anim-bar') as HTMLElement).style.width).toBe('100%')
  })
})

describe('Counter', () => {
  it('lands on its value even when no frame is ever drawn (a hidden tab)', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestAnimationFrame', () => 0) // frames never fire
    render(<Counter value={1614} />)
    expect(screen.getByTestId('counter')).toHaveTextContent('0')
    act(() => void vi.advanceTimersByTime(800))
    expect(screen.getByTestId('counter')).toHaveTextContent('1,614')
    vi.unstubAllGlobals()
  })

  it('shows the value at once under reduced motion', () => {
    setMedia('(prefers-reduced-motion: reduce)')
    render(<Counter value={0.85} format={(n) => n.toFixed(2)} />)
    expect(screen.getByTestId('counter')).toHaveTextContent('0.85')
  })
})
