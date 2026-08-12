interface StatCardProps {
  label: string
  value: string | number
  accent?: 'emerald' | 'sky' | 'amber' | 'fuchsia'
  subtext?: string
}

const ACCENTS: Record<string, string> = {
  emerald: 'text-emerald-600 dark:text-emerald-400',
  sky: 'text-sky-600 dark:text-sky-400',
  amber: 'text-amber-600 dark:text-amber-400',
  fuchsia: 'text-fuchsia-600 dark:text-fuchsia-400',
}

export function StatCard({ label, value, accent = 'emerald', subtext }: StatCardProps) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</p>
      <p className={`mt-2 text-3xl font-semibold tracking-tight ${ACCENTS[accent]}`}>{value}</p>
      {subtext && <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">{subtext}</p>}
    </div>
  )
}
