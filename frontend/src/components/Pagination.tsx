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

  const button =
    'rounded-md border border-border-default px-3 py-1.5 font-medium text-ink transition-colors hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'

  return (
    <div className="flex items-center justify-between gap-4 border-t border-border-subtle py-3 text-sm">
      <span className="tnum text-muted">
        Page {page} of {pageCount} &middot; {total.toLocaleString()} total
      </span>
      <div className="flex gap-2">
        <button className={button} onClick={() => onChange(Math.max(0, offset - limit))} disabled={offset === 0}>
          Previous
        </button>
        <button className={button} onClick={() => onChange(offset + limit)} disabled={offset + limit >= total}>
          Next
        </button>
      </div>
    </div>
  )
}
