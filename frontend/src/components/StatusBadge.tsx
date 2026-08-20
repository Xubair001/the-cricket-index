import type { PlayerStatus } from '../api/types'

/**
 * Playing status, worded to match exactly what the data supports.
 *
 * There is no "Retired" badge for a player who simply stopped appearing --
 * that state renders as "Last played YYYY", because a gap covers retirement,
 * injury, being dropped, and uncovered domestic cricket alike. "Retired" shows
 * only when a source says so, and says which source on hover.
 */
/* The -ink tier throughout: these are 12px labels, and the mark tier is
 * stepped for fills rather than for text. */
const STYLES: Record<string, string> = {
  active: 'bg-positive-dim text-positive-ink ring-positive/25',
  // Sourced fact, stated plainly -- neutral rather than semantic, because
  // being retired is not a judgement about the player.
  retired: 'bg-elevated text-muted ring-border-default',
  // Amber is the product's uncertainty colour, which is exactly right here:
  // "last played 2019" is an observation, not a conclusion about why. Safe as
  // a hue in this one place because the badge is isolated -- the amber/red
  // confusion the rest of the product designs around only bites when the two
  // sit in adjacent columns of the same row.
  inactive: 'bg-warning-dim text-warning-ink ring-warning/25',
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
    `That may mean retirement, injury, or cricket this dataset doesn't cover - ` +
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
            ? 'bg-positive'
            : status.state === 'retired'
              ? 'bg-muted'
              : 'bg-warning'
        }`}
      />
      {statusLabel(status)}
    </span>
  )
}
