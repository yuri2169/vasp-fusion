import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DualMeter } from './DualMeter'
import { OutcomeStamp } from './OutcomeStamp'

// Figures are the fixtures' (mocks/cases/*.json): OKX 0.91 with a range, HTX 0.46, ChangeNOW 0.34.

describe('OutcomeStamp', () => {
  it('ATTRIBUTED names the exchange, in saffron, with the confidence and its range', () => {
    render(<OutcomeStamp outcome="ATTRIBUTED" vasp="OKX" confidence={0.91} interval={[0.84, 0.95]} size="lg" />)
    const stamp = screen.getByTestId('outcome-stamp')
    expect(stamp).toHaveAttribute('data-outcome', 'ATTRIBUTED')
    expect(stamp).toHaveClass('bg-saffron', 'text-saffron-on')
    expect(stamp).toHaveTextContent('Attributed')
    expect(stamp).toHaveTextContent('OKX')
    expect(stamp).toHaveTextContent('confidence 0.91')
    expect(stamp).toHaveTextContent('range 0.84 to 0.95')
  })

  it('says "rule confidence" when there is no range (the label was not scored by the model)', () => {
    render(<OutcomeStamp outcome="ATTRIBUTED" vasp="HTX" confidence={0.71} interval={null} size="lg" />)
    expect(screen.getByTestId('outcome-stamp')).toHaveTextContent('rule confidence 0.71')
  })

  it('never prints certainty', () => {
    render(<OutcomeStamp outcome="ATTRIBUTED" vasp="OKX" confidence={0.9993} interval={[0.998, 0.9999]} size="lg" />)
    const stamp = screen.getByTestId('outcome-stamp')
    expect(stamp).toHaveTextContent('confidence over 0.99')
    expect(stamp).toHaveTextContent('range narrower than 0.01')
    expect(stamp).not.toHaveTextContent('1.00')
  })

  it('INSUFFICIENT EVIDENCE is slate and dashed, names no exchange, and says what would change it', () => {
    render(
      <OutcomeStamp
        outcome="INSUFFICIENT_EVIDENCE"
        size="lg"
        whatWouldChange="A deposit-address link (sweep or gas payer) from the last hop to a named exchange wallet"
      />,
    )
    const stamp = screen.getByTestId('outcome-stamp')
    expect(stamp).toHaveClass('stamp-dashed', 'text-muted')
    expect(stamp).not.toHaveClass('bg-saffron')
    expect(stamp).toHaveTextContent('Insufficient evidence')
    expect(stamp).toHaveTextContent('No exchange named')
    expect(screen.getByText(/What would change this:/).closest('p')).toHaveTextContent(
      'What would change this: A deposit-address link (sweep or gas payer) from the last hop to a named exchange wallet',
    )
  })

  it('SANCTIONED OR MIXER REACHED is seal red, and still names the nearest exchange when there is one', () => {
    render(<OutcomeStamp outcome="SANCTIONED_OR_MIXER_REACHED" vasp="CoinDCX" confidence={0.58} interval={[0.4, 0.74]} size="lg" />)
    const stamp = screen.getByTestId('outcome-stamp')
    expect(stamp).toHaveClass('bg-seal', 'text-seal-on')
    expect(stamp).toHaveTextContent('Sanctioned or mixer reached')
    expect(stamp).toHaveTextContent('Nearest exchange: CoinDCX')
  })

  it('a case still being traced says so, and a failed one says that', () => {
    const { rerender } = render(<OutcomeStamp outcome={null} status="running" />)
    expect(screen.getByTestId('outcome-stamp')).toHaveTextContent('Tracing…')
    rerender(<OutcomeStamp outcome={null} status="queued" />)
    expect(screen.getByTestId('outcome-stamp')).toHaveTextContent('Tracing…')
    rerender(<OutcomeStamp outcome={null} status="failed" />)
    expect(screen.getByTestId('outcome-stamp')).toHaveTextContent('Trace failed')
  })

  it('the small stamp is one flat line for a table row', () => {
    render(<OutcomeStamp outcome="ATTRIBUTED" vasp="OKX" confidence={0.91} size="sm" />)
    const stamp = screen.getByTestId('outcome-stamp')
    expect(stamp).toHaveTextContent('Attributed')
    expect(stamp).toHaveTextContent('OKX')
    expect(stamp).not.toHaveClass('stamp-tilt')
  })

  it('only tilts when asked (the Hop Rail asks)', () => {
    const { rerender } = render(<OutcomeStamp outcome="ATTRIBUTED" vasp="OKX" confidence={0.91} size="lg" />)
    expect(screen.getByTestId('outcome-stamp')).not.toHaveClass('stamp-tilt')
    rerender(<OutcomeStamp outcome="ATTRIBUTED" vasp="OKX" confidence={0.91} size="lg" tilt />)
    expect(screen.getByTestId('outcome-stamp')).toHaveClass('stamp-tilt')
  })
})

describe('DualMeter', () => {
  it('is two meters with their own names, never one score', () => {
    render(<DualMeter proximityRank={1} hops={3} shareOfFunds={0.85} timeToReachS={960} confidence={0.91} interval={[0.84, 0.95]} />)
    const meters = screen.getAllByRole('meter')
    expect(meters).toHaveLength(2)
    expect(screen.getByRole('meter', { name: 'Proximity' })).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Confidence' })).toBeInTheDocument()
  })

  it('proximity says the rank, the hops, the share of the funds and the time', () => {
    render(<DualMeter proximityRank={1} hops={3} shareOfFunds={0.85} timeToReachS={960} confidence={0.91} interval={[0.84, 0.95]} />)
    const proximity = screen.getByRole('meter', { name: 'Proximity' })
    expect(proximity).toHaveAttribute('aria-valuenow', '3')
    expect(proximity).toHaveAttribute('aria-valuetext', 'Rank 1: 3 hops, 85% of the funds, 16 min')
    expect(screen.getByText('3 hops')).toBeInTheDocument()
    expect(screen.getByText('85% of the funds')).toBeInTheDocument()
  })

  it('writes one hop in the singular, and zero hops as the wallet itself', () => {
    const { rerender } = render(<DualMeter proximityRank={1} hops={1} shareOfFunds={1} confidence={0.75} />)
    expect(screen.getByText('1 hop')).toBeInTheDocument()
    rerender(<DualMeter proximityRank={1} hops={0} shareOfFunds={1} confidence={0.75} />)
    expect(screen.getByText('The wallet itself')).toBeInTheDocument()
  })

  it('confidence carries its value, its range and where the 0.60 bar is', () => {
    render(<DualMeter proximityRank={1} hops={3} shareOfFunds={0.85} confidence={0.91} interval={[0.84, 0.95]} />)
    const confidence = screen.getByRole('meter', { name: 'Confidence' })
    expect(confidence).toHaveAttribute('aria-valuenow', '0.91')
    expect(confidence).toHaveAttribute('aria-valuemin', '0')
    expect(confidence).toHaveAttribute('aria-valuemax', '1')
    expect(confidence).toHaveAttribute('aria-valuetext', 'confidence 0.91, range 0.84 to 0.95, at or above the 0.60 bar')
    expect(screen.getByTestId('confidence-bar-mark')).toHaveStyle({ left: '60%' })
    expect(screen.getByTestId('confidence-range')).toHaveStyle({ left: '84%', width: '11%' })
  })

  it('without a range it is rule confidence, and says so', () => {
    render(<DualMeter proximityRank={2} hops={2} shareOfFunds={0.54} confidence={0.71} interval={null} />)
    expect(screen.getByRole('meter', { name: 'Confidence' })).toHaveAttribute(
      'aria-valuetext',
      'rule confidence 0.71, at or above the 0.60 bar',
    )
    expect(screen.getByText('Rule confidence')).toBeInTheDocument()
    expect(screen.queryByTestId('confidence-range')).not.toBeInTheDocument()
  })

  it('under the bar it says so in words and is hatched, not just paler', () => {
    render(<DualMeter proximityRank={2} hops={4} shareOfFunds={0.15} confidence={0.46} interval={[0.31, 0.61]} />)
    expect(screen.getByRole('meter', { name: 'Confidence' })).toHaveAttribute(
      'aria-valuetext',
      'confidence 0.46, range 0.31 to 0.61, under the 0.60 bar',
    )
    expect(screen.getByText('Under the 0.60 bar')).toBeInTheDocument()
    expect(screen.getByTestId('confidence-fill')).toHaveClass('hatch')
  })

  it('takes another bar', () => {
    render(<DualMeter proximityRank={1} hops={1} shareOfFunds={1} confidence={0.75} bar={0.8} />)
    expect(screen.getByTestId('confidence-bar-mark')).toHaveStyle({ left: '80%' })
    expect(screen.getByText('Under the 0.80 bar')).toBeInTheDocument()
  })
})
