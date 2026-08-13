import type { PlayerStatus } from '../api/types'

/**
 * Playing status, worded to match exactly what the data supports.
 *
 * There is no "Retired" badge for a player who simply stopped appearing --
 * that state renders as "Last played YYYY", because a gap covers retirement,
 * injury, being dropped, and uncovered domestic cricket alike. "Retired" shows
 * only when a source says so, and says which source on hover.
 */
const STYLES: Record<string, string> = {
  active:
    'bg-emerald-100 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-400/20',
  retired:
    'bg-slate-200 text-slate-700 ring-slate-500/20 dark:bg-slate-500/20 dark:text-slate-300 dark:ring-slate-400/20',
  inactive:
    'bg-amber-100 text-amber-800 ring-amber-600/20 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-400/20',
}

function year(date: string | null): string | null {
  return date ? date.slice(0, 4) : null
}

function statusLabel(status: PlayerStatus): string {
  if (status.state === 'retired') {
    const when = year(status.retired_on) ?? year(status.deceased_on)
    return when ? `Retired ${when}` : 'Retired'
  }
  if (status.state === 'active') return 'Active'
  const last = year(status.last_played)
  return last ? `Last played ${last}` : 'No recorded matches'
}

function tooltip(status: PlayerStatus): string {
  if (status.state === 'retired') {
    if (status.retired_on) {
      return `Retirement date from ${status.source ?? 'an external source'}.`
    }
    return `Recorded as deceased (${status.deceased_on}) by ${status.source ?? 'an external source'}.`
  }
  if (status.state === 'active') {
    return `Appeared in a match within the last year of this dataset (last: ${status.last_played}).`
  }
  return (
    `No appearances since ${status.last_played} in this dataset. ` +
    `That may mean retirement, injury, or cricket this dataset doesn't cover — ` +
    `no source confirms which, so none is claimed.`
  )
}

export function StatusBadge({ status }: { status: PlayerStatus | null }) {
  if (!status) return null
  return (
    <span
      title={tooltip(status)}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
        STYLES[status.state] ?? STYLES.inactive
      }`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full ${
          status.state === 'active'
            ? 'bg-emerald-500'
            : status.state === 'retired'
              ? 'bg-slate-400'
              : 'bg-amber-500'
        }`}
      />
      {statusLabel(status)}
    </span>
  )
}
