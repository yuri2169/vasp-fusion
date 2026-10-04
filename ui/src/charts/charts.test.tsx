import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { score, share } from '../overview/words'
import { renderApp } from '../test/render'
import { BarList } from './BarList'
import { CoveragePlot, ReliabilityPlot } from './ModelPlots'
import { ShareBar } from './ShareBar'
import { barPercent, floorTo, linear, niceTicks } from './scale'

describe('the arithmetic of a chart', () => {
  it('maps a domain onto a range and clamps what is outside it', () => {
    const x = linear(0, 1, 50, 150)
    expect(x(0)).toBe(50)
    expect(x(0.5)).toBe(100)
    expect(x(2)).toBe(150)
    expect(x(-1)).toBe(50)
    const y = linear(0, 1, 300, 0) // SVG: larger values are higher up
    expect(y(1)).toBe(0)
    expect(y(0.25)).toBe(225)
  })

  it('picks round ticks', () => {
    expect(niceTicks(0, 1)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1])
    expect(niceTicks(0.9, 1)).toEqual([0.9, 0.92, 0.94, 0.96, 0.98, 1])
    expect(niceTicks(0, 0)).toEqual([0])
  })

  it('starts a zoomed axis on a round value at or under the lowest point', () => {
    expect(floorTo(0.934, 0.02)).toBe(0.92)
    expect(floorTo(0.71, 0.1)).toBe(0.7)
    expect(floorTo(0.9, 0.02)).toBe(0.9)
  })

  it('never draws a non-zero value as nothing', () => {
    expect(barPercent(0, 100)).toBe(0)
    expect(barPercent(1, 100_000)).toBe(1)
    expect(barPercent(50, 100)).toBe(50)
    expect(barPercent(200, 100)).toBe(100)
  })

  it('never writes a share or a score as perfect unless it is', () => {
    expect(share(0.986)).toBe('98.6%')
    expect(share(0.99996)).toBe('over 99.9%')
    expect(share(1)).toBe('100%')
    expect(score(0.99996)).toBe('over 0.999')
    expect(score(1)).toBe('over 0.999')
    expect(score(0.0093)).toBe('0.009')
    expect(score(null)).toBe('not measured')
  })
})

describe('BarList', () => {
  const rows = [
    { key: 'a', label: 'CoinDCX', value: 7530, valueText: '$7,530', note: '2 cases', to: '/vasps/CoinDCX' },
    { key: 'b', label: 'HTX', value: 7000, valueText: '$7,000', note: '1 case' },
  ]

  it('writes every value beside its bar, and links a row to the list behind it', () => {
    renderApp(<BarList caption="Exchanges" rows={rows} />)
    const list = screen.getByRole('list', { name: 'Exchanges' })
    const items = within(list).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('CoinDCX$7,5302 cases')
    expect(within(items[0]).getByRole('link')).toHaveAttribute('href', '/vasps/CoinDCX')
    expect(within(items[1]).queryByRole('link')).not.toBeInTheDocument()
    const bars = within(list).getAllByTestId('bar')
    expect(bars[0]).toHaveStyle({ width: '100%' })
    expect(parseFloat(bars[1].style.width)).toBeCloseTo(92.96, 1)
  })

  it('says so when there is nothing to count', () => {
    renderApp(<BarList caption="Exchanges" rows={[]} empty="No finished case names an exchange yet." />)
    expect(screen.getByText('No finished case names an exchange yet.')).toBeInTheDocument()
  })
})

describe('ShareBar', () => {
  it('names every part with its count, draws no segment for a part of zero, and reads as one sentence', () => {
    renderApp(
      <ShareBar
        caption="Finished cases by outcome"
        unit={(n) => `${n} cases`}
        parts={[
          { key: 'a', name: 'An exchange is named', value: 4, fill: 'named', to: '/cases?outcome=ATTRIBUTED' },
          { key: 'i', name: 'Insufficient evidence', value: 3, fill: 'open' },
          { key: 's', name: 'Sanctioned or mixer', value: 0, fill: 'seal' },
        ]}
      />,
    )
    expect(screen.getByRole('img')).toHaveAccessibleName('Finished cases by outcome: 4 cases An exchange is named, 3 cases Insufficient evidence, 0 cases Sanctioned or mixer')
    expect(screen.getAllByTestId('share-segment')).toHaveLength(2)
    const legend = screen.getByRole('list', { name: 'Finished cases by outcome' })
    expect(within(legend).getAllByRole('listitem')).toHaveLength(3)
    expect(within(legend).getByRole('link', { name: /An exchange is named/ })).toHaveAttribute('href', '/cases?outcome=ATTRIBUTED')
    expect(legend).toHaveTextContent('57%')
  })
})

describe('the model plots', () => {
  const bins = [
    { bin_mid: 0.05, predicted: 0.0092, observed: 0, count: 413 },
    { bin_mid: 0.55, predicted: 0.53, observed: 0.25, count: 8 },
    { bin_mid: 0.95, predicted: 0.9991, observed: 1, count: 1364 },
    { bin_mid: 0.65, predicted: null, observed: 0, count: 0 },
  ]

  it('a reliability plot has a point per group that holds addresses, each named, and the same figures as a table', () => {
    renderApp(<ReliabilityPlot bins={bins} />)
    const points = screen.getAllByRole('img', { name: /^Predicted/ })
    expect(points).toHaveLength(3) // the empty group is not drawn
    expect(points[2]).toHaveAccessibleName('Predicted over 0.99, observed over 0.99, 1,364 addresses')
    const table = screen.getByRole('table', { name: 'Reliability, per group of addresses', hidden: true })
    expect(within(table).getAllByRole('row', { hidden: true })).toHaveLength(4)
    expect(table).toHaveTextContent('0.530.258')
  })

  it('a coverage plot says where its zoomed axis starts and lists every point in its table', () => {
    const points = Array.from({ length: 30 }, (_, i) => ({ coverage: (i + 1) / 30, accuracy: 1 - i * 0.002 }))
    renderApp(<CoveragePlot points={points} caption="Accuracy against coverage" xTitle="Answered" yTitle="Right" reference={{ value: 0.9458, name: 'the one rule' }} />)
    expect(screen.getByText('The vertical axis starts at 90%, not at zero.')).toBeInTheDocument()
    expect(screen.getByText('the one rule')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Accuracy against coverage', hidden: true })
    expect(within(table).getAllByRole('row', { hidden: true })).toHaveLength(31)
    // fewer marks than points, but the last point is always marked
    const marks = screen.getAllByRole('img', { name: /^Answering/ })
    expect(marks.length).toBeLessThan(30)
    expect(marks.at(-1)).toHaveAccessibleName('Answering 100%: 94.2% right')
  })
})
