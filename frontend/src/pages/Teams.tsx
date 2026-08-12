import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamSummary, TeamType } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { useGender } from '../gender/useGender'

// National sides and franchises are both "teams" but aren't comparable: a
// win % against Australia doesn't mean what a win % against Multan Sultans
// means. One kind at a time, the same way the app never mixes genders.
const TEAM_TYPES: { value: TeamType; label: string }[] = [
  { value: 'international', label: 'International' },
  { value: 'franchise', label: 'Franchise' },
]

export function Teams() {
  const { slug, apiGender } = useGender()
  const [teamType, setTeamType] = useState<TeamType>('international')
  const [teams, setTeams] = useState<TeamSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setTeams(null)
    setError(null)
    api
      .teams(apiGender, teamType)
      .then((res) => {
        if (!cancelled) setTeams(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [apiGender, teamType])

  if (error) return <ErrorMessage message={error} />

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Teams</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {teams ? `${teams.length} teams, ranked by matches played` : 'Loading…'}
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900">
          {TEAM_TYPES.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => setTeamType(t.value)}
              className={
                'rounded-md px-3 py-1.5 text-sm font-medium transition ' +
                (teamType === t.value
                  ? 'bg-emerald-600 text-white'
                  : 'text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white')
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
        <p className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
          No {teamType} teams in this dataset.
        </p>
      ) : (

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
              <th className="py-3 pl-5">#</th>
              <th className="py-3">Team</th>
              <th className="py-3 text-right">Matches</th>
              <th className="py-3 text-right">Won</th>
              <th className="py-3 text-right">Lost</th>
              <th className="py-3 text-right">Tied/NR</th>
              <th className="py-3 pr-5 text-right">Win %</th>
            </tr>
          </thead>
          <tbody>
            {teams.map((t, i) => (
              <tr key={t.team_id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800/50 dark:hover:bg-slate-800/40">
                <td className="py-2.5 pl-5 text-slate-400">{i + 1}</td>
                <td className="py-2.5">
                  <Link
                    to={`/${slug}/teams/${t.team_id}`}
                    className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                  >
                    {t.name}
                  </Link>
                </td>
                <td className="py-2.5 text-right text-slate-600 dark:text-slate-300">{t.matches}</td>
                <td className="py-2.5 text-right text-emerald-600 dark:text-emerald-400">{t.wins}</td>
                <td className="py-2.5 text-right text-red-500 dark:text-red-400">{t.losses}</td>
                <td className="py-2.5 text-right text-slate-500 dark:text-slate-400">{t.ties_or_no_result}</td>
                <td className="py-2.5 pr-5 text-right font-semibold text-slate-800 dark:text-slate-100">
                  {t.win_pct !== null ? `${t.win_pct}%` : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </div>
  )
}
