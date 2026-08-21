import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { AppliedPeriod, BattingRankingRow, BowlingRankingRow } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'
import { useScopedCompetition } from '../scope/scope'
import { useFilters } from '../state/useFilters'
import { AppliedPeriodNote, PeriodSelect } from '../components/PeriodSelect'
import { rate } from '../format'
import { PlayerName } from '../components/PlayerName'
import {
  tableClass,
  tdClass,
  tdNumClass,
  tdNumStrongClass,
  thClass,
  thNumClass,
  theadRowClass,
  trClass,
} from '../components/ui'

/**
 * Computed leaderboards - this project's own figures, derived from Cricsheet
 * ball-by-ball aggregates. Deliberately not the same page as ICC Rankings,
 * which are official published ratings (§6, derived figures and official
 * ratings stay separate).
 */

const LIMIT = 20

/** Kept off the URL when unchanged, so a default board has a clean address. */
const DEFAULT_MIN_MATCHES = 10

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
  // Every filter here lives in the URL (see `state/useFilters`), so a narrowed
  // board is a shareable address and the back button undoes a filter rather
  // than leaving the page.
  const f = useFilters()
  const tab: 'batting' | 'bowling' = f.get('tab') === 'bowling' ? 'bowling' : 'batting'
  const requestedCompetition = f.get('competition')
  const minMatches = Math.max(1, f.int('min_matches', DEFAULT_MIN_MATCHES))
  const sortBy = f.get('sort_by', tab === 'batting' ? 'runs' : 'wickets')
  // The window, as one shareable value. Absent means career, which is what a
  // leaderboard has always meant here.
  const period = f.get('period')
  const offset = f.int('offset', 0)

  // The scope switch owns which family is in play; a competition from the
  // other family is dropped rather than sent, so the board never shows
  // franchise figures under an international heading.
  const {
    competition,
    competitionType,
    options: competitionOptions,
  } = useScopedCompetition(requestedCompetition)
  const [rows, setRows] = useState<(BattingRankingRow | BowlingRankingRow)[]>([])
  const [total, setTotal] = useState(0)
  const [applied, setApplied] = useState<AppliedPeriod | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function switchTab(nextTab: 'batting' | 'bowling') {
    // Tab and sort move in ONE write, so the fetch effect below never runs with
    // a sort field the new tab does not have (bowling with `runs` carried over
    // from batting is a 422). The rows are cleared in the same handler so the
    // pagination footer cannot show the previous tab's total over an empty body.
    f.set({ tab: nextTab, sort_by: nextTab === 'batting' ? 'runs' : 'wickets' })
    setRows([])
    setTotal(0)
  }

  useEffect(() => {
    // Guards against a slower, now-superseded request (e.g. the previous
    // tab's) resolving after a newer one and overwriting its state with
    // stale data - there's no built-in fetch cancellation here, so this
    // flag is what makes only the most recent request's result "win".
    let cancelled = false
    setLoading(true)
    setError(null)
    const params = {
      competition: competition || undefined,
      competition_type: competitionType,
      min_matches: minMatches,
      sort_by: sortBy,
      period: period || undefined,
      limit: LIMIT,
      offset,
    }
    const request =
      tab === 'batting' ? api.battingRankings(apiGender, params) : api.bowlingRankings(apiGender, params)
    request
      .then((res) => {
        if (cancelled) return
        setRows(res.items)
        setTotal(res.total)
        setApplied(res.period)
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
  }, [apiGender, tab, competition, competitionType, minMatches, sortBy, period, offset])

  const sortOptions = tab === 'batting' ? BATTING_SORTS : BOWLING_SORTS

  const tabButton = (active: boolean) =>
    'rounded-md px-4 py-1.5 text-sm font-medium transition-colors ' +
    (active ? 'bg-elevated text-ink' : 'text-muted hover:text-ink')

  return (
    <div className="space-y-5">
      <div>
        <h1 className="u-display text-title text-ink">Rankings</h1>
        <p className="mt-1 text-sm text-muted">
          Career leaderboards computed from ball-by-ball aggregates - not the ICC's official
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
          options={competitionOptions}
          onChange={(v) => f.set({ competition: v })}
        />
        <PeriodSelect value={period} onChange={(v) => f.set({ period: v })} />
        <SelectControl
          label="Sort by"
          value={sortBy}
          options={sortOptions}
          onChange={(v) => f.set({ sort_by: v })}
        />
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
            Min matches
          </span>
          <input
            type="number"
            min={1}
            value={minMatches}
            onChange={(e) => f.set({ min_matches: Math.max(1, Number(e.target.value) || 1) })}
            className="w-24 rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink"
          />
        </label>
      </div>

      {/* Above the table, not below it: the window is what the figures MEAN, so
          a reader has to have it before they read the first row. */}
      <AppliedPeriodNote period={applied} />

      {error && <ErrorMessage message={error} />}
      {loading && rows.length === 0 && <LoadingSpinner />}

      {!error && !(loading && rows.length === 0) && (
        <div className="scroll-x rounded-xl border border-border-subtle bg-surface shadow-card">
          {tab === 'batting' ? (
            <table className={`${tableClass} min-w-[720px]`}>
              <thead>
                <tr className={theadRowClass}>
                  <th className="px-4 py-2.5">#</th>
                  <th className={thClass}>Player</th>
                  <th className={thNumClass}>Mat</th>
                  <th className={thNumClass}>Runs</th>
                  <th className={thNumClass}>Avg</th>
                  <th className={thNumClass}>SR</th>
                  <th className={thNumClass}>4s</th>
                  <th className="px-4 py-2.5 text-right">6s</th>
                </tr>
              </thead>
              <tbody>
                {(rows as BattingRankingRow[]).map((p, i) => (
                  <tr
                    key={p.player_identifier ?? p.player_name}
                    className={trClass}
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{offset + i + 1}</td>
                    <td className={tdClass}>
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
                    <td className={tdNumClass}>{p.matches}</td>
                    <td className={tdNumStrongClass}>
                      {p.runs.toLocaleString()}
                    </td>
                    <td className={tdNumClass}>{rate(p.average)}</td>
                    <td className={tdNumClass}>{rate(p.strike_rate)}</td>
                    <td className={tdNumClass}>{p.fours}</td>
                    <td className="tnum px-4 py-2.5 text-right text-muted">{p.sixes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className={`${tableClass} min-w-[660px]`}>
              <thead>
                <tr className={theadRowClass}>
                  <th className="px-4 py-2.5">#</th>
                  <th className={thClass}>Player</th>
                  <th className={thNumClass}>Mat</th>
                  <th className={thNumClass}>Wkts</th>
                  <th className={thNumClass}>Runs</th>
                  <th className={thNumClass}>Avg</th>
                  <th className="px-4 py-2.5 text-right">Econ</th>
                </tr>
              </thead>
              <tbody>
                {(rows as BowlingRankingRow[]).map((p, i) => (
                  <tr
                    key={p.player_identifier ?? p.player_name}
                    className={trClass}
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{offset + i + 1}</td>
                    <td className={tdClass}>
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
                    <td className={tdNumClass}>{p.matches}</td>
                    <td className={tdNumStrongClass}>{p.wickets}</td>
                    <td className={tdNumClass}>{p.runs_conceded.toLocaleString()}</td>
                    <td className={tdNumClass}>{rate(p.average)}</td>
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
            <Pagination total={total} limit={LIMIT} offset={offset} onChange={(o) => f.keep({ offset: o })} />
          </div>
        </div>
      )}

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        Figures are aggregated by player identifier rather than name, because 70 names in this
        dataset belong to more than one person. Internationals and franchise cricket are ranked
        separately and never summed - a career total blending Test and PSL runs is a figure no
        cricket source publishes.
      </p>
    </div>
  )
}
