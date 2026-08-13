import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { IccRankingTable, IccTeamRankingTable } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
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

const LIMIT = 25

const FORMATS = [
  { value: 'test', label: 'Test' },
  { value: 'odi', label: 'ODI' },
  { value: 't20', label: 'T20I' },
]

const field = 'rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink'
const fieldLabel = 'font-mono text-[10px] uppercase tracking-[0.1em] text-muted'
const notice = 'rounded-lg border border-border-default bg-surface px-4 py-6 text-sm text-muted'

export function IccRankings() {
  const { slug, apiGender } = useGender()
  const [format, setFormat] = useState('test')
  const [discipline, setDiscipline] = useState('batting')
  const [available, setAvailable] = useState<{ players: string[]; teams: string[] } | null>(null)
  const [players, setPlayers] = useState<IccRankingTable | null>(null)
  const [teams, setTeams] = useState<IccTeamRankingTable | null>(null)
  const [offset, setOffset] = useState(0)
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

  // A new table is a new list; carrying an offset into it can land past the end.
  useEffect(() => {
    setOffset(0)
  }, [rankType])

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
    const page = { limit: LIMIT, offset }
    const request =
      discipline === 'team'
        ? api.iccTeamRanking(rankType, page).then((t) => !cancelled && setTeams(t))
        : api.iccPlayerRanking(rankType, page).then((t) => !cancelled && setPlayers(t))
    request
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [rankType, discipline, womensTest, offset])

  const published = players ?? teams

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">ICC Rankings</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Official ratings published by the ICC, refreshed daily. These are not computed by this
          site — for figures derived from ball-by-ball data see{' '}
          <Link to={`/${slug}/rankings`} className="text-analytic hover:underline">
            Rankings
          </Link>
          .
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Format</span>
          <select value={format} onChange={(e) => setFormat(e.target.value)} className={field}>
            {FORMATS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Discipline</span>
          <select
            value={discipline}
            onChange={(e) => setDiscipline(e.target.value)}
            className={field}
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
        <p className={notice}>The ICC does not publish women's Test rankings. Try ODI or T20I.</p>
      ) : loading ? (
        <LoadingSpinner />
      ) : error && known ? (
        <ErrorMessage message={error} />
      ) : error ? (
        <p className={notice}>No ICC data stored for this combination yet.</p>
      ) : (
        <>
          {published && (
            <p className="tnum text-xs text-dim">
              Published {published.rank_date}
              {published.fetched_at && ` · fetched ${published.fetched_at.slice(0, 10)}`}
            </p>
          )}

          <div className="scroll-x rounded-lg border border-border-default bg-surface">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-border-default bg-elevated text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                  <th className="px-4 py-2.5">Rank</th>
                  <th className="px-3 py-2.5">{discipline === 'team' ? 'Team' : 'Player'}</th>
                  {discipline !== 'team' && <th className="px-3 py-2.5">Country</th>}
                  <th className="px-3 py-2.5 text-right">Rating</th>
                  {discipline !== 'team' && <th className="px-4 py-2.5 text-right">Career best</th>}
                </tr>
              </thead>
              <tbody>
                {players?.rows.map((r) => (
                  <tr
                    key={`${r.position}-${r.player_name}`}
                    className="border-b border-border-subtle last:border-0 hover:bg-elevated"
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{r.position}</td>
                    <td className="px-3 py-2.5 font-medium text-ink">
                      {/* Only confidently-matched entries become links. An
                          unmatched name is still shown -- it's ICC's data and
                          it's real -- but is not attached to a profile. */}
                      {r.player_identifier ? (
                        <Link
                          to={`/${slug}/players/${r.player_identifier}`}
                          className="hover:text-analytic"
                        >
                          {r.player_name}
                        </Link>
                      ) : (
                        <span
                          className="text-muted"
                          title="No confident match to a player in this dataset, so this name is not linked"
                        >
                          {r.player_name}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-muted">{r.country ?? '—'}</td>
                    <td className="tnum px-3 py-2.5 text-right font-semibold text-ink">
                      {r.points ?? '—'}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right text-xs text-dim">
                      {r.career_best ?? '—'}
                    </td>
                  </tr>
                ))}
                {teams?.rows.map((r) => (
                  <tr
                    key={`${r.position}-${r.team_name}`}
                    className="border-b border-border-subtle last:border-0 hover:bg-elevated"
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{r.position}</td>
                    <td className="px-3 py-2.5 font-medium text-ink">
                      {r.team_id ? (
                        <Link to={`/${slug}/teams/${r.team_id}`} className="hover:text-analytic">
                          {r.team_name}
                        </Link>
                      ) : (
                        <span className="text-muted">{r.team_name}</span>
                      )}
                    </td>
                    <td className="tnum px-3 py-2.5 text-right font-semibold text-ink">
                      {r.points ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {published && (
              <div className="px-4">
                <Pagination
                  total={published.total}
                  limit={published.limit || LIMIT}
                  offset={published.offset}
                  onChange={setOffset}
                />
              </div>
            )}
          </div>

          <p className="max-w-3xl text-xs leading-relaxed text-dim">
            ICC names people in full where this dataset uses the scorecard form, and publishes no
            shared identifier, so entries are matched on surname and initial with country as a
            tiebreak. Anything ambiguous resolves to no link rather than a guess — about one entry in
            six stays unlinked, and those still show ICC's figure.
          </p>
        </>
      )}
    </div>
  )
}
