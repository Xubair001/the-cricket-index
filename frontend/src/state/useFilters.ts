import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Every filter on every page lives in the URL, and this hook is the one place
 * that reads and writes it.
 *
 * Filter state held in `useState` is invisible state: a reader who narrows a
 * board to Test bowling with a 20-match floor, then follows a player link and
 * comes back, lands on the unfiltered default with no way to tell what changed.
 * The same URL also cannot be shared, bookmarked, or reloaded, and the browser's
 * own back button silently becomes a page-level navigation rather than an undo.
 * Nine pages already did this correctly with a hand-rolled copy of the same
 * fifteen lines; seven did not, and the difference was not a decision anybody
 * made.
 *
 * Two writers rather than one with a boolean, because the two cases are
 * genuinely different and a flag at the call site does not say which is meant:
 *
 * - `set` is **a filter changed**, so paging resets. Holding the offset across a
 *   filter change lands the reader on page four of a three-page result and reads
 *   as an empty board.
 * - `keep` is **everything else** - the pager itself, and disclosures like the
 *   Performance Index's per-row "How?", which are UI state rather than a query
 *   and must not throw away the reader's place.
 *
 * Writes `replace` rather than pushing, so adjusting a dropdown four times
 * leaves one history entry instead of four. Back then means "the page I came
 * from", which is what a reader expects of it.
 */

/** A value being written. `null`, `undefined` and `''` all remove the key,
 *  so a filter set back to its default leaves no trace in the URL. */
type Writable = string | number | null | undefined

export type Filters = {
  /** Raw value, or `fallback` (default `''`) when absent. */
  get(key: string, fallback?: string): string
  /** Integer value, or `fallback` when absent or unparseable. */
  int(key: string, fallback: number): number
  /** `true` only for the literal string `true`, so an absent flag is false. */
  flag(key: string): boolean
  /** A filter changed. Paging resets. */
  set(next: Record<string, Writable>): void
  /** Not a filter: paging, or a disclosure. The offset is preserved. */
  keep(next: Record<string, Writable>): void
  /**
   * Drop every filter. For a gender switch, where an id from one gender names
   * nothing in the other, so carrying the query string over is worse than
   * starting clean.
   */
  clear(): void
  /** The current query string, for building a link that carries this state. */
  params: URLSearchParams
}

/** Reset on any filter change. Named so the two writers read as a pair. */
const PAGING_KEY = 'offset'

/**
 * The merge itself, pure and exported so the rule can be tested without a
 * router. `''`, `null` and `undefined` all REMOVE a key rather than writing an
 * empty one, so a filter returned to its default leaves no trace in the address
 * and two readers who made the same choices get the same link.
 */
export function mergeFilterParams(
  previous: URLSearchParams,
  next: Record<string, Writable>,
  resetPaging: boolean
): URLSearchParams {
  const merged = new URLSearchParams(previous)
  for (const [key, value] of Object.entries(next)) {
    const text = value === null || value === undefined ? '' : String(value)
    // Zero is written for a FILTER, because a floor of nought is a real choice
    // and dropping it would silently restore the control's default. It is
    // removed for paging, because page one is the absence of an offset and
    // `?offset=0` is noise in a link somebody is about to share.
    if (text && !(key === PAGING_KEY && text === '0')) merged.set(key, text)
    else merged.delete(key)
  }
  // An explicit offset in `next` is the caller paging deliberately, so it stands.
  if (resetPaging && !(PAGING_KEY in next)) merged.delete(PAGING_KEY)
  return merged
}

export function useFilters(): Filters {
  const [params, setParams] = useSearchParams()

  // Written through the functional form of the setter rather than by closing over
  // `params`, which is what makes `set` and `keep` STABLE across renders. It is
  // not a micro-optimisation: a writer whose identity changed with the query
  // string could not be listed in an effect's dependencies without that effect
  // re-running - and refetching - every time any unrelated parameter moved, such
  // as a disclosure being opened.
  const write = useCallback(
    (next: Record<string, Writable>, resetPaging: boolean) => {
      setParams((previous) => mergeFilterParams(previous, next, resetPaging), {
        replace: true,
      })
    },
    [setParams]
  )

  const set = useCallback((next: Record<string, Writable>) => write(next, true), [write])
  const keep = useCallback((next: Record<string, Writable>) => write(next, false), [write])
  const clear = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams])

  return useMemo(
    () => ({
      get: (key, fallback = '') => params.get(key) ?? fallback,
      int: (key, fallback) => {
        const raw = params.get(key)
        if (raw === null) return fallback
        const parsed = Number(raw)
        return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback
      },
      flag: (key) => params.get(key) === 'true',
      set,
      keep,
      clear,
      params,
    }),
    [params, set, keep, clear]
  )
}

export default useFilters
