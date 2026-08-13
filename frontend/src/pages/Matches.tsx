import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { MatchSummary, TeamSummary } from '../api/types'
import { CompetitionBadge } from '../components/CompetitionBadge'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { Flag } from '../components/Flag'
import { useGender } from '../gender/useGender'

const LIMIT = 25

// A match list isn't an aggregate, so "All" here really is everything --
// unlike Rankings, showing a Test and a PSL fixture side by side sums nothing.
const COMPETITIONS = [
  { value: '', label: 'All Competitions' },
  { value: 'tests', label: 'Tests' },
  { value: 'odis', label: 'ODIs' },
  { value: 't20is', label: 'T20Is' },
  { value: 'psl', label: 'PSL' },
]

const field = 'rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink'
const fieldLabel = 'font-mono text-[10px] uppercase tracking-[0.1em] text-muted'

export function Matches() {
  const { slug, apiGender } = useGender()
  const [competition, setCompetition] = useState('')
  const [teamId, setTeamId] = useState('')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [offset, setOffset] = useState(0)

  const [teams, setTeams] = useState<TeamSummary[]>([])
  const [matches, setMatches] = useState<MatchSummary[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // The filter is a select, so it needs every side rather than a page.
    api
      .teams(apiGender, undefined, { limit: 500 })
      .then((res) => setTeams(res.items))
      .catch(() => {})
  }, [apiGender])

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
      setOffset(0)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    // Guards against a slower request for previous filters resolving after
    // a newer one and overwriting it with stale results.
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .matches(apiGender, {
        competition: competition || undefined,
        team_id: teamId ? Number(teamId) : undefined,
        search: debouncedSearch || undefined,
        limit: LIMIT,
        offset,
      })
      .then((res) => {
        if (cancelled) return
        setMatches(res.items)
        setTotal(res.total)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [apiGender, competition, teamId, debouncedSearch, offset])

  return (
    <div className="space-y-5">
      <div>
        <h1 className="u-display text-title text-ink">Matches</h1>
        <p className="mt-1 text-sm text-muted">
          {total.toLocaleString()} matches, most recent first
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Competition</span>
          <select
            value={competition}
            onChange={(e) => {
              setCompetition(e.target.value)
              setOffset(0)
            }}
            className={field}
          >
            {COMPETITIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Team</span>
          <select
            value={teamId}
            onChange={(e) => {
              setTeamId(e.target.value)
              setOffset(0)
            }}
            className={field}
          >
            <option value="">All teams</option>
            {teams.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Search</span>
          <input
            type="text"
            placeholder="Venue or event"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`${field} w-56 placeholder:text-dim`}
          />
        </label>
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && matches.length === 0 && <LoadingSpinner />}

      {!error && matches.length > 0 && (
        <div className="scroll-x rounded-xl border border-border-subtle bg-surface shadow-card">
          <table className="w-full min-w-[720px] text-sm">
            <tbody>
              {matches.map((m) => (
                <tr
                  key={m.match_id}
                  className="border-b border-border-subtle last:border-0 hover:bg-elevated"
                >
                  <td className="px-4 py-2.5 align-top">
                    <CompetitionBadge competition={m.competition_key} />
                  </td>
                  <td className="tnum whitespace-nowrap px-3 py-2.5 align-top text-muted">
                    {m.match_date_start ?? '—'}
                  </td>
                  <td className="px-3 py-2.5">
                    <Link
                      to={`/${slug}/matches/${m.match_id}`}
                      className="font-medium text-ink hover:text-analytic-ink"
                    >
                      <Flag code={m.team1?.country_code} name={m.team1?.name} />{' '}
                      {m.team1?.name} v {m.team2?.name}{' '}
                      <Flag code={m.team2?.country_code} name={m.team2?.name} />
                    </Link>
                    <div className="mt-0.5 text-xs text-dim">{m.venue ?? 'Venue not recorded'}</div>
                  </td>
                  <td className="px-4 py-2.5 text-right align-top text-muted">
                    {m.winner ? `${m.winner.name} won` : (m.outcome_result ?? '—')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4">
            <Pagination total={total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        </div>
      )}

      {!loading && !error && matches.length === 0 && (
        <p className="rounded-xl border border-border-subtle bg-surface shadow-card px-4 py-6 text-sm text-muted">
          No matches match these filters.
        </p>
      )}
    </div>
  )
}
