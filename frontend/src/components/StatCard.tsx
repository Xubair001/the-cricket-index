interface StatCardProps {
  label: string
  value: string | number
  /* Retained so existing callers keep working. Semantic colour is reserved for
   * meaning (above/below baseline, uncertainty) rather than decoration, so a
   * plain KPI renders in ink regardless of which accent it asks for. */
  accent?: 'emerald' | 'sky' | 'amber' | 'fuchsia'
  subtext?: string
}

export function StatCard({ label, value, subtext }: StatCardProps) {
  return (
    <div className="rounded-lg border border-border-default bg-surface p-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">{label}</p>
      <p className="tnum mt-1.5 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      {subtext && <p className="mt-1 text-xs text-dim">{subtext}</p>}
    </div>
  )
}
