import { BadgeAlert, Ban, LockKeyhole, ShieldAlert, ShieldCheck, Siren, Store, type LucideIcon } from 'lucide-react'
import type { LabelOut, Screening, Threat, ThreatTag } from '../api/models'
import { cx } from '../lib/cx'
import { Tip, useTip } from './Tip'

/** What a public source ties an address to. Always icon + words: the danger colour alone says nothing. */
export const THREATS: Record<Threat, { name: string; Icon: LucideIcon }> = {
  terrorism_financing: { name: 'Terrorism financing', Icon: Siren },
  ransomware: { name: 'Ransomware', Icon: LockKeyhole },
  darknet_market: { name: 'Darknet market', Icon: Store },
  fraud: { name: 'Fraud', Icon: BadgeAlert },
  sanctioned_other: { name: 'Sanctioned', Icon: Ban },
}

/** The order the filters and summaries list them in: most specific first, as the label store ranks them. */
export const THREAT_ORDER = Object.keys(THREATS) as Threat[]

/** How a source is named in a sentence (mirrors vaspfusion/labels/threats.py, `source_name`). */
export function threatSource(source: string | null | undefined): string | null {
  if (!source) return null
  const first = source.split('+')[0].trim()
  if (first.startsWith('graphsense-tagpack:')) return 'GraphSense TagPacks'
  return (
    {
      'ofac-sdn-xml': 'OFAC SDN list',
      'ofac-sdn': 'OFAC SDN list',
      ransomwhere: 'Ransomwhere',
      'mew-ethereum-lists': 'MyEtherWallet scam list',
      'eth-labels': 'explorer tag',
    }[first] ?? first
  )
}

/** The threat tag of a label, as the flags and alerts carry it (null for an untagged label). */
export function threatOf(label: LabelOut | null | undefined): ThreatTag | null {
  if (!label?.threat) return null
  return {
    threat: label.threat,
    entity: label.threat_entity ?? null,
    source: label.threat_source ?? null,
    url: label.threat_url ?? null,
    evidence: label.threat_evidence ?? null,
  }
}

type Props = {
  /** The threat alone, or the whole tag: with a tag the chip names who, and its card gives the source's words. */
  threat?: Threat
  tag?: ThreatTag | null
  size?: 'sm' | 'md'
  /** Leave the entity out where the row already names it. */
  bare?: boolean
}

/** A threat tag: icon, the threat in words and, with a tag, who the source names. Hover or focus shows the
 *  source and its own words. */
export function ThreatChip({ threat, tag, size = 'md', bare = false }: Props) {
  const tip = useTip()
  const kind = tag?.threat ?? threat
  if (!kind) return null
  const { name, Icon } = THREATS[kind]
  const who = !bare && tag?.entity ? tag.entity : null
  const source = threatSource(tag?.source)
  const hasCard = Boolean(tag && (source || tag.evidence))
  return (
    <>
      <span
        data-threat={kind}
        tabIndex={hasCard ? 0 : undefined}
        aria-describedby={tip.open ? tip.id : undefined}
        {...(hasCard ? tip.bind : {})}
        className={cx(
          'inline-flex max-w-full shrink-0 items-center gap-1 border border-danger bg-danger-wash font-sans text-2xs font-semibold normal-case tracking-normal text-danger',
          size === 'sm' ? 'h-[18px] px-1.5' : 'h-5 px-2',
        )}
      >
        <Icon size={12} aria-hidden className="shrink-0" />
        <span className="whitespace-nowrap">{name}</span>
        {who && <span className="truncate font-medium text-ink">· {who}</span>}
      </span>
      {hasCard && (
        <Tip id={tip.id} anchor={tip.anchor}>
          <span className="flex flex-col gap-1">
            <span className="font-semibold">
              {name}
              {tag?.entity ? `: ${tag.entity}` : ''}
            </span>
            {source && <span className="text-ink-soft">Source: {source}</span>}
            {tag?.evidence && <span>{tag.evidence}</span>}
          </span>
        </Tip>
      )}
    </>
  )
}

/** The distinct threats a case touches, as chips (the case header, a row of the cases list). */
export function ThreatChips({ threats, size = 'md' }: { threats: readonly Threat[] | undefined; size?: 'sm' | 'md' }) {
  if (!threats?.length) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1" aria-label="Threat tags this case touches">
      {threats.map((t) => (
        <ThreatChip key={t} threat={t} size={size} />
      ))}
    </span>
  )
}

/** What the check of the case's own address against the threat tags found, in the backend's sentence. A hit is
 *  an alert; no hit is one quiet line, shown while the trace is still running. */
export function ScreeningNote({ screening }: { screening: Screening | null | undefined }) {
  if (!screening) return null
  if (!screening.hit)
    return (
      <p className="flex items-start gap-2 text-base text-ink-soft" data-screening="clear">
        <ShieldCheck size={15} aria-hidden className="mt-0.5 shrink-0" />
        <span>
          <span className="font-medium text-ink">Screened on intake.</span> {screening.text}
        </span>
      </p>
    )
  return (
    <div role="alert" data-screening="hit" className="flex flex-col gap-1.5 border-l-2 border-danger bg-danger-wash px-3 py-2">
      <span className="inline-flex flex-wrap items-center gap-2">
        <ShieldAlert size={15} aria-hidden className="shrink-0 text-danger" />
        <span className="text-2xs font-semibold uppercase tracking-[0.075em] text-danger">High-risk wallet</span>
        {screening.tag && <ThreatChip tag={screening.tag} />}
      </span>
      <p className="text-base text-ink">{screening.text}</p>
      {screening.tag?.evidence && <p className="text-sm text-ink-soft [overflow-wrap:anywhere]">{screening.tag.evidence}</p>}
    </div>
  )
}
