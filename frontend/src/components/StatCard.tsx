interface StatCardProps {
  label: string
  value: string | number
  /* Retained so existing callers keep working. Semantic colour is reserved for
   * meaning (above/below baseline, uncertainty) rather than decoration, so a
   * plain KPI renders in ink regardless of which accent it asks for. */
  accent?: 'emerald' | 'sky' | 'amber' | 'fuchsia'
  subtext?: string
}

/**
 * A single figure with its label.
 *
 * The figure is set in the display face because it is the thing being read —
 * everything else on the card is apparatus. That is also why the label sits
 * above rather than below: the reader needs to know what they are looking at
 * before the number means anything.
 */
export function StatCard({ label, value, subtext }: StatCardProps) {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-card">
      <p className="u-eyebrow">{label}</p>
      <p className="u-display tnum mt-2 text-2xl text-ink">{value}</p>
      {subtext && <p className="mt-1 text-xs leading-relaxed text-dim">{subtext}</p>}
    </div>
  )
}
