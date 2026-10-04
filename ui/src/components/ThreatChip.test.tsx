import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ThreatTag } from '../api/models'
import { ScreeningNote, ThreatChip, ThreatChips, THREATS, threatOf, threatSource } from './ThreatChip'
import { TypologyFlag } from './TypologyFlag'

// The tag of TLDtPq9PQsDuQunME8CSeVdYaLtRdrVgoJ as the label store holds it (demo case tron-terror-link).
const ISIL: ThreatTag = {
  threat: 'terrorism_financing',
  entity: 'ISIL KHORASAN',
  source: 'ofac-sdn-xml',
  url: 'https://sanctionssearch.ofac.treas.gov/Details.aspx?id=18647',
  evidence: 'OFAC SDN list (published 2026-10-02), uid 18647: ISIL KHORASAN; programme FTO, SDGT. Listed as: TRX.',
}

describe('ThreatChip', () => {
  it('says the threat in words beside an icon, and who the source names', () => {
    render(<ThreatChip tag={ISIL} />)
    const chip = screen.getByText('Terrorism financing').closest('[data-threat]')!
    expect(chip).toHaveAttribute('data-threat', 'terrorism_financing')
    expect(chip).toHaveTextContent('Terrorism financing· ISIL KHORASAN')
    expect(chip.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('has words for every threat', () => {
    expect(Object.values(THREATS).map((t) => t.name)).toEqual(['Terrorism financing', 'Ransomware', 'Darknet market', 'Fraud', 'Sanctioned'])
  })

  it('shows the source and its own words on hover and on keyboard focus', async () => {
    const user = userEvent.setup()
    render(<ThreatChip tag={ISIL} />)
    await user.tab()
    const card = screen.getByRole('tooltip')
    expect(card).toHaveTextContent('Source: OFAC SDN list')
    expect(card).toHaveTextContent('programme FTO, SDGT')
  })

  it('draws nothing for an untagged label, and reads a tag off a label', () => {
    const { container } = render(<ThreatChip tag={threatOf(null)} />)
    expect(container).toBeEmptyDOMElement()
    expect(threatOf({ threat: 'ransomware', threat_entity: 'Conti', threat_source: 'ransomwhere' } as never)).toEqual({
      threat: 'ransomware',
      entity: 'Conti',
      source: 'ransomwhere',
      url: null,
      evidence: null,
    })
  })

  it('names sources as the backend does', () => {
    expect(threatSource('ransomwhere')).toBe('Ransomwhere')
    expect(threatSource('graphsense-tagpack:hydra')).toBe('GraphSense TagPacks')
    expect(threatSource('mew-ethereum-lists+eth-labels')).toBe('MyEtherWallet scam list')
    expect(threatSource(null)).toBeNull()
  })

  it('lists the threats a case touches', () => {
    render(<ThreatChips threats={['terrorism_financing', 'fraud']} />)
    expect(screen.getByLabelText('Threat tags this case touches')).toHaveTextContent('Terrorism financingFraud')
  })
})

describe('ScreeningNote', () => {
  it('raises a direct hit as an alert with the reason', () => {
    render(<ScreeningNote screening={{ hit: true, tag: ISIL, text: 'Direct hit: this address is tagged terrorism financing (ISIL KHORASAN, OFAC SDN list).' }} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('High-risk wallet')
    expect(alert).toHaveTextContent('Direct hit: this address is tagged terrorism financing')
    expect(alert).toHaveTextContent('uid 18647')
  })

  it('says quietly that nothing was found', () => {
    render(<ScreeningNote screening={{ hit: false, tag: null, text: 'No direct hit: the address itself carries no tag.' }} />)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByText(/Screened on intake/)).toBeInTheDocument()
  })
})

describe('a flag on a tagged address', () => {
  it('carries the chip beside its name', () => {
    render(
      <TypologyFlag
        flag={{
          code: 'threat_contact',
          severity: 'high',
          wallet: 'bc1q',
          text: 'Linked to ransomware (Conti, Ransomwhere): 2 hops away, 14% of the funds (1.2 BTC) reached bc1q',
          figures: {},
          tx_hashes: [],
          threat: { threat: 'ransomware', entity: 'Conti', source: 'ransomwhere' },
        }}
      />,
    )
    expect(screen.getByText('Link to a tagged address')).toBeInTheDocument()
    expect(screen.getByText('Ransomware').closest('[data-threat]')).toHaveTextContent('Ransomware· Conti')
  })
})
