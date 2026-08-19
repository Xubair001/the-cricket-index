import { createContext, useContext, useEffect } from 'react'
import type { CompetitionInfo } from '../api/types'

/**
 * The international / league switch.
 *
 * This exists because competition type is a hard partition in this schema, in
 * exactly the way gender is. `teams` are keyed by (name, gender, team_type),
 * rankings are confined to one competition type at a time, and a figure that
 * blended a player's Test runs with their PSL runs is a number no cricket
 * source publishes. The backend has enforced that from the start; the client
 * did not, and offered a single flat dropdown reading
 *
 *     All Internationals | Tests | ODIs | T20Is | PSL
 *
 * copy-pasted into five pages. That list crosses the partition mid-dropdown,
 * and its blank default silently means internationals - so a reader who picked
 * "PSL" had changed families without being told, and a reader who picked
 * nothing did not know which family they were in.
 *
 * So the family is now a switch at the top of the app, beside Men's/Women's,
 * and a page's competition control only ever offers competitions from the
 * family currently selected.
 *
 * WHY NOT A PATH PREFIX, as gender is: gender is in the URL because a link to a
 * player is meaningless without it - identifiers differ between the two. A
 * competition family is a lens over the same rows rather than a different set
 * of them, and every scope-sensitive page already carries its chosen
 * competition in its own query string, so a shared link is already precise.
 * Putting it in the path would have meant editing 48 link sites across 24
 * files to gain nothing a reader can see.
 */

export type ScopeFamily = 'international' | 'league'

/** The API's own `competition_type`, so a client never maps a label to a value. */
export const FAMILY_COMPETITION_TYPE: Record<ScopeFamily, string> = {
  international: 'international',
  league: 'domestic_league',
}

export const COMPETITION_TYPE_FAMILY: Record<string, ScopeFamily> = {
  international: 'international',
  domestic_league: 'league',
}

export const FAMILY_LABEL: Record<ScopeFamily, string> = {
  international: 'International',
  league: 'Leagues',
}

/** The blank option in a competition dropdown, named for the family it means. */
export const FAMILY_ALL_LABEL: Record<ScopeFamily, string> = {
  international: 'All Internationals',
  league: 'All Leagues',
}

const STORAGE_KEY = 'cricket-dashboard-scope'

export type ScopeValue = {
  family: ScopeFamily
  setFamily: (family: ScopeFamily) => void
  /** Pass as `competition_type` when no specific competition is chosen. */
  competitionType: string
  /** Competitions in the current family, richest first. */
  competitions: CompetitionInfo[]
  /** Every competition, both families. Needed to tell which family a key is in. */
  allCompetitions: CompetitionInfo[]
  /** The family a competition key belongs to, or null while unknown. */
  familyOf: (key: string) => ScopeFamily | null
  loading: boolean
}

export const ScopeContext = createContext<ScopeValue | null>(null)

export function storedFamily(): ScopeFamily {
  if (typeof localStorage === 'undefined') return 'international'
  return localStorage.getItem(STORAGE_KEY) === 'league' ? 'league' : 'international'
}

export function persistFamily(next: ScopeFamily): void {
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // Private browsing. The switch still works for this session.
  }
}

export function useScope(): ScopeValue {
  const ctx = useContext(ScopeContext)
  if (!ctx) throw new Error('useScope must be used inside a ScopeProvider')
  return ctx
}

/**
 * A page's competition selection, kept consistent with the family switch.
 *
 * When a page asks for a competition from the OTHER family, the switch follows
 * it rather than the competition being dropped. That direction is deliberate:
 * the only way to hold an out-of-family competition is for a URL to name it -
 * a page's dropdown only ever offers the current family - and a URL naming
 * `competition=psl` is a more specific instruction than a preference left in
 * localStorage weeks ago. A shared link to a PSL board should show the PSL
 * board, with the switch visibly moved to Leagues, not a notice explaining why
 * it will not.
 *
 * What must never happen is the two disagreeing silently: franchise figures
 * under an international heading is the exact conflation the switch exists to
 * prevent. Adopting the URL's family keeps them in step.
 */
export function useScopedCompetition(competition: string): {
  competition: string
  competitionType: string | undefined
  options: { value: string; label: string }[]
} {
  const { family, competitions, familyOf, loading, setFamily } = useScope()
  // While the competition list is still loading familyOf cannot answer, so
  // nothing is adopted and nothing is dropped.
  const known = loading ? null : familyOf(competition)
  const mismatched = competition !== '' && known !== null && known !== family

  useEffect(() => {
    if (mismatched && known) setFamily(known)
  }, [mismatched, known, setFamily])

  // Until the switch catches up, send the family the competition belongs to,
  // so the first render is already correct rather than briefly wrong.
  const effectiveFamily = mismatched && known ? known : family
  return {
    competition,
    // Only sent when no specific competition is chosen. A competition key is
    // already narrower than its type, and sending both would be redundant.
    competitionType: competition ? undefined : FAMILY_COMPETITION_TYPE[effectiveFamily],
    options: [
      { value: '', label: FAMILY_ALL_LABEL[effectiveFamily] },
      ...(mismatched && known
        ? allCompetitionsIn(competitions, known)
        : competitions
      ).map((c) => ({ value: c.key, label: c.display_name })),
    ],
  }
}

/** Competitions of one family, from the full list rather than the filtered one. */
function allCompetitionsIn(current: CompetitionInfo[], family: ScopeFamily): CompetitionInfo[] {
  // During the single render before setFamily lands, `current` still holds the
  // old family. Returning it would flash the wrong options, so the caller's
  // list is only used once the two agree; here we simply return nothing rather
  // than guess, and the next render has the right list.
  return current.filter(
    (c) => COMPETITION_TYPE_FAMILY[c.type] === family
  )
}
