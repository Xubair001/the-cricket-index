import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { BattingRankingRow, BowlingRankingRow } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'

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

const COMPETITIONS = [
  { value: '', label: 'All Formats' },
  { value: 'tests', label: 'Tests' },
  { value: 'odis', label: 'ODIs' },
  { value: 't20is', label: 'T20Is' },
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
    <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Rankings</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Career leaderboards across international cricket
        </p>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => switchTab('batting')}
          className={`rounded-md px-4 py-2 text-sm font-medium ${
            tab === 'batting'
              ? 'bg-emerald-600 text-white'
              : 'bg-white text-slate-600 ring-1 ring-slate-300 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700'
          }`}
        >
          Batting
        </button>
        <button
          onClick={() => switchTab('bowling')}
          className={`rounded-md px-4 py-2 text-sm font-medium ${
            tab === 'bowling'
              ? 'bg-emerald-600 text-white'
              : 'bg-white text-slate-600 ring-1 ring-slate-300 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700'
          }`}
        >
          Bowling
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
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
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          Min. matches
          <input
            type="number"
            min={1}
            value={minMatches}
            onChange={(e) => {
              setMinMatches(Math.max(1, Number(e.target.value) || 1))
              setOffset(0)
            }}
            className="w-20 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          />
        </label>
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && rows.length === 0 && <LoadingSpinner />}

      {!error && !(loading && rows.length === 0) && (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          {tab === 'batting' ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
                  <th className="py-3 pl-5">#</th>
                  <th className="py-3">Player</th>
                  <th className="py-3 text-right">M</th>
                  <th className="py-3 text-right">Runs</th>
                  <th className="py-3 text-right">Avg</th>
                  <th className="py-3 text-right">SR</th>
                  <th className="py-3 text-right">4s</th>
                  <th className="py-3 pr-5 text-right">6s</th>
                </tr>
              </thead>
              <tbody>
                {(rows as BattingRankingRow[]).map((p, i) => (
                  <tr key={p.player_identifier ?? p.player_name} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800/50 dark:hover:bg-slate-800/40">
                    <td className="py-2.5 pl-5 text-slate-400">{offset + i + 1}</td>
                    <td className="py-2.5">
                      <Link
                        to={p.player_identifier ? `/${slug}/players/${p.player_identifier}` : '#'}
                        className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                      >
                        {p.player_name}
                      </Link>
                    </td>
                    <td className="py-2.5 text-right text-slate-600 dark:text-slate-300">{p.matches}</td>
                    <td className="py-2.5 text-right font-semibold text-slate-800 dark:text-slate-100">{p.runs}</td>
                    <td className="py-2.5 text-right text-slate-600 dark:text-slate-300">{p.average ?? '-'}</td>
                    <td className="py-2.5 text-right text-slate-600 dark:text-slate-300">{p.strike_rate ?? '-'}</td>
                    <td className="py-2.5 text-right text-slate-600 dark:text-slate-300">{p.fours}</td>
                    <td className="py-2.5 pr-5 text-right text-slate-600 dark:text-slate-300">{p.sixes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
                  <th className="py-3 pl-5">#</th>
                  <th className="py-3">Player</th>
                  <th className="py-3 text-right">M</th>
                  <th className="py-3 text-right">Wkts</th>
                  <th className="py-3 text-right">Runs</th>
                  <th className="py-3 text-right">Avg</th>
                  <th className="py-3 pr-5 text-right">Econ</th>
                </tr>
              </thead>
              <tbody>
                {(rows as BowlingRankingRow[]).map((p, i) => (
                  <tr key={p.player_identifier ?? p.player_name} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800/50 dark:hover:bg-slate-800/40">
                    <td className="py-2.5 pl-5 text-slate-400">{offset + i + 1}</td>
                    <td className="py-2.5">
                      <Link
                        to={p.player_identifier ? `/${slug}/players/${p.player_identifier}` : '#'}
                        className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                      >
                        {p.player_name}
                      </Link>
                    </td>
                    <td className="py-2.5 text-right text-slate-600 dark:text-slate-300">{p.matches}</td>
                    <td className="py-2.5 text-right font-semibold text-slate-800 dark:text-slate-100">{p.wickets}</td>
                    <td className="py-2.5 text-right text-slate-600 dark:text-slate-300">{p.runs_conceded}</td>
                    <td className="py-2.5 text-right text-slate-600 dark:text-slate-300">{p.average ?? '-'}</td>
                    <td className="py-2.5 pr-5 text-right text-slate-600 dark:text-slate-300">{p.economy ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="px-5">
            <Pagination total={total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        </div>
      )}
    </div>
  )
}
