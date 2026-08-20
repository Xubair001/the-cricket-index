/**
 * Figure formatting.
 *
 * §23 makes tabular numerals non-negotiable in a product built on tables, but
 * the `tnum` font feature only aligns digits that are *there*. The API rounds
 * rates to two decimals and drops trailing zeros, so a win-percentage column
 * arrives as 58.88, 49.16, 50, 37.5 - and rendered raw, the decimal points in
 * that column do not line up no matter what the font does. `50%` sitting under
 * `58.88%` is exactly the re-finding-the-decimal-point problem tabular numerals
 * exist to remove.
 *
 * So rates are padded back out to a fixed width here. Counts are not: an
 * integer is exact, and `1,019` should not become `1,019.00`.
 */

/** A rate - average, strike rate, economy. Fixed 2dp so columns align. */
export function rate(value: number | null | undefined, dash = '-'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return dash
  return value.toFixed(2)
}

/** A percentage, with the sign. Fixed 2dp for the same reason. */
export function percent(value: number | null | undefined, dash = '-'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return dash
  return `${value.toFixed(2)}%`
}

/** A count. Thousands separated, never given decimals it doesn't have. */
export function count(value: number | null | undefined, dash = '-'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return dash
  return value.toLocaleString()
}

/** ISO timestamp -> "2h ago", "3d ago", or a date once it stops being news. */
export function timeAgo(iso: string | null): string {
  if (!iso) return '-'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '-'
  const mins = Math.round((Date.now() - then) / 60000)
  // Publishers schedule features ahead of their own publication time, so a
  // small negative age is normal and must not render as "-1h ago".
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days <= 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}
