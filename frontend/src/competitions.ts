/**
 * Competition display names.
 *
 * Its own module rather than an export from `CompetitionBadge.tsx`, because a
 * file that exports both a component and a plain function loses fast refresh -
 * and because more than one place needs the label: the badge, and prose like
 * "Within ODI cricket" on a splits panel.
 *
 * Falls through to the raw key on anything unknown. That is deliberate and is
 * the same contract `app/validation.py` keeps on the server: competition keys
 * are validated against the `competitions` table rather than hardcoded, so
 * ingesting a new league stays a data change. A missing entry here costs a
 * prettier label, never a broken page.
 */
const LABELS: Record<string, string> = {
  tests: 'Test',
  odis: 'ODI',
  t20is: 'T20I',
  psl: 'PSL',
}

export function competitionLabel(competition: string): string {
  return LABELS[competition] ?? competition
}

/** Franchise cricket, which must never read as interchangeable with
 *  international cricket. The one distinction the badge draws in colour. */
export const FRANCHISE = new Set(['psl'])
