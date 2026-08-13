import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { IccRankingTable, IccTeamRankingTable } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { useGender } from '../gender/useGender'

/**
 * ICC's own published ratings — distinct from /rankings, which this project
 * computes from ball-by-ball data. The page says so explicitly, because two
 * pages of "rankings" with different provenance is exactly how a reader ends up
 * quoting a derived number as an official one.
 *
 * ICC keys women's tables with a 'w' suffix on the format ('odiw-batting'), and
 * publishes no women's Test ranking at all.
 */
const DISCIPLINES = [
  { value: 'batting', label: 'Batting' },
  { value: 'bowling', label: 'Bowling' },
  { value: 'allrounder', label: 'All-rounder' },
  { value: 'team', label: 'Team' },
]

const FORMATS = [
  { value: 'test', label: 'Test' },
  { value: 'odi', label: 'ODI' },
  { value: 't20', label: 'T20I' },
]

export function IccRankings() {
  const { slug, apiGender } = useGender()
  const [format, setFormat] = useState('test')
  const [discipline, setDiscipline] = useState('batting')
  const [available, setAvailable] = useState<{ players: string[]; teams: string[] } | null>(null)
  const [players, setPlayers] = useState<IccRankingTable | null>(null)
  const [teams, setTeams] = useState<IccTeamRankingTable | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Women's tables carry a 'w' suffix on the format segment.
  const rankType = useMemo(
    () => `${format}${apiGender === 'female' ? 'w' : ''}-${discipline}`,
    [format, discipline, apiGender]
  )

  useEffect(() => {
    api.iccRankTypes().then(setAvailable).catch((e) => setError(String(e)))
  }, [])

  const known = available
    ? [...available.players, ...available.teams].includes(rankType)
    : true
  // ICC publishes no women's Test rankings — say so rather than showing an error.
  const womensTest = apiGender === 'female' && format === 'test'

  useEffect(() => {
    // Don't request a table we already know doesn't exist: it would 404 every
    // time a woman's Test ranking is selected, purely to render a message the
    // component can produce on its own.
    if (womensTest) {
      setPlayers(null)
      setTeams(null)
      setLoading(false)
      setError(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setPlayers(null)
    setTeams(null)
    const request =
      discipline === 'team'
        ? api.iccTeamRanking(rankType).then((t) => !cancelled && setTeams(t))
        : api.iccPlayerRanking(rankType).then((t) => !cancelled && setPlayers(t))
    request
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [rankType, discipline, womensTest])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">ICC Rankings</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Official ratings published by the ICC, refreshed daily. These are not computed by this
          site — for figures derived from ball-by-ball data see{' '}
          <Link to={`/${slug}/rankings`} className="text-emerald-600 hover:underline dark:text-emerald-400">
            Rankings
          </Link>
          .
        </p>
      </div>

      <div className="flex flex-wrap gap-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          Format
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          >
            {FORMATS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          Discipline
          <select
            value={discipline}
            onChange={(e) => setDiscipline(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          >
            {DISCIPLINES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {womensTest ? (
        <p className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
          The ICC does not publish women's Test rankings. Try ODI or T20I.
        </p>
      ) : loading ? (
        <LoadingSpinner />
      ) : error && known ? (
        <ErrorMessage message={error} />
      ) : error ? (
        <p className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
          No ICC data stored for this combination yet.
        </p>
      ) : (
        <>
          {(players || teams) && (
            <p className="text-xs text-slate-400">
              Published {(players ?? teams)!.rank_date}
              {(players ?? teams)!.fetched_at &&
                ` · fetched ${(players ?? teams)!.fetched_at!.slice(0, 10)}`}
            </p>
          )}

          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
                  <th className="py-3 pl-5">Rank</th>
                  <th className="py-3">{discipline === 'team' ? 'Team' : 'Player'}</th>
                  {discipline !== 'team' && <th className="py-3">Country</th>}
                  <th className="py-3 pr-5 text-right">Rating</th>
                  {discipline !== 'team' && <th className="py-3 pr-5">Career best</th>}
                </tr>
              </thead>
              <tbody>
                {players?.rows.map((r) => (
                  <tr
                    key={`${r.position}-${r.player_name}`}
                    className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800/50 dark:hover:bg-slate-800/40"
                  >
                    <td className="py-2.5 pl-5 text-slate-400">{r.position}</td>
                    <td className="py-2.5 font-medium text-slate-800 dark:text-slate-100">
                      {/* Only confidently-matched entries become links. An
                          unmatched name is still shown -- it's ICC's data and
                          it's real -- but is not attached to a profile. */}
                      {r.player_identifier ? (
                        <Link
                          to={`/${slug}/players/${r.player_identifier}`}
                          className="hover:text-emerald-600 dark:hover:text-emerald-400"
                        >
                          {r.player_name}
                        </Link>
                      ) : (
                        <span title="No confident match to a player in this dataset">
                          {r.player_name}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 text-slate-500 dark:text-slate-400">{r.country ?? '—'}</td>
                    <td className="py-2.5 pr-5 text-right font-semibold text-slate-800 dark:text-slate-100">
                      {r.points ?? '—'}
                    </td>
                    <td className="py-2.5 pr-5 text-xs text-slate-400">{r.career_best ?? '—'}</td>
                  </tr>
                ))}
                {teams?.rows.map((r) => (
                  <tr
                    key={`${r.position}-${r.team_name}`}
                    className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800/50 dark:hover:bg-slate-800/40"
                  >
                    <td className="py-2.5 pl-5 text-slate-400">{r.position}</td>
                    <td className="py-2.5 font-medium text-slate-800 dark:text-slate-100">
                      {r.team_id ? (
                        <Link
                          to={`/${slug}/teams/${r.team_id}`}
                          className="hover:text-emerald-600 dark:hover:text-emerald-400"
                        >
                          {r.team_name}
                        </Link>
                      ) : (
                        r.team_name
                      )}
                    </td>
                    <td className="py-2.5 pr-5 text-right font-semibold text-slate-800 dark:text-slate-100">
                      {r.points ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
