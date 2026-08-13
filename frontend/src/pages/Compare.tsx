import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type { ApiGender, ComparisonMetric, PlayerComparison, PlayerSummary } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { PlayerAvatar } from '../components/PlayerAvatar'
import { StatusBadge } from '../components/StatusBadge'
import { useGender } from '../gender/useGender'
import { useTheme } from '../theme/ThemeContext'

// Two series, one categorical pair, validated for colour-vision deficiency and
// contrast against BOTH the light and dark chart surfaces (OKLCH lightness in
// band, adjacent ΔE 23.4 protan / 30.6 normal). One pair serves both themes, so
// a player keeps the same colour when the theme changes.
const SERIES = { a: '#0284c7', b: '#d97706' }

const SCOPES = [
  { value: '', label: 'All Internationals' },
  { value: 'tests', label: 'Tests' },
  { value: 'odis', label: 'ODIs' },
  { value: 't20is', label: 'T20Is' },
  { value: 'psl', label: 'PSL' },
]

function fmt(value: number | null, format: string): string {
  if (value === null || value === undefined) return '—'
  if (format === 'int') return Math.round(value).toLocaleString()
  return value.toFixed(2)
}

/** One head-to-head row: both values, with the winning side emphasised. */
function MetricRow({ metric, nameA, nameB }: { metric: ComparisonMetric; nameA: string; nameB: string }) {
  const total = (Math.abs(metric.a ?? 0) || 0) + (Math.abs(metric.b ?? 0) || 0)
  const pctA = total > 0 ? ((Math.abs(metric.a ?? 0) / total) * 100).toFixed(1) : '50'
  const win = (side: 'a' | 'b') => metric.better === side

  return (
    <div className="border-b border-slate-100 py-3 last:border-0 dark:border-slate-800/60">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span
          className={win('a') ? 'font-bold text-slate-900 dark:text-white' : 'text-slate-500 dark:text-slate-400'}
        >
          {fmt(metric.a, metric.format)}
        </span>
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500">
          {metric.label}
          {metric.lower_is_better && <span className="ml-1 normal-case">(lower is better)</span>}
        </span>
        <span
          className={win('b') ? 'font-bold text-slate-900 dark:text-white' : 'text-slate-500 dark:text-slate-400'}
        >
          {fmt(metric.b, metric.format)}
        </span>
      </div>
      {/* Proportional bar, with a 2px surface gap so the boundary reads even
          where the two hues sit close in value.

          Drawn only for higher-is-better metrics. Bar length encodes
          magnitude, and for a metric like bowling average magnitude runs
          opposite to quality -- a 107 average would take the longer bar while
          being far the worse figure, so the picture would contradict the
          verdict beside it. Those rows get a winner marker instead. */}
      {metric.lower_is_better ? (
        <div className="mt-1.5 flex justify-between text-[11px] text-slate-400">
          <span>{metric.better === 'a' ? '▲ better' : ''}</span>
          <span>{metric.better === 'b' ? 'better ▲' : ''}</span>
        </div>
      ) : (
        <div className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div
            style={{ width: `${pctA}%`, backgroundColor: SERIES.a }}
            className="rounded-l-full"
            title={`${nameA}: ${fmt(metric.a, metric.format)}`}
          />
          <div className="w-0.5 shrink-0 bg-white dark:bg-slate-900" />
          <div
            style={{ width: `calc(${100 - Number(pctA)}% - 2px)`, backgroundColor: SERIES.b }}
            className="rounded-r-full"
            title={`${nameB}: ${fmt(metric.b, metric.format)}`}
          />
        </div>
      )}
    </div>
  )
}

/**
 * Player selector backed by server-side search.
 *
 * Searches the API rather than filtering a preloaded slice: the dataset holds
 * ~9,400 players, so a client-side filter over the first page would silently
 * make most of them unselectable — "compare any two players" has to mean any.
 */
function PlayerPicker({
  label,
  value,
  apiGender,
  exclude,
  onChange,
}: {
  label: string
  value: string
  apiGender: ApiGender
  exclude: string
  onChange: (v: string) => void
}) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [options, setOptions] = useState<PlayerSummary[]>([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<PlayerSummary | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    let cancelled = false
    api
      .players(apiGender, { search: debounced || undefined, limit: 50, offset: 0 })
      .then((res) => {
        if (cancelled) return
        setOptions(res.items)
        setTotal(res.total)
      })
      .catch(() => !cancelled && setOptions([]))
    return () => {
      cancelled = true
    }
  }, [apiGender, debounced])

  // Keep the chosen player listed even once the search moves on, so the
  // selection doesn't vanish from its own dropdown.
  const listed = useMemo(() => {
    const base = options.filter((p) => p.identifier !== exclude)
    if (selected && !base.some((p) => p.identifier === selected.identifier)) {
      return [selected, ...base]
    }
    return base
  }, [options, exclude, selected])

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">{label}</label>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search all players…"
        className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
      />
      <select
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          setSelected(options.find((p) => p.identifier === e.target.value) ?? selected)
        }}
        className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
      >
        <option value="">Select a player…</option>
        {listed.map((p) => (
          <option key={p.identifier} value={p.identifier}>
            {p.name} ({p.matches})
          </option>
        ))}
      </select>
      {total > listed.length && (
        <p className="text-xs text-slate-400">
          Showing {listed.length} of {total.toLocaleString()} — type to narrow.
        </p>
      )}
    </div>
  )
}

export function Compare() {
  const { slug, apiGender } = useGender()
  const { theme } = useTheme()
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [scope, setScope] = useState('')
  const [data, setData] = useState<PlayerComparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const gridStroke = theme === 'dark' ? '#334155' : '#e2e8f0'
  const axisTick = theme === 'dark' ? '#94a3b8' : '#64748b'
  const tooltipStyle = {
    borderRadius: 8,
    fontSize: 13,
    background: theme === 'dark' ? '#1e293b' : '#ffffff',
    border: `1px solid ${theme === 'dark' ? '#334155' : '#e2e8f0'}`,
    color: theme === 'dark' ? '#f1f5f9' : '#0f172a',
  }

  // Each picker searches within the current gender, so a cross-gender pairing
  // can't even be expressed in the UI (the API rejects it too). Switching
  // gender clears the pair rather than carrying over foreign identifiers.
  useEffect(() => {
    setA('')
    setB('')
    setData(null)
  }, [apiGender])

  useEffect(() => {
    if (!a || !b) {
      setData(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .comparePlayers(a, b, scope ? { competition: scope } : {})
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [a, b, scope])

  const hasWickets =
    data && data.season_wickets.some((p) => p.a > 0 || p.b > 0)

  const byCompetition = useMemo(() => {
    if (!data) return []
    const keys = new Set([
      ...data.a.by_competition.map((c) => c.competition_key),
      ...data.b.by_competition.map((c) => c.competition_key),
    ])
    return [...keys].map((key) => {
      const ca = data.a.by_competition.find((c) => c.competition_key === key)
      const cb = data.b.by_competition.find((c) => c.competition_key === key)
      return {
        competition: ca?.display_name ?? cb?.display_name ?? key,
        a: ca?.runs ?? 0,
        b: cb?.runs ?? 0,
      }
    })
  }, [data])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Compare Players</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Head-to-head within one competition at a time — international and franchise figures are
          never summed together.
        </p>
      </div>

      <div className="grid gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-3 dark:border-slate-800 dark:bg-slate-900">
        <PlayerPicker label="Player A" value={a} apiGender={apiGender} exclude={b} onChange={setA} />
        <PlayerPicker label="Player B" value={b} apiGender={apiGender} exclude={a} onChange={setB} />
        <div className="space-y-2">
          <label className="block text-xs font-medium uppercase tracking-wide text-slate-400">
            Scope
          </label>
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          >
            {SCOPES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner />}

      {!a || !b ? (
        <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          Pick two players to compare.
        </p>
      ) : null}

      {data && !loading && (
        <>
          {/* Identity header — colour is introduced here and reused for every
              mark below, so a reader learns the mapping once. */}
          <div className="grid gap-4 sm:grid-cols-2">
            {(['a', 'b'] as const).map((side) => {
              const p = data[side]
              return (
                <div
                  key={side}
                  className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
                  style={{ borderTopColor: SERIES[side], borderTopWidth: 3 }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <PlayerAvatar src={p.bio.image_url} alt={p.name} className="h-10 w-10" />
                    <Link
                      to={`/${slug}/players/${p.identifier}`}
                      className="text-lg font-bold text-slate-900 hover:text-emerald-600 dark:text-white dark:hover:text-emerald-400"
                    >
                      {p.name}
                    </Link>
                    <StatusBadge status={p.status} />
                  </div>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {p.career_span.filter(Boolean).join('–') || 'Span unknown'}
                    {p.teams.length > 0 && ` · ${p.teams.map((t) => t.name).join(', ')}`}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    {p.bio.date_of_birth ? `Born ${p.bio.date_of_birth}` : 'Born: Not available'}
                    {p.bio.birth_place ? ` · ${p.bio.birth_place}` : ''}
                  </p>
                  {p.icc_rankings.length > 0 && (
                    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                      ICC:{' '}
                      {p.icc_rankings
                        .map((r) => `#${r.position} ${r.rank_type.replace('-', ' ')}`)
                        .join(' · ')}
                    </p>
                  )}
                </div>
              )
            })}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-semibold text-slate-900 dark:text-white">
                Head to head — {data.scope_label}
              </h2>
              {/* Legend is always present for two series: identity must never
                  rest on colour alone. */}
              <div className="flex gap-3 text-xs text-slate-500 dark:text-slate-400">
                {(['a', 'b'] as const).map((s) => (
                  <span key={s} className="inline-flex items-center gap-1.5">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: SERIES[s] }}
                      aria-hidden
                    />
                    {data[s].name}
                  </span>
                ))}
              </div>
            </div>
            {data.metrics.map((m) => (
              <MetricRow key={m.key} metric={m} nameA={data.a.name} nameB={data.b.name} />
            ))}
            <p className="mt-3 text-xs text-slate-400">
              Rate metrics (averages, strike rate, economy) declare a winner only when both players
              clear a minimum volume — otherwise the numbers are shown without a verdict.
            </p>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">Runs by season</h2>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={data.season_runs} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="season" tick={{ fill: axisTick, fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fill: axisTick, fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line
                    type="monotone" dataKey="a" name={data.a.name} stroke={SERIES.a}
                    strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }}
                  />
                  <Line
                    type="monotone" dataKey="b" name={data.b.name} stroke={SERIES.b}
                    strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {hasWickets && (
              <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">
                  Wickets by season
                </h2>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart
                    data={data.season_wickets}
                    margin={{ top: 4, right: 8, bottom: 0, left: -12 }}
                  >
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="season" tick={{ fill: axisTick, fontSize: 11 }} tickLine={false} />
                    <YAxis tick={{ fill: axisTick, fontSize: 11 }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line
                      type="monotone" dataKey="a" name={data.a.name} stroke={SERIES.a}
                      strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }}
                    />
                    <Line
                      type="monotone" dataKey="b" name={data.b.name} stroke={SERIES.b}
                      strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">
                Runs by competition
              </h2>
              <p className="mb-2 text-xs text-slate-400">
                Shown side by side, never added together.
              </p>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={byCompetition} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="competition" tick={{ fill: axisTick, fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fill: axisTick, fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'transparent' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="a" name={data.a.name} fill={SERIES.a} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="b" name={data.b.name} fill={SERIES.b} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
