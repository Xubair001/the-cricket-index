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

/**
 * A 0-100 score. No sign, no percent sign - it is an index, not a proportion.
 *
 * One decimal because the top of a percentile board is compressed: the leading
 * handful of a 700-player scope all sit above 99, and at 0dp they render as an
 * identical "100" while the rows around them visibly differ.
 */
export function score(value: number | null | undefined, dash = '-'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return dash
  return value.toFixed(1)
}

/**
 * A change against a baseline, worded so it is never a percentage over 100.
 *
 * The API sends `delta_display` already worded this way, and that is what
 * should be rendered when it is present. This is the client-side equivalent for
 * the rows that carry only a number.
 *
 * Why not just print the percentage: a ratio against a player's own baseline
 * has no ceiling, and this dataset produces up to +306%. A percentage past 100
 * stops reading as "more than doubled" and starts reading as a broken figure,
 * so past a doubling the same fact is stated as a multiple instead. Nothing is
 * clipped - the wording changes, the value does not.
 */
export function change(value: number | null | undefined, dash = '-'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return dash
  if (Math.abs(value) > 100) {
    const multiple = value > 0 ? 1 + value / 100 : 1 / (1 + Math.abs(value) / 100)
    return `${multiple.toFixed(value > 0 ? 1 : 2)}x baseline`
  }
  return `${value > 0 ? '+' : ''}${value.toFixed(0)}%`
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
