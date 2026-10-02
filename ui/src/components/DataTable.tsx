import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { useMemo, useState, type CSSProperties, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react'
import { cx } from '../lib/cx'
import { Skeleton } from './Skeleton'

export interface Column<T> {
  key: string
  header: string
  cell: (row: T) => ReactNode
  /** Give one to make the column sortable. null sorts last, whichever the direction. */
  sortValue?: (row: T) => string | number | null
  align?: 'left' | 'right'
  width?: CSSProperties['width']
}

export type Sort = { key: string; dir: 'asc' | 'desc' }

export interface DataTableProps<T> {
  /** What the table lists; read out by screen readers. */
  caption: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  initialSort?: Sort
  /** Makes each row open something (click, or Enter on the focused row). */
  onRowOpen?: (row: T) => void
  loading?: boolean
  /** Shown instead of rows when there are none. */
  empty?: ReactNode
  /** The body scrolls under a sticky header once the table is taller than this. */
  maxHeight?: CSSProperties['maxHeight']
}

const INTERACTIVE = 'a, button, input, select, textarea, [role="button"]'

function compare(a: string | number | null, b: string | number | null, dir: 1 | -1): number {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1 // no value: always last
  if (typeof a === 'number' && typeof b === 'number') return (a - b) * dir
  return String(a).localeCompare(String(b), 'en', { numeric: true }) * dir
}

export function DataTable<T>({ caption, columns, rows, rowKey, initialSort, onRowOpen, loading, empty, maxHeight }: DataTableProps<T>) {
  const [sort, setSort] = useState<Sort | null>(initialSort ?? null)

  const sorted = useMemo(() => {
    const column = sort && columns.find((c) => c.key === sort.key)
    if (!sort || !column?.sortValue) return rows
    const value = column.sortValue
    const dir = sort.dir === 'asc' ? 1 : -1
    return rows
      .map((row, i) => ({ row, i }))
      .sort((a, b) => compare(value(a.row), value(b.row), dir) || a.i - b.i)
      .map(({ row }) => row)
  }, [rows, columns, sort])

  const toggle = (key: string) => setSort((s) => (s?.key === key && s.dir === 'asc' ? { key, dir: 'desc' } : { key, dir: 'asc' }))

  const open = (row: T) => (e: MouseEvent<HTMLTableRowElement>) => {
    if ((e.target as Element).closest(INTERACTIVE)) return // a control in the row was used, not the row
    onRowOpen?.(row)
  }
  const openByKey = (row: T) => (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === 'Enter' && e.target === e.currentTarget) onRowOpen?.(row)
  }

  return (
    <div className="overflow-auto rounded-md border border-rule bg-surface" style={{ maxHeight }}>
      <table aria-busy={loading || undefined} className="w-full border-separate border-spacing-0 text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key
              const Icon = !active ? ChevronsUpDown : sort.dir === 'asc' ? ArrowUp : ArrowDown
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={c.sortValue ? (active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none') : undefined}
                  style={{ width: c.width }}
                  className={cx(
                    'eyebrow sticky top-0 z-10 h-9 whitespace-nowrap border-b border-rule-strong bg-sunk px-3',
                    c.align === 'right' ? 'text-right' : 'text-left',
                  )}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggle(c.key)}
                      className={cx(
                        '-mx-1 inline-flex items-center gap-1 rounded-sm px-1 uppercase tracking-[inherit] hover:text-fg',
                        active && 'text-fg',
                      )}
                    >
                      {c.header}
                      <Icon size={12} aria-hidden />
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {loading &&
            [0, 1, 2, 3].map((i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key} className="h-11 border-b border-rule px-3">
                    <Skeleton width={c.align === 'right' ? '50%' : '75%'} />
                  </td>
                ))}
              </tr>
            ))}
          {!loading && sorted.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-8 text-sm text-muted">
                {empty ?? 'Nothing to show.'}
              </td>
            </tr>
          )}
          {!loading &&
            sorted.map((row) => (
              <tr
                key={rowKey(row)}
                tabIndex={onRowOpen ? 0 : undefined}
                onClick={onRowOpen && open(row)}
                onKeyDown={onRowOpen && openByKey(row)}
                className={cx('group', onRowOpen && 'cursor-pointer hover:bg-sunk focus-visible:bg-sunk')}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cx(
                      'h-11 border-b border-rule px-3 py-1.5 align-middle group-last:border-b-0',
                      c.align === 'right' && 'text-right',
                    )}
                  >
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}
