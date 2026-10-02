import type { CSSProperties } from 'react'

/** A grey block where content is on its way. Hidden from screen readers: the region it
 *  stands in says "Loading". */
export function Skeleton({
  width = '100%',
  height = 14,
  lines = 1,
}: {
  width?: CSSProperties['width']
  height?: CSSProperties['height']
  lines?: number
}) {
  return (
    <span aria-hidden="true" className="flex flex-col gap-2">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton block" style={{ width: lines > 1 && i === lines - 1 ? '60%' : width, height }} />
      ))}
    </span>
  )
}
