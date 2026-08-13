const LABELS: Record<string, string> = {
  tests: 'Test',
  odis: 'ODI',
  t20is: 'T20I',
  psl: 'PSL',
}

/* Format badges are neutral chips, not semantic colour: green/red/amber carry
 * meaning elsewhere in the product (above baseline, below baseline, low
 * confidence) and must not be spent labelling a format. Franchise cricket is
 * the one distinction drawn, because it is the one that must never be read as
 * interchangeable with international cricket. */
const FRANCHISE = new Set(['psl'])

export function CompetitionBadge({ competition }: { competition: string }) {
  const label = LABELS[competition] ?? competition
  const style = FRANCHISE.has(competition)
    ? 'bg-analytic-dim text-analytic ring-analytic/30'
    : 'bg-elevated text-muted ring-border-default'
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] ring-1 ring-inset ${style}`}
      title={FRANCHISE.has(competition) ? 'Franchise cricket — never blended with international figures' : undefined}
    >
      {label}
    </span>
  )
}
