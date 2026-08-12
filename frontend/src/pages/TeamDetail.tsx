import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamDetail as TeamDetailType } from '../api/types'
import { CompetitionBadge } from '../components/CompetitionBadge'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { StatCard } from '../components/StatCard'
import { useGender } from '../gender/useGender'

export function TeamDetail() {
  const { slug } = useGender()
  const { teamId = '' } = useParams()
  const [team, setTeam] = useState<TeamDetailType | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Guards against a slower request for a previous team resolving after
    // a newer one and overwriting it with the wrong team's data.
    let cancelled = false
    setTeam(null)
    setError(null)
    api
      .teamDetail(Number(teamId))
      .then((res) => {
        if (!cancelled) setTeam(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [teamId])

  if (error) return <ErrorMessage message={error} />
  if (!team) return <LoadingSpinner />

  return (
    <div className="space-y-8">
      <div>
        <Link to={`/${slug}/teams`} className="text-sm text-emerald-600 hover:underline dark:text-emerald-400">
          &larr; All teams
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-slate-900 dark:text-white">{team.name}</h1>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Matches" value={team.matches} accent="emerald" />
        <StatCard label="Won" value={team.wins} accent="sky" />
        <StatCard label="Lost" value={team.losses} accent="amber" />
        <StatCard label="Win %" value={team.win_pct !== null ? `${team.win_pct}%` : '-'} accent="fuchsia" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="border-b border-slate-200 px-5 py-3 font-semibold text-slate-800 dark:border-slate-800 dark:text-slate-100">
            Top Run Scorers
          </h2>
          <table className="w-full text-sm">
            <tbody>
              {team.top_run_scorers.map((p) => (
                <tr key={p.player_identifier ?? p.player_name} className="border-b border-slate-100 last:border-0 dark:border-slate-800/50">
                  <td className="py-2.5 pl-5">
                    <Link
                      to={p.player_identifier ? `/${slug}/players/${p.player_identifier}` : '#'}
                      className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                    >
                      {p.player_name}
                    </Link>
                  </td>
                  <td className="py-2.5 text-right font-semibold text-slate-700 dark:text-slate-200">{p.runs}</td>
                  <td className="py-2.5 pr-5 text-right text-slate-400">avg {p.average ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="border-b border-slate-200 px-5 py-3 font-semibold text-slate-800 dark:border-slate-800 dark:text-slate-100">
            Top Wicket Takers
          </h2>
          <table className="w-full text-sm">
            <tbody>
              {team.top_wicket_takers.map((p) => (
                <tr key={p.player_identifier ?? p.player_name} className="border-b border-slate-100 last:border-0 dark:border-slate-800/50">
                  <td className="py-2.5 pl-5">
                    <Link
                      to={p.player_identifier ? `/${slug}/players/${p.player_identifier}` : '#'}
                      className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                    >
                      {p.player_name}
                    </Link>
                  </td>
                  <td className="py-2.5 text-right font-semibold text-slate-700 dark:text-slate-200">{p.wickets}</td>
                  <td className="py-2.5 pr-5 text-right text-slate-400">avg {p.average ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 className="border-b border-slate-200 px-5 py-3 font-semibold text-slate-800 dark:border-slate-800 dark:text-slate-100">
          Recent Matches
        </h2>
        <table className="w-full text-sm">
          <tbody>
            {team.recent_matches.map((m) => (
              <tr key={m.match_id} className="border-b border-slate-100 last:border-0 dark:border-slate-800/50">
                <td className="py-2.5 pl-5">
                  <CompetitionBadge competition={m.competition_key} />
                </td>
                <td className="py-2.5 text-slate-600 dark:text-slate-300">{m.match_date_start}</td>
                <td className="py-2.5">
                  <Link to={`/${slug}/matches/${m.match_id}`} className="hover:text-emerald-600 dark:hover:text-emerald-400">
                    {m.team1?.name} vs {m.team2?.name}
                  </Link>
                </td>
                <td className="py-2.5 pr-5 text-right text-slate-600 dark:text-slate-300">
                  {m.winner ? `${m.winner.name} won` : m.outcome_result ?? '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
