import { buttonClass } from './ui'

interface PaginationProps {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
}

export function Pagination({ total, limit, offset, onChange }: PaginationProps) {
  const page = Math.floor(offset / limit) + 1
  const pageCount = Math.max(1, Math.ceil(total / limit))

  if (pageCount <= 1) return null

  // The range actually on screen, not just the page number. On a directory of
  // ~9,400 players "Page 3 of 189" says much less than "101-150 of 9,442"
  // about where you are in the list.
  const first = offset + 1
  const last = Math.min(offset + limit, total)

  return (
    <nav
      aria-label="Pagination"
      className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle py-3 text-sm"
    >
      <p className="tnum text-xs text-muted">
        <span className="text-ink">
          {first.toLocaleString()}–{last.toLocaleString()}
        </span>{' '}
        of {total.toLocaleString()}
        <span className="text-dim"> · page {page} of {pageCount.toLocaleString()}</span>
      </p>
      <div className="flex gap-2">
        <button
          className={buttonClass}
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={offset === 0}
        >
          Previous
        </button>
        <button
          className={buttonClass}
          onClick={() => onChange(offset + limit)}
          disabled={offset + limit >= total}
        >
          Next
        </button>
      </div>
    </nav>
  )
}
