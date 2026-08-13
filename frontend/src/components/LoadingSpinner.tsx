/**
 * Loading and failure states.
 *
 * The spinner is a ring on the par-datum motif — a track with one lit arc —
 * rather than a generic spinner, so a load reads as part of the product
 * rather than as a borrowed widget.
 */
export function LoadingSpinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16" role="status">
      <div className="h-7 w-7 animate-spin rounded-full border-2 border-border-default border-t-analytic" />
      <span className="u-eyebrow">{label}</span>
    </div>
  )
}

/**
 * A row of skeleton bars, for lists that know their own length.
 *
 * Preferred over a spinner wherever the shape of the result is already known:
 * the layout doesn't jump when the data lands.
 */
export function SkeletonRows({ rows = 5, className = '' }: { rows?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-7 animate-pulse rounded-md bg-sunken" />
      ))}
    </div>
  )
}

/**
 * A failed fetch.
 *
 * Says what failed and what to do about it, in the interface's voice. The
 * underlying message is kept because it is usually the only clue about
 * whether the API is down or the request was bad.
 */
export function ErrorMessage({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2.5 rounded-xl border border-border-subtle bg-negative-dim px-4 py-3"
    >
      <svg viewBox="0 0 16 16" aria-hidden className="mt-px h-4 w-4 shrink-0 text-negative-ink">
        <path
          d="M8 1.5 15 14H1L8 1.5Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
        <path d="M8 6v3.4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="8" cy="11.6" r="0.85" fill="currentColor" />
      </svg>
      <div className="min-w-0 text-sm">
        <p className="font-medium text-negative-ink">Couldn't load this.</p>
        <p className="mt-0.5 break-words text-xs leading-relaxed text-negative-ink/85">
          {message} — check the API is running on port 8001, then reload.
        </p>
      </div>
    </div>
  )
}
