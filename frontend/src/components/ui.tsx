import type { ReactNode } from 'react'

/**
 * Shared surfaces and controls.
 *
 * Before this existed, `rounded-lg border border-border-default bg-surface p-4`
 * was written out in fourteen files, which meant a change to card treatment was
 * fourteen edits and the pages had already drifted apart on padding and radius.
 * Everything below is the same set of tokens, named once.
 */

/* ── Controls ──────────────────────────────────────────────────
 * Exported as strings rather than components because they are applied to
 * native <input>, <select> and <textarea>, which each take different props. */

export const fieldClass =
  'w-full rounded-lg border border-border-default bg-surface px-3 py-2 text-sm text-ink shadow-card ' +
  'transition-colors placeholder:text-dim hover:border-border-strong ' +
  'focus:border-analytic focus:outline-none focus:ring-2 focus:ring-analytic/25'

export const fieldLabelClass = 'u-eyebrow block'

export const buttonClass =
  'inline-flex items-center justify-center gap-1.5 rounded-lg border border-border-default bg-surface ' +
  'px-3.5 py-2 text-sm font-medium text-ink shadow-card transition-colors ' +
  'hover:border-border-strong hover:bg-elevated ' +
  'disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-surface'

/* ── Surfaces ──────────────────────────────────────────────── */

export function Card({
  children,
  className = '',
  padded = true,
}: {
  children: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <div
      className={`rounded-xl border border-border-subtle bg-surface shadow-card ${
        padded ? 'p-4' : ''
      } ${className}`}
    >
      {children}
    </div>
  )
}

/**
 * A card with a titled header.
 *
 * `blurb` is for the sentence that says what the figures in the panel mean.
 * It is a first-class slot rather than something each page bolts on, because
 * "show the workings" is the product's whole claim and a panel that drops the
 * explanation quietly walks it back.
 */
export function Panel({
  title,
  blurb,
  aside,
  children,
  className = '',
  bodyClassName = 'p-4',
}: {
  title: ReactNode
  blurb?: ReactNode
  aside?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section
      className={`overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-card ${className}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
          {blurb && <p className="mt-1 max-w-prose text-xs leading-relaxed text-muted">{blurb}</p>}
        </div>
        {aside}
      </header>
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

/* ── Page furniture ───────────────────────────────────────── */

export function PageHeader({
  eyebrow,
  title,
  blurb,
  actions,
}: {
  eyebrow?: string
  title: ReactNode
  blurb?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="u-eyebrow mb-2">{eyebrow}</p>}
        <h1 className="u-display text-title text-ink">{title}</h1>
        {blurb && <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">{blurb}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/**
 * An empty result.
 *
 * Always says what to do next rather than only what is missing - an empty
 * screen is an invitation to act, not a dead end.
 */
export function EmptyState({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border-default px-6 py-12 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint && <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-muted">{hint}</p>}
    </div>
  )
}

/**
 * The footnote under a figure-bearing panel.
 *
 * Small and quiet, but never omitted: it is where the derivation lives.
 */
export function Provenance({ children }: { children: ReactNode }) {
  return (
    <p className="max-w-3xl text-xs leading-relaxed text-dim">{children}</p>
  )
}

/* ── Tables ────────────────────────────────────────────────────
 * Class constants rather than wrapper components: the pages need to put
 * colSpan, sorting handlers and links on these elements, and a component that
 * forwarded all of that would be longer than the string it replaced. */

/* No min-width here. Every table needs a different one - the nine in this app
 * range from 380px to 840px - and a shared floor either lets a narrow table
 * scroll when it did not need to or lets a wide one crush its columns. Each
 * page appends its own. */
export const tableClass = 'w-full border-collapse text-sm'

/**
 * The header styling sits on the `<tr>`, not on `<thead>`, so the mono/uppercase
 * treatment inherits down into every `<th>` and the cell classes stay short.
 */
export const theadRowClass =
  'border-b border-border-default bg-elevated text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted'

export const thClass = 'px-3 py-2.5 font-medium whitespace-nowrap'
export const thNumClass = 'px-3 py-2.5 text-right font-medium whitespace-nowrap'

export const trClass =
  'border-b border-border-subtle transition-colors last:border-0 hover:bg-elevated'

export const tdClass = 'px-3 py-2.5 text-ink'

/**
 * A numeric cell. Right-aligned and tabular, which together are what make a
 * column of figures scannable - the decimal points land in one vertical line.
 * Muted by default: in a row of eight figures at most one is the point, and
 * that one gets `tdNumStrongClass`.
 */
export const tdNumClass = 'tnum px-3 py-2.5 text-right text-muted'
export const tdNumStrongClass = 'tnum px-3 py-2.5 text-right font-semibold text-ink'

/* ── Uncertainty ───────────────────────────────────────────────
 * The product's second channel for "trust this less". Not a colour, because
 * the colour it would want (amber) is indistinguishable from the red used for
 * below-par figures beside it. */

export function Uncertain({
  children,
  reason,
  className = '',
}: {
  children: ReactNode
  reason: string
  className?: string
}) {
  return (
    <span className={`uncertain ${className}`} title={reason}>
      {children}
      <span className="sr-only"> (low confidence: {reason})</span>
    </span>
  )
}
