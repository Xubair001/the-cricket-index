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
          {/* `u-panel` and `u-note`, not ad-hoc size classes. Every panel in
              the app goes through here, so the scale propagates rather than
              being re-picked per page - which is how three different heading
              sizes ended up on adjacent cards. */}
          <h2 className="u-panel">{title}</h2>
          {blurb && <p className="u-note mt-1">{blurb}</p>}
        </div>
        {aside}
      </header>
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

/* ── Page furniture ───────────────────────────────────────── */

/**
 * A heading that groups several panels, with its own explanatory line.
 *
 * Exists because the alternative is every page inventing this: a flex row, a
 * bottom border, a hand-picked heading size and a caption class. Three pages had
 * three different versions sitting on the same scroll.
 */
export function SectionHeading({
  title,
  note,
  aside,
}: {
  title: ReactNode
  note?: ReactNode
  aside?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border-default pb-2">
      <h2 className="u-section">{title}</h2>
      {note && <p className="u-note text-xs">{note}</p>}
      {aside}
    </div>
  )
}

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
        <h1 className="u-title">{title}</h1>
        {blurb && <p className="u-note mt-2 max-w-2xl">{blurb}</p>}
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
/**
 * The note under a table that says how its figures were produced.
 *
 * Was `max-w-3xl`, which left it ending well short of the table above it and
 * reading as a stray paragraph rather than that table's own footnote. Now it
 * fills the column and is framed as a note, so it is skimmable: the label tells
 * a reader they can skip it, which is what makes it safe to keep.
 */
export function Provenance({ children }: { children: ReactNode }) {
  return (
    // A DISCLOSURE, not a paragraph. These notes carry the product's honesty
    // devices and are load-bearing, so they cannot be cut - but several ran past
    // 700 characters and a wall of small grey text at the foot of every page is
    // read by nobody, which defeats the purpose of writing it. Collapsed, the
    // page ends on one clear line; open, the whole explanation is there.
    //
    // `<details>` rather than a React toggle: it is keyboard accessible, works
    // before hydration, and is searchable by the browser's own find.
    <details className="group rounded-xl border border-border-subtle bg-elevated px-4 py-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-medium text-muted transition-colors hover:text-ink">
        How these figures are produced
        <span
          aria-hidden
          className="text-[10px] text-dim transition-transform group-open:rotate-90"
        >
          &#9656;
        </span>
      </summary>
      <div className="mt-2.5 border-t border-border-subtle pt-2.5 text-xs leading-relaxed text-muted">
        {children}
      </div>
    </details>
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
/**
 * Table cells were `px-3` with no edge inset, so the first and last columns sat
 * 12px from the card border and read as clipped. The inset is declared here
 * rather than on every page's cells: one place, and it cannot drift.
 */
export const tableClass =
  'w-full border-collapse text-sm ' +
  '[&_th:first-child]:pl-5 [&_td:first-child]:pl-5 ' +
  '[&_th:last-child]:pr-5 [&_td:last-child]:pr-5'

/**
 * The header styling sits on the `<tr>`, not on `<thead>`, so the mono/uppercase
 * treatment inherits down into every `<th>` and the cell classes stay short.
 */
export const theadRowClass =
  'border-b border-border-default bg-elevated text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted'

export const thClass = 'px-3 py-3 font-medium whitespace-nowrap'
export const thNumClass = 'px-3 py-3 text-right font-medium whitespace-nowrap'

export const trClass =
  'border-b border-border-subtle transition-colors last:border-0 hover:bg-elevated'

export const tdClass = 'px-3 py-3 text-ink'

/**
 * A numeric cell. Right-aligned and tabular, which together are what make a
 * column of figures scannable - the decimal points land in one vertical line.
 * Muted by default: in a row of eight figures at most one is the point, and
 * that one gets `tdNumStrongClass`.
 */
export const tdNumClass = 'tnum px-3 py-3 text-right text-muted'
export const tdNumStrongClass = 'tnum px-3 py-3 text-right font-semibold text-ink'

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
