const LABELS: Record<string, string> = {
  tests: 'Test',
  odis: 'ODI',
  t20is: 'T20I',
  psl: 'PSL',
}

const STYLES: Record<string, string> = {
  tests:
    'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300 ring-amber-600/20 dark:ring-amber-400/20',
  odis:
    'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300 ring-sky-600/20 dark:ring-sky-400/20',
  t20is:
    'bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-500/15 dark:text-fuchsia-300 ring-fuchsia-600/20 dark:ring-fuchsia-400/20',
  // Franchise cricket sits visually apart from the three international
  // formats rather than extending their sequence.
  psl:
    'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300 ring-emerald-600/20 dark:ring-emerald-400/20',
}

export function CompetitionBadge({ competition }: { competition: string }) {
  const style =
    STYLES[competition] ??
    'bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300 ring-slate-600/20'
  const label = LABELS[competition] ?? competition
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {label}
    </span>
  )
}
