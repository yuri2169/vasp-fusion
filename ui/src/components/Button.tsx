import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cx } from '../lib/cx'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANT: Record<Variant, string> = {
  // Saffron is the primary action, and only that: one per screen.
  primary: 'bg-saffron text-saffron-on border-transparent font-semibold hover:brightness-105 active:brightness-95',
  secondary: 'bg-surface text-fg border-rule-strong font-medium hover:bg-sunk',
  ghost: 'bg-transparent text-fg border-transparent font-medium hover:bg-sunk',
  danger: 'bg-seal text-seal-on border-transparent font-semibold hover:brightness-110 active:brightness-95',
}

const SIZE: Record<Size, string> = {
  sm: 'h-7 gap-1.5 px-2.5 text-xs',
  md: 'h-9 gap-2 px-3.5 text-sm',
}

/** The classes alone, for a router <Link> or an <a> that should look like a button. */
export function buttonClass(variant: Variant = 'secondary', size: Size = 'md', extra?: string): string {
  return cx(
    'inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded border',
    'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:brightness-100',
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
