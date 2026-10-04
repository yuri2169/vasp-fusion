import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cx } from '../lib/cx'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANT: Record<Variant, string> = {
  // The primary action is an officer's action, so it is in the confirm colour: one per screen.
  primary: 'bg-confirm text-surface border-transparent font-semibold hover:opacity-90 active:opacity-100',
  secondary: 'bg-surface text-ink border-ink font-medium hover:bg-surface-3',
  ghost: 'bg-transparent text-ink-soft border-rule font-medium hover:bg-surface-3 hover:text-ink',
  danger: 'bg-surface text-danger border-danger font-semibold hover:bg-danger-wash',
}

const SIZE: Record<Size, string> = {
  sm: 'h-7 gap-1.5 px-2.5 text-sm',
  md: 'h-8 gap-2 px-3 text-base',
}

/** The classes alone, for a router <Link> or an <a> that should look like a button. */
export function buttonClass(variant: Variant = 'secondary', size: Size = 'md', extra?: string): string {
  return cx(
    'inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap border transition-colors duration-150',
    'disabled:cursor-not-allowed disabled:opacity-40',
    VARIANT[variant],
    SIZE[size],
    extra,
  )
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: ReactNode
}

export function Button({ variant = 'secondary', size = 'md', icon, className, children, type = 'button', ...rest }: ButtonProps) {
  return (
    <button type={type} className={buttonClass(variant, size, className)} {...rest}>
      {icon}
      {children}
    </button>
  )
}
