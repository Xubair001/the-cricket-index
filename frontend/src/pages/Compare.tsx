import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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
import { legendLabel, tooltipStyle, useChartTheme } from '../theme/useChartTheme'
import { PlayerName } from '../components/PlayerName'
import {
  EmptyState,
  PageHeader,
  Panel,
  Provenance,
  fieldClass,
  fieldLabelClass,
} from '../components/ui'

/*
 * Colour here follows the player, not their rank, so the mapping learned in
 * the identity header holds for every mark below it. Player A takes
 * categorical slot 1 and player B slot 2 - the first two of the fixed order
 * defined in index.css, which is validated as a set in both themes.
 *
 * The values are read from the stylesheet rather than written here. They used
 * to be literals copied from the dark palette, which was correct until a light
 * theme existed and then rendered a dark-tuned pair on white.
 */
const SCOPES = [
  { value: '', label: 'All Internationals' },
  { value: 'tests', label: 'Tests' },
  { value: 'odis', label: 'ODIs' },
  { value: 't20is', label: 'T20Is' },
  { value: 'psl', label: 'PSL' },
]

function fmt(value: number | null, format: string): string {
  if (value === null || value === undefined) return '-'
  if (format === 'int') return Math.round(value).toLocaleString()
  return value.toFixed(2)
}

/** One head-to-head row: both values, with the winning side emphasised. */
function MetricRow({ metric, nameA, nameB }: { metric: ComparisonMetric; nameA: string; nameB: string }) {
  const chart = useChartTheme()
  const total = (Math.abs(metric.a ?? 0) || 0) + (Math.abs(metric.b ?? 0) || 0)
  const pctA = total > 0 ? ((Math.abs(metric.a ?? 0) / total) * 100).toFixed(1) : '50'
  const win = (side: 'a' | 'b') => metric.better === side

  // Leading in a comparison is not the same claim as "above baseline", so the
  // winner is marked with weight rather than with the semantic green.
  const figure = (side: 'a' | 'b') =>
    `tnum text-sm ${win(side) ? 'font-semibold text-ink' : 'text-muted'}`

  return (
    <div className="border-b border-border-subtle py-3 last:border-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className={figure('a')}>{fmt(metric.a, metric.format)}</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
          {metric.label}
          {metric.lower_is_better && <span className="ml-1 normal-case text-dim">(lower is better)</span>}
        </span>
        <span className={figure('b')}>{fmt(metric.b, metric.format)}</span>
      </div>
      {/* Proportional bar, with a 2px surface gap so the boundary reads even
          where the two hues sit close in value.

          Drawn only for higher-is-better metrics. Bar length encodes
          magnitude, and for a metric like bowling average magnitude runs
          opposite to quality -- a 107 average would take the longer bar while
          being far the worse figure, so the picture would contradict the
          verdict beside it. Those rows get a winner marker instead. */}
      {metric.lower_is_better ? (
        <div className="mt-1.5 flex justify-between text-[11px] text-dim">
          <span>{metric.better === 'a' ? '▲ better' : ''}</span>
          <span>{metric.better === 'b' ? 'better ▲' : ''}</span>
        </div>
      ) : (
        <div className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-sunken">
          <div
            style={{ width: `${pctA}%`, backgroundColor: chart.series[0] }}
            className="rounded-l-full"
            title={`${nameA}: ${fmt(metric.a, metric.format)}`}
          />
          <div className="w-0.5 shrink-0 bg-surface" />
          <div
            style={{ width: `calc(${100 - Number(pctA)}% - 2px)`, backgroundColor: chart.series[1] }}
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
 * make most of them unselectable - "compare any two players" has to mean any.
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

  // A player chosen in the URL rather than in this dropdown - arriving from a
  // profile's "compare" link, or from a shared comparison - is very unlikely to
  // sit in the default first fifty. Resolve their name directly so the control
  // shows who is selected, instead of reading "Select a player…" underneath a
  // comparison that is already using them.
  useEffect(() => {
    if (!value || value === selected?.identifier) return
    if (options.some((p) => p.identifier === value)) return
    let cancelled = false
    api
      .playerDetail(value)
      .then((p) => {
        if (cancelled) return
        setSelected({
          identifier: p.identifier,
          name: p.name,
          scorecard_name: p.scorecard_name,
          gender: p.gender,
          country: p.country,
          country_code: p.country_code,
          matches: p.by_competition.reduce((sum, c) => sum + c.matches, 0),
          status: p.status,
        })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [value, options, selected])

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
      <label className={fieldLabelClass}>{label}</label>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search all players…"
        className={fieldClass}
      />
      <select
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          setSelected(options.find((p) => p.identifier === e.target.value) ?? selected)
        }}
        className={fieldClass}
      >
        <option value="">Select a player…</option>
        {listed.map((p) => (
          <option key={p.identifier} value={p.identifier}>
            {p.name} ({p.matches})
          </option>
        ))}
      </select>
      {total > listed.length && (
        <p className="tnum text-xs text-dim">
          Showing {listed.length} of {total.toLocaleString()} - type to narrow.
        </p>
      )}
    </div>
  )
}

export function Compare() {
  const { slug, apiGender } = useGender()
  const chart = useChartTheme()
  const [params, setParams] = useSearchParams()

  // The selection lives in the URL, not in component state, so a comparison is
  // a link a scout can send to a colleague (§24). It is also what makes the
  // "Compare with another player" link on a profile work: that link arrives as
  // ?a=<identifier>, and state held only in the component would ignore it and
  // land the reader on an empty picker.
  const a = params.get('a') ?? ''
  const b = params.get('b') ?? ''
  const scope = params.get('scope') ?? ''

  const [data, setData] = useState<PlayerComparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v)
      else merged.delete(k)
    }
    setParams(merged, { replace: true })
  }

  // Each picker searches within the current gender, so a cross-gender pairing
  // can't even be expressed in the UI (the API rejects it too). Switching
  // gender clears the pair rather than carrying over foreign identifiers.
  //
  // Keyed off an actual *change* rather than firing on mount: on first render
  // this would otherwise wipe the ?a= that a profile link just navigated with.
  const previousGender = useRef(apiGender)
  useEffect(() => {
    if (previousGender.current === apiGender) return
    previousGender.current = apiGender
    setData(null)
    setParams(new URLSearchParams(), { replace: true })
  }, [apiGender, setParams])

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

  const hasWickets = data && data.season_wickets.some((p) => p.a > 0 || p.b > 0)

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

  const seriesLegend = data && (
    <div className="flex gap-3 text-xs text-muted">
      {(['a', 'b'] as const).map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          <span
            className="h-2 w-2 rounded-full"
            style={{ backgroundColor: chart.series[s === 'a' ? 0 : 1] }}
            aria-hidden
          />
          {data[s].name}
        </span>
      ))}
    </div>
  )

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Scout"
        title="Compare Players"
        blurb="Head-to-head within one competition at a time - international and franchise figures are never summed together."
      />

      <div className="grid gap-4 rounded-xl border border-border-subtle bg-surface p-4 shadow-card sm:grid-cols-3">
        <PlayerPicker
          label="Player A"
          value={a}
          apiGender={apiGender}
          exclude={b}
          onChange={(v) => update({ a: v })}
        />
        <PlayerPicker
          label="Player B"
          value={b}
          apiGender={apiGender}
          exclude={a}
          onChange={(v) => update({ b: v })}
        />
        <div className="space-y-2">
          <label className={fieldLabelClass}>Scope</label>
          <select value={scope} onChange={(e) => update({ scope: e.target.value })} className={fieldClass}>
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
        <EmptyState
          title="Pick two players to compare"
          hint="Search either picker above by name. Both players must be in the same gender's register - an identifier from one is meaningless in the other."
        />
      ) : null}

      {data && !loading && (
        <>
          {/* Identity header - colour is introduced here and reused for every
              mark below, so a reader learns the mapping once. */}
          <div className="grid gap-4 sm:grid-cols-2">
            {(['a', 'b'] as const).map((side) => {
              const p = data[side]
              return (
                <div
                  key={side}
                  className="rounded-xl border border-border-subtle bg-surface shadow-card p-4"
                  style={{
                    borderTopColor: chart.series[side === 'a' ? 0 : 1],
                    borderTopWidth: 3,
                  }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <PlayerAvatar src={p.bio.image_url} alt={p.name} className="h-10 w-10" />
                    <PlayerName
                      name={p.name}
                      country={p.country}
                      countryCode={p.country_code}
                      to={`/${slug}/players/${p.identifier}`}
                      className="text-lg font-semibold text-ink"
                    />
                    <StatusBadge status={p.status} />
                  </div>
                  <p className="mt-1 text-sm text-muted">
                    <span className="tnum">
                      {p.career_span.filter(Boolean).join('–') || 'Span unknown'}
                    </span>
                    {p.teams.length > 0 && ` · ${p.teams.map((t) => t.name).join(', ')}`}
                  </p>
                  <p className="mt-1 text-xs text-dim">
                    {p.bio.date_of_birth ? `Born ${p.bio.date_of_birth}` : 'Born: Not available'}
                    {p.bio.birth_place ? ` · ${p.bio.birth_place}` : ''}
                  </p>
                  {p.icc_rankings.length > 0 && (
                    <p className="mt-2 text-xs text-muted">
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

          {/* Legend is always present for two series: identity must never rest
              on colour alone. */}
          <Panel title={`Head to head - ${data.scope_label}`} aside={seriesLegend}>
            {data.metrics.map((m) => (
              <MetricRow key={m.key} metric={m} nameA={data.a.name} nameB={data.b.name} />
            ))}
            <div className="mt-3">
              <Provenance>
                Rate metrics (averages, strike rate, economy) declare a winner only when both
                players clear a minimum volume - otherwise the numbers are shown without a verdict.
              </Provenance>
            </div>
          </Panel>

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Runs by season">
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={data.season_runs} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="season" tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={tooltipStyle(chart)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} formatter={legendLabel(chart)} />
                  <Line
                    type="monotone" dataKey="a" name={data.a.name} stroke={chart.series[0]}
                    strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} isAnimationActive={false}
                  />
                  <Line
                    type="monotone" dataKey="b" name={data.b.name} stroke={chart.series[1]}
                    strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </Panel>

            {hasWickets && (
              <Panel title="Wickets by season">
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart
                    data={data.season_wickets}
                    margin={{ top: 4, right: 8, bottom: 0, left: -12 }}
                  >
                    <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="season" tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} />
                    <YAxis tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={tooltipStyle(chart)} />
                    <Legend wrapperStyle={{ fontSize: 12 }} formatter={legendLabel(chart)} />
                    <Line
                      type="monotone" dataKey="a" name={data.a.name} stroke={chart.series[0]}
                      strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} isAnimationActive={false}
                    />
                    <Line
                      type="monotone" dataKey="b" name={data.b.name} stroke={chart.series[1]}
                      strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </Panel>
            )}

            <Panel title="Runs by competition">
              <p className="-mt-2 mb-2 text-xs text-dim">Shown side by side, never added together.</p>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={byCompetition} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="competition" tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={tooltipStyle(chart)} cursor={{ fill: 'transparent' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} formatter={legendLabel(chart)} />
                  <Bar dataKey="a" name={data.a.name} fill={chart.series[0]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="b" name={data.b.name} fill={chart.series[1]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}
