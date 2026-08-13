import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { BattingRankingRow, BowlingRankingRow } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'
import { rate } from '../format'
import { PlayerName } from '../components/PlayerName'

/**
 * Computed leaderboards — this project's own figures, derived from Cricsheet
 * ball-by-ball aggregates. Deliberately not the same page as ICC Rankings,
 * which are official published ratings (§6, derived figures and official
 * ratings stay separate).
 */

const LIMIT = 20

const BATTING_SORTS = [
  { value: 'runs', label: 'Runs' },
  { value: 'average', label: 'Average' },
  { value: 'strike_rate', label: 'Strike Rate' },
  { value: 'matches', label: 'Matches' },
]

const BOWLING_SORTS = [
  { value: 'wickets', label: 'Wickets' },
  { value: 'average', label: 'Average' },
  { value: 'economy', label: 'Economy' },
  { value: 'matches', label: 'Matches' },
]

// "All Internationals", not "All Formats": the API deliberately refuses to sum
// international and franchise cricket into one career figure, so the unscoped
// option means every international format -- PSL has to be picked explicitly.
const COMPETITIONS = [
  { value: '', label: 'All Internationals' },
  { value: 'tests', label: 'Tests' },
  { value: 'odis', label: 'ODIs' },
  { value: 't20is', label: 'T20Is' },
  { value: 'psl', label: 'PSL' },
]

function SelectControl({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function Rankings() {
  const { slug, apiGender } = useGender()
  const [tab, setTab] = useState<'batting' | 'bowling'>('batting')
  const [competition, setCompetition] = useState('')
  const [minMatches, setMinMatches] = useState(10)
  const [sortBy, setSortBy] = useState('runs')
  const [offset, setOffset] = useState(0)

  const [rows, setRows] = useState<(BattingRankingRow | BowlingRankingRow)[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function switchTab(nextTab: 'batting' | 'bowling') {
    // Set everything together (same render/batch) so the fetch effect below
    // never runs with a sort field that's invalid for the new tab (e.g.
    // bowling with sortBy still 'runs' from the batting tab), and so the
    // pagination footer never shows a stale total from the previous tab
    // while the table body is already empty/loading.
    setTab(nextTab)
    setSortBy(nextTab === 'batting' ? 'runs' : 'wickets')
    setOffset(0)
    setRows([])
    setTotal(0)
  }

  useEffect(() => {
    // Guards against a slower, now-superseded request (e.g. the previous
    // tab's) resolving after a newer one and overwriting its state with
    // stale data — there's no built-in fetch cancellation here, so this
    // flag is what makes only the most recent request's result "win".
    let cancelled = false
    setLoading(true)
    setError(null)
    const params = { competition: competition || undefined, min_matches: minMatches, sort_by: sortBy, limit: LIMIT, offset }
    const request =
      tab === 'batting' ? api.battingRankings(apiGender, params) : api.bowlingRankings(apiGender, params)
    request
      .then((res) => {
        if (cancelled) return
        setRows(res.items)
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
  }, [apiGender, tab, competition, minMatches, sortBy, offset])

  const sortOptions = tab === 'batting' ? BATTING_SORTS : BOWLING_SORTS

  const tabButton = (active: boolean) =>
    'rounded-md px-4 py-1.5 text-sm font-medium transition-colors ' +
    (active ? 'bg-elevated text-ink' : 'text-muted hover:text-ink')

  const th = 'px-3 py-2.5 text-right'
  const td = 'tnum px-3 py-2.5 text-right text-muted'

  return (
    <div className="space-y-5">
      <div>
        <h1 className="u-display text-title text-ink">Rankings</h1>
        <p className="mt-1 text-sm text-muted">
          Career leaderboards computed from ball-by-ball aggregates — not the ICC's official
          ratings, which are{' '}
          <Link to={`/${slug}/icc-rankings`} className="text-analytic-ink hover:underline">
            published separately
          </Link>
          .
        </p>
      </div>

      {/* Segmented control rather than two filled buttons: picking batting over
          bowling is a view change, not an outcome, so it gets no semantic colour. */}
      <div className="inline-flex rounded-lg border border-border-default bg-surface p-0.5">
        <button type="button" onClick={() => switchTab('batting')} className={tabButton(tab === 'batting')}>
          Batting
        </button>
        <button type="button" onClick={() => switchTab('bowling')} className={tabButton(tab === 'bowling')}>
          Bowling
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <SelectControl
          label="Format"
          value={competition}
          options={COMPETITIONS}
          onChange={(v) => {
            setCompetition(v)
            setOffset(0)
          }}
        />
        <SelectControl
          label="Sort by"
          value={sortBy}
          options={sortOptions}
          onChange={(v) => {
            setSortBy(v)
            setOffset(0)
          }}
        />
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
            Min matches
          </span>
          <input
            type="number"
            min={1}
            value={minMatches}
            onChange={(e) => {
              setMinMatches(Math.max(1, Number(e.target.value) || 1))
              setOffset(0)
            }}
            className="w-24 rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink"
          />
        </label>
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && rows.length === 0 && <LoadingSpinner />}

      {!error && !(loading && rows.length === 0) && (
        <div className="scroll-x rounded-xl border border-border-subtle bg-surface shadow-card">
          {tab === 'batting' ? (
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-border-default bg-elevated text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                  <th className="px-4 py-2.5">#</th>
                  <th className="px-3 py-2.5">Player</th>
                  <th className={th}>Mat</th>
                  <th className={th}>Runs</th>
                  <th className={th}>Avg</th>
                  <th className={th}>SR</th>
                  <th className={th}>4s</th>
                  <th className="px-4 py-2.5 text-right">6s</th>
                </tr>
              </thead>
              <tbody>
                {(rows as BattingRankingRow[]).map((p, i) => (
                  <tr
                    key={p.player_identifier ?? p.player_name}
                    className="border-b border-border-subtle last:border-0 hover:bg-elevated"
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{offset + i + 1}</td>
                    <td className="px-3 py-2.5">
                      <PlayerName
                        name={p.player_name}
                        country={p.country}
                        countryCode={p.country_code}
                        to={
                          p.player_identifier
                            ? `/${slug}/players/${p.player_identifier}`
                            : undefined
                        }
                        nameClassName="font-medium"
                      />
                    </td>
                    <td className={td}>{p.matches}</td>
                    <td className="tnum px-3 py-2.5 text-right font-semibold text-ink">
                      {p.runs.toLocaleString()}
                    </td>
                    <td className={td}>{rate(p.average)}</td>
                    <td className={td}>{rate(p.strike_rate)}</td>
                    <td className={td}>{p.fours}</td>
                    <td className="tnum px-4 py-2.5 text-right text-muted">{p.sixes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="w-full min-w-[660px] text-sm">
              <thead>
                <tr className="border-b border-border-default bg-elevated text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                  <th className="px-4 py-2.5">#</th>
                  <th className="px-3 py-2.5">Player</th>
                  <th className={th}>Mat</th>
                  <th className={th}>Wkts</th>
                  <th className={th}>Runs</th>
                  <th className={th}>Avg</th>
                  <th className="px-4 py-2.5 text-right">Econ</th>
                </tr>
              </thead>
              <tbody>
                {(rows as BowlingRankingRow[]).map((p, i) => (
                  <tr
                    key={p.player_identifier ?? p.player_name}
                    className="border-b border-border-subtle last:border-0 hover:bg-elevated"
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{offset + i + 1}</td>
                    <td className="px-3 py-2.5">
                      <PlayerName
                        name={p.player_name}
                        country={p.country}
                        countryCode={p.country_code}
                        to={
                          p.player_identifier
                            ? `/${slug}/players/${p.player_identifier}`
                            : undefined
                        }
                        nameClassName="font-medium"
                      />
                    </td>
                    <td className={td}>{p.matches}</td>
                    <td className="tnum px-3 py-2.5 text-right font-semibold text-ink">{p.wickets}</td>
                    <td className={td}>{p.runs_conceded.toLocaleString()}</td>
                    <td className={td}>{rate(p.average)}</td>
                    <td className="tnum px-4 py-2.5 text-right text-muted">{rate(p.economy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {!loading && rows.length === 0 && (
            <p className="px-4 py-6 text-sm text-muted">
              No players clear this minimum in this scope. Try lowering the minimum matches.
            </p>
          )}

          <div className="px-4">
            <Pagination total={total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        </div>
      )}

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        Figures are aggregated by player identifier rather than name, because 70 names in this
        dataset belong to more than one person. Internationals and franchise cricket are ranked
        separately and never summed — a career total blending Test and PSL runs is a figure no
        cricket source publishes.
      </p>
    </div>
  )
}
