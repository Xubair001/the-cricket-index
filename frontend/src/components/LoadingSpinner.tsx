/**
 * Loading and failure states.
 *
 * The spinner is a ring on the par-datum motif - a track with one lit arc -
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

/**
 * Turns a thrown fetch error into something a reader can act on.
 *
 * The client throws `"404 Not Found: {\"detail\":\"player 'x' not found\"}"`,
 * and this component used to print that verbatim followed by "check the API is
 * running on port 8001". Three things wrong with that: the port is a developer's
 * detail and was wrong the moment a second instance ran on another port, a JSON
 * envelope is not a sentence, and "the API is down" is the wrong diagnosis for
 * the far commoner case of a URL naming something that does not exist.
 *
 * So a status code chooses the wording, and the server's own `detail` - which
 * this project writes as a readable sentence on every 404 and 422 - is the
 * explanation. Anything unrecognised falls back to a plain retry line rather
 * than exposing whatever text came back.
 */
function status(message: string): number | null {
  const match = /^(\d{3}) /.exec(message.replace(/^Error:\s*/, ''))
  return match ? Number(match[1]) : null
}

function detail(message: string): string | null {
  // Callers pass either `error.message` or `String(error)`, and the second
  // carries an "Error: " prefix - so the body is found from the first brace
  // rather than from the first colon, which that prefix would otherwise claim.
  const start = message.indexOf('{')
  if (start === -1) return null
  try {
    const parsed = JSON.parse(message.slice(start))
    const value = typeof parsed?.detail === 'string' ? parsed.detail : null
    // FastAPI's validation errors are a list, which is not prose.
    return value && value.length < 300 ? value : null
  } catch {
    return null
  }
}

function headline(message: string): string {
  const code = status(message)
  if (code === 404) return 'Not found here.'
  if (code === 422) return 'That filter cannot be applied.'
  return "Couldn't load this."
}

function readable(message: string): string {
  const said = detail(message)
  const code = status(message)
  if (said) {
    // Capitalise the server's sentence and give it a full stop, so it reads as
    // prose beside the headline rather than as a field value.
    const sentence = said.charAt(0).toUpperCase() + said.slice(1)
    return /[.!?]$/.test(sentence) ? sentence : sentence + '.'
  }
  if (code === 404) return 'Nothing in this dataset matches that address.'
  // Deliberately NOT "try reloading": a 422 is the address itself carrying a
  // value the API will not accept, so the same request will fail the same way.
  // The project's own 422s carry a readable `detail` and are handled above;
  // this is the framework's field-level shape, which is not prose.
  if (code === 422) return 'The address carries a value this page cannot use.'
  if (code && code >= 500) return 'Something went wrong at our end. Try again in a moment.'
  return 'Try reloading the page.'
}

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
        <p className="font-medium text-negative-ink">{headline(message)}</p>
        <p className="mt-0.5 break-words text-xs leading-relaxed text-negative-ink/85">
          {readable(message)}
        </p>
      </div>
    </div>
  )
}
