/**
 * The par datum — this product's signature device.
 *
 * Every derived figure here is relative to par: form boards rank on par units
 * gained, and opposition strength is fitted so that par means an average
 * match rather than an average team. A bare "0.70x" does not say that. A bar
 * anchored to a marked datum does, and it does it before the reader has
 * parsed the number.
 *
 * The bar grows *from* the datum, right when above par and left when below,
 * so direction is carried by geometry. Colour reinforces it but is never the
 * only channel — which matters because a below-par figure sits inches from an
 * uncertainty marker in the same row, and those two hues cannot be told apart
 * (see the note in index.css).
 */

const DEFAULT_MAX = 2

export function ParMeter({
  value,
  max = DEFAULT_MAX,
  className = '',
  label,
}: {
  /** Par units. 1.0 is an average appearance. */
  value: number | null | undefined
  /** Top of the track. Values beyond it clamp and are marked as clamped. */
  max?: number
  className?: string
  /** Accessible description; falls back to a generated one. */
  label?: string
}) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return (
      <div className={`par-track ${className}`} style={{ ['--par-pos' as string]: 1 / max }}>
        <span className="sr-only">Standard unavailable</span>
      </div>
    )
  }

  const datum = 1 / max
  const clamped = Math.min(Math.max(value, 0), max)
  const position = clamped / max
  const above = value >= 1

  // Width is measured from the datum, so a player at 1.4 and one at 0.6 draw
  // mirrored bars of the same length rather than one long bar and one short.
  const left = above ? datum : position
  const width = Math.abs(position - datum)

  const description =
    label ??
    `${value.toFixed(2)} par units — ${
      above ? 'above' : 'below'
    } the 1.00 average appearance${value > max ? ', clamped to the top of the scale' : ''}`

  return (
    <div
      className={`par-track ${className}`}
      style={{ ['--par-pos' as string]: datum }}
      role="img"
      aria-label={description}
      title={description}
    >
      <span
        className="par-fill"
        style={{
          left: `${left * 100}%`,
          width: `${Math.max(width * 100, 0.6)}%`,
          background: above ? 'var(--color-positive)' : 'var(--color-negative)',
        }}
      />
    </div>
  )
}

/**
 * The figure that goes beside the meter.
 *
 * Carries the sign as well as the colour, so the above/below reading survives
 * a greyscale print, a colour-vision deficiency, and a forced-colors mode.
 */
export function ParFigure({
  value,
  className = '',
}: {
  value: number | null | undefined
  className?: string
}) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className={`tnum text-dim ${className}`}>—</span>
  }
  const above = value >= 1
  return (
    <span
      className={`tnum font-mono ${above ? 'text-positive-ink' : 'text-negative-ink'} ${className}`}
      title={`${value.toFixed(2)}x what an average appearance is worth`}
    >
      {above ? '▲' : '▼'} {value.toFixed(2)}
      <span className="text-dim">x</span>
    </span>
  )
}
