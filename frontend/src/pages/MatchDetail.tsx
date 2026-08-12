import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { MatchDetail as MatchDetailType, MatchPerformer, TeamRef } from '../api/types'
import { CompetitionBadge } from '../components/CompetitionBadge'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { useGender } from '../gender/useGender'

function PerformerTable({ performers, team }: { performers: MatchPerformer[]; team: TeamRef }) {
  const teamPerformers = performers.filter((p) => p.team_id === team.team_id)
  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <h3 className="border-b border-slate-200 px-5 py-3 font-semibold text-slate-800 dark:border-slate-800 dark:text-slate-100">
        {team.name}
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
            <th className="py-2 pl-5">Player</th>
            <th className="py-2 text-right">Runs</th>
            <th className="py-2 text-right">Balls</th>
            <th className="py-2 pr-5 text-right">Wkts</th>
          </tr>
        </thead>
        <tbody>
          {teamPerformers.map((p) => (
            <tr key={p.player_name} className="border-b border-slate-100 last:border-0 dark:border-slate-800/50">
              <td className="py-2 pl-5 text-slate-700 dark:text-slate-200">{p.player_name}</td>
              <td className="py-2 text-right text-slate-600 dark:text-slate-300">
                {p.runs_scored}
                {p.dismissals === 0 && p.balls_faced > 0 ? '*' : ''}
              </td>
              <td className="py-2 text-right text-slate-500 dark:text-slate-400">{p.balls_faced || '-'}</td>
              <td className="py-2 pr-5 text-right text-slate-600 dark:text-slate-300">
                {p.balls_bowled > 0 ? `${p.wickets_taken}/${p.runs_conceded}` : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function MatchDetail() {
  const { slug } = useGender()
  const { matchId = '' } = useParams()
  const [match, setMatch] = useState<MatchDetailType | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Guards against a slower request for a previous `matchId` resolving
    // after a newer one and overwriting it with the wrong match's data.
    let cancelled = false
    setMatch(null)
    setError(null)
    api
      .matchDetail(matchId)
      .then((res) => {
        if (!cancelled) setMatch(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [matchId])

  if (error) return <ErrorMessage message={error} />
  if (!match) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/${slug}/matches`} className="text-sm text-emerald-600 hover:underline dark:text-emerald-400">
          &larr; All matches
        </Link>
        <div className="mt-2 flex items-center gap-3">
          <CompetitionBadge competition={match.competition_key} />
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {match.team1?.name} vs {match.team2?.name}
          </h1>
        </div>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {match.event_name && `${match.event_name} · `}
          {match.venue}, {match.city} &middot; {match.match_date_start}
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p className="text-lg font-semibold text-emerald-600 dark:text-emerald-400">
          {match.winner
            ? `${match.winner.name} won${match.win_by_runs ? ` by ${match.win_by_runs} runs` : ''}${
                match.win_by_wickets ? ` by ${match.win_by_wickets} wickets` : ''
              }`
            : (match.outcome_result ?? 'Result unknown')}
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-500 dark:text-slate-400 sm:grid-cols-3">
          <p>Toss: {match.toss_winner?.name} chose to {match.toss_decision}</p>
          {match.player_of_match && <p>Player of the Match: {match.player_of_match}</p>}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {match.team1 && <PerformerTable performers={match.performers} team={match.team1} />}
        {match.team2 && <PerformerTable performers={match.performers} team={match.team2} />}
      </div>
    </div>
  )
}
