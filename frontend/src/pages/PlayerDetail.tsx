import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { PlayerDetail as PlayerDetailType } from '../api/types'
import { CompetitionBadge } from '../components/CompetitionBadge'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { useGender } from '../gender/useGender'

export function PlayerDetail() {
  const { slug } = useGender()
  const { identifier = '' } = useParams()
  const [player, setPlayer] = useState<PlayerDetailType | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Guards against a slower request for a previous `identifier` resolving
    // after a newer one and overwriting it with the wrong player's data.
    let cancelled = false
    setPlayer(null)
    setError(null)
    api
      .playerDetail(identifier)
      .then((res) => {
        if (!cancelled) setPlayer(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [identifier])

  if (error) return <ErrorMessage message={error} />
  if (!player) return <LoadingSpinner />

  const bio = player.bio
  const hasAnyBio = bio.date_of_birth || bio.birth_place || bio.nationality

  return (
    <div className="space-y-8">
      <div>
        <Link to={`/${slug}/players`} className="text-sm text-emerald-600 hover:underline dark:text-emerald-400">
          &larr; All players
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-slate-900 dark:text-white">{player.name}</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {player.teams.map((t) => t.name).join(', ')}
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Bio</h3>
        {hasAnyBio ? (
          <dl className="grid grid-cols-2 gap-y-2 text-sm sm:grid-cols-3">
            <BioPair label="Date of Birth" value={bio.date_of_birth} />
            <BioPair label="Birthplace" value={bio.birth_place} />
            <BioPair label="Nationality" value={bio.nationality} />
          </dl>
        ) : (
          <p className="text-sm text-slate-400">Not available</p>
        )}
      </div>

      <div className="space-y-4">
        {player.by_competition.map((c) => (
          <div key={c.competition_key} className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center gap-2 border-b border-slate-200 px-5 py-3 dark:border-slate-800">
              <CompetitionBadge competition={c.competition_key} />
              <span className="text-sm text-slate-500 dark:text-slate-400">{c.matches} matches</span>
            </div>
            <div className="grid grid-cols-1 divide-y divide-slate-100 sm:grid-cols-2 sm:divide-x sm:divide-y-0 dark:divide-slate-800">
              <div className="p-5">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Batting</h3>
                <dl className="grid grid-cols-2 gap-y-2 text-sm sm:grid-cols-3">
                  <StatPair label="Runs" value={c.runs} />
                  <StatPair label="Average" value={c.batting_average ?? '-'} />
                  <StatPair label="Strike Rate" value={c.strike_rate ?? '-'} />
                  <StatPair label="Balls Faced" value={c.balls_faced} />
                  <StatPair label="4s" value={c.fours} />
                  <StatPair label="6s" value={c.sixes} />
                </dl>
              </div>
              <div className="p-5">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Bowling</h3>
                {c.wickets > 0 || c.balls_bowled > 0 ? (
                  <dl className="grid grid-cols-2 gap-y-2 text-sm sm:grid-cols-3">
                    <StatPair label="Wickets" value={c.wickets} />
                    <StatPair label="Average" value={c.bowling_average ?? '-'} />
                    <StatPair label="Economy" value={c.economy ?? '-'} />
                    <StatPair label="Runs Conceded" value={c.runs_conceded} />
                  </dl>
                ) : (
                  <p className="text-sm text-slate-400">Did not bowl</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 className="border-b border-slate-200 px-5 py-3 font-semibold text-slate-800 dark:border-slate-800 dark:text-slate-100">
          Recent Matches
        </h2>
        <table className="w-full text-sm">
          <tbody>
            {player.recent_matches.map((m) => (
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

function StatPair({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-slate-400">{label}</dt>
      <dd className="font-semibold text-slate-800 dark:text-slate-100">{value}</dd>
    </div>
  )
}

function BioPair({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-slate-400">{label}</dt>
      <dd className="font-semibold text-slate-800 dark:text-slate-100">{value ?? 'Not available'}</dd>
    </div>
  )
}
