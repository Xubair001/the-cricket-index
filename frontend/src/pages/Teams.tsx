import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamSummary } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { useGender } from '../gender/useGender'

export function Teams() {
  const { slug, apiGender } = useGender()
  const [teams, setTeams] = useState<TeamSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setTeams(null)
    setError(null)
    api
      .teams(apiGender)
      .then((res) => {
        if (!cancelled) setTeams(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [apiGender])

  if (error) return <ErrorMessage message={error} />
  if (!teams) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Teams</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {teams.length} teams, ranked by matches played
        </p>
      </div>

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
    </div>
  )
}
