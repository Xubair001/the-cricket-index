import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { DirectoryPlayer, FormState } from '../api/types'
import { ErrorMessage } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'
import { rate } from '../format'
import { PlayerName } from '../components/PlayerName'

/**
 * The player directory — the main discovery interface (§7).
 *
 * Filter state lives in the URL, not in component state alone, so a filtered
 * view is a link a scout can send to a colleague and land on the same numbers
 * (§24, shareable analysis URLs). That also makes the back button work.
 *
 * Sorting on a rate applies a qualification server-side; the page says which
 * one is in force rather than leaving a leaderboard that silently excludes
 * people looking like it covers everyone.
 */

const LIMIT = 25

const SORTS = [
  { key: 'matches', label: 'Matches' },
  { key: 'runs', label: 'Runs' },
  { key: 'batting_average', label: 'Batting average' },
  { key: 'strike_rate', label: 'Strike rate' },
  { key: 'wickets', label: 'Wickets' },
  { key: 'bowling_average', label: 'Bowling average' },
  { key: 'economy', label: 'Economy' },
  { key: 'form', label: 'Current form' },
]

const COMPETITIONS = [
  { key: '', label: 'Internationals' },
  { key: 'tests', label: 'Tests' },
  { key: 'odis', label: 'ODIs' },
  { key: 't20is', label: 'T20Is' },
  { key: 'psl', label: 'PSL' },
]

const STATUSES = [
  { key: '', label: 'Any status' },
  { key: 'active', label: 'Active' },
  { key: 'inactive', label: 'Inactive' },
  { key: 'retired', label: 'Retired' },
]

const FORM_STATES = [
  { key: '', label: 'Any form' },
  { key: 'in_form', label: 'In form' },
  { key: 'improving', label: 'Improving' },
  { key: 'stable', label: 'Stable' },
  { key: 'declining', label: 'Declining' },
  { key: 'out_of_form', label: 'Out of form' },
]

// Which sorts rest on a rate, and therefore carry a server-side qualification.
const QUALIFIED: Record<string, string> = {
  batting_average: '200 balls faced',
  strike_rate: '200 balls faced',
  runs: '200 balls faced',
  bowling_average: '300 balls bowled',
  economy: '300 balls bowled',
  wickets: '300 balls bowled',
}

const FORM_TONE: Record<FormState, string> = {
  in_form: 'text-positive-ink',
  improving: 'text-positive-ink',
  stable: 'text-muted',
  declining: 'text-warning-ink',
  out_of_form: 'text-negative-ink',
  insufficient_data: 'text-dim',
}

function Select({
  value,
  onChange,
  options,
  label,
}: {
  value: string
  onChange: (v: string) => void
  options: { key: string; label: string }[]
  label: string
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
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function Players() {
  const { slug, apiGender } = useGender()
  const [params, setParams] = useSearchParams()

  const competition = params.get('competition') ?? ''
  const status = params.get('status') ?? ''
  const formState = params.get('form') ?? ''
  const sortBy = params.get('sort') ?? 'matches'
  const minMatches = Number(params.get('min_matches') ?? 1)
  const offset = Number(params.get('offset') ?? 0)
  const search = params.get('q') ?? ''

  const [searchInput, setSearchInput] = useState(search)
  const [rows, setRows] = useState<DirectoryPlayer[]>([])
  const [total, setTotal] = useState(0)
  const [scope, setScope] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // One writer for the URL, so every control resets pagination the same way and
  // no control can leave a stale offset pointing past the new result set.
  function update(next: Record<string, string>, keepOffset = false) {
    const merged = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v)
      else merged.delete(k)
    }
    if (!keepOffset) merged.delete('offset')
    setParams(merged, { replace: true })
  }

  useEffect(() => {
    const t = setTimeout(() => {
      if (searchInput !== search) update({ q: searchInput })
    }, 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .playerDirectory(apiGender, {
        search: search || undefined,
        competition: competition || undefined,
        status: status || undefined,
        form_state: formState || undefined,
        sort_by: sortBy,
        min_matches: minMatches,
        limit: LIMIT,
        offset,
      })
      .then((res) => {
        if (cancelled) return
        setRows(res.items)
        setTotal(res.total)
        setScope(res.scope)
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
  }, [apiGender, search, competition, status, formState, sortBy, minMatches, offset])

  const qualification = useMemo(() => QUALIFIED[sortBy], [sortBy])

  return (
    <div className="space-y-5">
      <div>
        <h1 className="u-display text-title text-ink">Players</h1>
        <p className="mt-1 text-sm text-muted">
          {total.toLocaleString()} players in {scope || 'this scope'}
          {qualification && (
            <>
              {' '}
              · sorted on a rate, so a minimum of{' '}
              <span className="text-warning-ink">{qualification}</span> applies
            </>
          )}
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">Search</span>
          <input
            type="text"
            placeholder="Any spelling — Joe Root or JE Root"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="w-64 rounded-md border border-border-default bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-dim"
          />
        </label>
        <Select label="Competition" value={competition} options={COMPETITIONS} onChange={(v) => update({ competition: v })} />
        <Select label="Sort by" value={sortBy} options={SORTS.map((s) => ({ key: s.key, label: s.label }))} onChange={(v) => update({ sort: v })} />
        <Select label="Status" value={status} options={STATUSES} onChange={(v) => update({ status: v })} />
        <Select label="Form" value={formState} options={FORM_STATES} onChange={(v) => update({ form: v })} />
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">Min matches</span>
          <input
            type="number"
            min={1}
            value={minMatches}
            onChange={(e) => update({ min_matches: e.target.value })}
            className="w-24 rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink"
          />
        </label>
      </div>

      {error && <ErrorMessage message={error} />}

      <div className="scroll-x rounded-xl border border-border-subtle bg-surface shadow-card">
        <table className="w-full min-w-[840px] text-sm">
          <thead>
            <tr className="border-b border-border-default bg-elevated text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
              <th className="px-4 py-2.5">Player</th>
              <th className="px-3 py-2.5 text-right">Mat</th>
              <th className="px-3 py-2.5 text-right">Runs</th>
              <th className="px-3 py-2.5 text-right">Avg</th>
              <th className="px-3 py-2.5 text-right">SR</th>
              <th className="px-3 py-2.5 text-right">Wkts</th>
              <th className="px-3 py-2.5 text-right">Econ</th>
              <th className="px-4 py-2.5 text-right">Form</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={8} className="px-4 py-2">
                      <div className="h-5 animate-pulse rounded bg-elevated" />
                    </td>
                  </tr>
                ))
              : rows.map((p) => (
                  <tr key={p.identifier} className="border-b border-border-subtle last:border-0 hover:bg-elevated">
                    <td className="px-4 py-2.5">
                      <PlayerName
                        name={p.name ?? p.scorecard_name ?? p.identifier}
                        country={p.country}
                        countryCode={p.country_code}
                        to={`/${slug}/players/${p.identifier}`}
                        nameClassName="font-medium"
                      />
                      {p.status?.state === 'retired' && (
                        <span className="ml-2 font-mono text-[9px] uppercase tracking-[0.1em] text-dim">retired</span>
                      )}
                    </td>
                    <td className="tnum px-3 py-2.5 text-right text-muted">{p.matches}</td>
                    <td className="tnum px-3 py-2.5 text-right text-ink">{p.runs.toLocaleString()}</td>
                    <td className="tnum px-3 py-2.5 text-right text-muted">{rate(p.batting_average)}</td>
                    <td className="tnum px-3 py-2.5 text-right text-muted">{rate(p.strike_rate)}</td>
                    <td className="tnum px-3 py-2.5 text-right text-muted">{p.wickets || '—'}</td>
                    <td className="tnum px-3 py-2.5 text-right text-muted">{rate(p.economy)}</td>
                    <td className="px-4 py-2.5 text-right">
                      {p.form_state ? (
                        <span
                          className={`tnum text-xs font-semibold ${FORM_TONE[p.form_state]}`}
                          title={`${p.form_label} — confidence ${Math.round((p.form_confidence ?? 0) * 100)}%`}
                        >
                          {p.form_delta !== null
                            ? `${p.form_delta > 0 ? '+' : ''}${p.form_delta.toFixed(0)}%`
                            : p.form_label}
                        </span>
                      ) : (
                        <span className="text-xs text-dim" title="Not enough recent cricket in this scope">
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>

        {!loading && rows.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted">
            No players match these filters. Try lowering the minimum matches, or widening the
            competition scope.
          </p>
        )}

        {total > LIMIT && (
          <div className="px-4">
            <Pagination
              total={total}
              limit={LIMIT}
              offset={offset}
              onChange={(o) => update({ offset: String(o) }, true)}
            />
          </div>
        )}
      </div>

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        Form compares each player against their own preceding 12 months within this scope — it
        measures change, not standard, so a modest player having a good run can outrank a great one
        playing normally. A dash means not enough recent cricket to judge. Internationals and
        franchise cricket are never blended into one figure.
      </p>
    </div>
  )
}
