import { BadgeCheck, CircleDashed, FlaskConical, ListChecks, Tag, type LucideIcon } from 'lucide-react'
import type { Tier } from '../api/models'
import { cx } from '../lib/cx'

/** How strong a label is. Always icon + words + colour: never colour alone. */
export const TIERS: Record<Tier | 'none', { name: string; Icon: LucideIcon; tag: string; icon: string }> = {
  published_por: {
    name: 'Published by exchange',
    Icon: BadgeCheck,
    tag: 'border-transparent bg-verified text-verified-on',
    icon: 'text-verified-text',
  },
  curated: {
    name: 'Curated list',
    Icon: ListChecks,
    tag: 'border-transparent bg-verified-wash text-verified-text',
    icon: 'text-verified-text',
  },
  explorer_tag: {
    name: 'Explorer tag',
    Icon: Tag,
    tag: 'border-verified-text text-verified-text',
    icon: 'text-verified-text',
  },
  derived: {
    name: 'Derived by VASP-FUSION',
    Icon: FlaskConical,
    tag: 'border-rule-strong bg-slate-wash text-muted',
    icon: 'text-muted',
  },
  none: {
    name: 'Unlabelled',
    Icon: CircleDashed,
    tag: 'border-dashed border-rule-strong text-muted',
    icon: 'text-muted',
  },
}

export function TierTag({ tier, size = 'md' }: { tier: Tier | null; size?: 'sm' | 'md' }) {
  const { name, Icon, tag } = TIERS[tier ?? 'none']
  return (
    <span
      data-tier={tier ?? 'none'}
      className={cx(
        'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-sm border text-xs font-medium',
        size === 'sm' ? 'h-5 px-1.5' : 'h-6 px-2',
        tag,
      )}
    >
      <Icon size={13} aria-hidden />
      {name}
    </span>
  )
}

/** The icon alone, where the words are given next to it (an address chip's tooltip, a table column). */
export function TierIcon({ tier, size = 13 }: { tier: Tier | null; size?: number }) {
  const { Icon, icon } = TIERS[tier ?? 'none']
  return <Icon size={size} aria-hidden className={cx('shrink-0', icon)} />
}
