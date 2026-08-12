import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { MatchSummary, TeamSummary } from '../api/types'
import { CompetitionBadge } from '../components/CompetitionBadge'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
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
    api.teams(apiGender).then(setTeams).catch(() => {})
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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Matches</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {total.toLocaleString()} matches, most recent first
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <select
          value={competition}
          onChange={(e) => {
            setCompetition(e.target.value)
            setOffset(0)
          }}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        >
          {COMPETITIONS.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <select
          value={teamId}
          onChange={(e) => {
            setTeamId(e.target.value)
            setOffset(0)
          }}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        >
          <option value="">All Teams</option>
          {teams.map((t) => (
            <option key={t.team_id} value={t.team_id}>
              {t.name}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Search venue, event..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        />
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && matches.length === 0 && <LoadingSpinner />}

      {!error && matches.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <tbody>
              {matches.map((m) => (
                <tr key={m.match_id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800/50 dark:hover:bg-slate-800/40">
                  <td className="py-2.5 pl-5">
                    <CompetitionBadge competition={m.competition_key} />
                  </td>
                  <td className="whitespace-nowrap py-2.5 text-slate-500 dark:text-slate-400">{m.match_date_start}</td>
                  <td className="py-2.5">
                    <Link
                      to={`/${slug}/matches/${m.match_id}`}
                      className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                    >
                      {m.team1?.name} vs {m.team2?.name}
                    </Link>
                    <div className="text-xs text-slate-400">{m.venue}</div>
                  </td>
                  <td className="py-2.5 pr-5 text-right text-slate-600 dark:text-slate-300">
                    {m.winner ? `${m.winner.name} won` : (m.outcome_result ?? '-')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-5">
            <Pagination total={total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        </div>
      )}

      {!loading && !error && matches.length === 0 && (
        <p className="text-sm text-slate-500 dark:text-slate-400">No matches found.</p>
      )}
    </div>
  )
}
