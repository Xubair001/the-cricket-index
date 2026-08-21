import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamSummary, TeamType } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { Flag } from '../components/Flag'
import { useGender } from '../gender/useGender'
import { useScope } from '../scope/scope'
import { useFilters } from '../state/useFilters'
import { percent, plural } from '../format'
import {
  tableClass,
  tdClass,
  thClass,
  theadRowClass,
  trClass,
} from '../components/ui'

// National sides and franchises are both "teams" but aren't comparable: a
// win % against Australia doesn't mean what a win % against Multan Sultans
// means. One kind at a time, the same way the app never mixes genders.
const LIMIT = 25

const TEAM_TYPES: { value: TeamType; label: string }[] = [
  { value: 'international', label: 'International' },
  { value: 'franchise', label: 'Franchise' },
]

export function Teams() {
  const { slug, apiGender } = useGender()
  // Seeded from the global family switch rather than hardcoded to
  // 'international'. team_type and competition type are the same partition
  // seen from two sides - `shared.TEAM_TYPE_BY_COMPETITION_TYPE` maps one to
  // the other on the ingestion side - so a reader who has put the app into
  // Leagues should land on franchises. Still local state afterwards, because
  // this page's tabs are a legitimate way to look at the other set without
  // changing the whole app's mode.
  const { family } = useScope()
  const f = useFilters()
  // A URL naming a type wins over the family default, so a shared link to the
  // franchise list opens on franchises. Same rule the scope switch follows.
  const teamType: TeamType =
    f.get('type') === 'franchise'
      ? 'franchise'
      : f.get('type') === 'international'
        ? 'international'
        : family === 'league'
          ? 'franchise'
          : 'international'
  const offset = f.int('offset', 0)
  const [teams, setTeams] = useState<TeamSummary[] | null>(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setTeams(null)
    setError(null)
    api
      .teams(apiGender, teamType, { limit: LIMIT, offset })
      .then((res) => {
        if (cancelled) return
        setTeams(res.items)
        setTotal(res.total)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [apiGender, teamType, offset])

  // Follow the app-wide family switch, but only when it actually MOVES. Writing
  // on mount as well would overwrite a shared `?type=` with the family default,
  // which is the opposite of the rule above.
  const previousFamily = useRef(family)
  useEffect(() => {
    if (previousFamily.current === family) return
    previousFamily.current = family
    f.set({ type: family === 'league' ? 'franchise' : 'international' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [family])

  if (error) return <ErrorMessage message={error} />

  const th = 'px-3 py-2.5 text-right'
  const td = 'tnum px-3 py-2.5 text-right text-muted'

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="u-display text-title text-ink">Teams</h1>
          <p className="mt-1 text-sm text-muted">
            {teams ? `${plural(total, `${teamType} team`, `${teamType} teams`)}, by matches played` : 'Loading…'}
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-border-default bg-surface p-0.5">
          {TEAM_TYPES.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => {
                f.set({ type: t.value })
              }}
              className={
                'rounded-md px-3 py-1.5 text-sm font-medium transition-colors ' +
                (teamType === t.value ? 'bg-elevated text-ink' : 'text-muted hover:text-ink')
              }
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {!teams ? (
        <LoadingSpinner />
      ) : teams.length === 0 ? (
        <p className="rounded-xl border border-border-subtle bg-surface shadow-card px-4 py-6 text-sm text-muted">
          No {teamType} teams in this dataset.
        </p>
      ) : (
        <div className="scroll-x rounded-xl border border-border-subtle bg-surface shadow-card">
          <table className={`${tableClass} min-w-[620px]`}>
            <thead>
              <tr className={theadRowClass}>
                <th className="px-4 py-2.5">#</th>
                <th className={thClass}>Team</th>
                <th className={th}>Matches</th>
                <th className={th}>Won</th>
                <th className={th}>Lost</th>
                <th className={th}>Tied/NR</th>
                <th className="px-4 py-2.5 text-right">Win %</th>
              </tr>
            </thead>
            <tbody>
              {/* Wins and losses render neutrally. Colouring a whole column
                  green or red carries no per-row information - every cell in it
                  would be the same colour - and green/red are reserved for
                  above/below baseline elsewhere. Win % is the comparative
                  figure, so that is the one given weight. */}
              {teams.map((t, i) => (
                <tr
                  key={t.team_id}
                  className={trClass}
                >
                  <td className="tnum px-4 py-2.5 text-dim">{offset + i + 1}</td>
                  <td className={tdClass}>
                    <Link
                      to={`/${slug}/teams/${t.team_id}`}
                      className="inline-flex items-center gap-2 font-medium text-ink hover:text-analytic-ink"
                    >
                      <Flag code={t.country_code} name={t.name} />
                      {t.name}
                    </Link>
                  </td>
                  <td className={td}>{t.matches.toLocaleString()}</td>
                  <td className={td}>{t.wins}</td>
                  <td className={td}>{t.losses}</td>
                  <td className={td}>{t.ties_or_no_result}</td>
                  <td className="tnum px-4 py-2.5 text-right font-semibold text-ink">
                    {percent(t.win_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4">
            <Pagination total={total} limit={LIMIT} offset={offset} onChange={(o) => f.keep({ offset: o })} />
          </div>
        </div>
      )}

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        Win % counts decided matches only; ties and no-results sit in their own column rather than
        being folded into either side. International and franchise sides are listed separately
        because their records are not comparable.
      </p>
    </div>
  )
}
