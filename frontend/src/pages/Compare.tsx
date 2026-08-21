import { useEffect, useMemo, useRef, useState } from 'react'
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
import { useFilters } from '../state/useFilters'
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
 * the identity header holds for every mark below it. Players take categorical
 * slots in order, from the fixed sequence defined in index.css, which is
 * validated as a set in both themes.
 *
 * The values are read from the stylesheet rather than written here. They used
 * to be literals copied from the dark palette, which was correct until a light
 * theme existed and then rendered a dark-tuned pair on white.
 */

/*
 * §13 asks for 2-5 players and the API allows 5. This page allows FOUR, and the
 * limit comes from the design system rather than from the data: index.css
 * defines and CVD-validates exactly four categorical series, and identity here
 * rests on colour across three charts. A fifth player would need either an
 * unvalidated fifth hue or a chart where two players share one - and a
 * comparison in which two columns are the same colour is worse than a
 * comparison of four. The cap is stated on the page, not just enforced.
 */
const MAX_PLAYERS = 4

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

/**
 * One metric across every player, with the leader emphasised.
 *
 * Two markers, and both matter:
 *
 * - The **leader** is emphasised only when the API named one. It returns
 *   `best_index: null` on a tie, because highlighting one of two equal figures
 *   asserts a difference that is not there.
 * - An **unqualified** figure is greyed and carries the reason. A rate needs a
 *   sample before it means anything, and the threshold applies per player, not
 *   to the set: MS Dhoni's 36 balls bowled give him a bowling average of 31.00
 *   which is true, unmeaningful, and must not win the row - while Rohit
 *   Sharma's 610 balls in the same row are perfectly comparable.
 *
 * The bar is drawn as a share of the row's total, and only for
 * higher-is-better metrics. On a lower-is-better one a longer bar would mean
 * worse, which no reader expects.
 */
function MetricRow({
  metric,
  names,
  colours,
}: {
  metric: ComparisonMetric
  names: string[]
  colours: string[]
}) {
  const magnitudes = metric.values.map((v) => Math.abs(v ?? 0))
  const total = magnitudes.reduce((sum, v) => sum + v, 0)
  const drawBars = !metric.lower_is_better && total > 0

  const gateNote = metric.gate_field
    ? `needs ${metric.gate_min?.toLocaleString()} ${metric.gate_field.replace(/_/g, ' ')} to be comparable`
    : undefined

  return (
    <div className="border-b border-border-subtle py-2.5 last:border-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="u-eyebrow">
          {metric.label}
          {metric.lower_is_better && (
            <span className="ml-1 normal-case text-dim">(lower is better)</span>
          )}
        </span>
      </div>

      <div
        className="mt-1.5 grid gap-2"
        style={{ gridTemplateColumns: `repeat(${metric.values.length}, minmax(0, 1fr))` }}
      >
        {metric.values.map((value, i) => {
          const leads = metric.best_index === i
          const thin = !metric.qualified[i]
          return (
            <div key={i} className="min-w-0">
              <div
                className={`tnum truncate text-sm ${
                  thin ? 'text-dim' : leads ? 'font-semibold text-ink' : 'text-muted'
                }`}
                title={
                  thin
                    ? `${names[i]}: ${fmt(value, metric.format)} - ${gateNote ?? 'not comparable'}`
                    : `${names[i]}: ${fmt(value, metric.format)}`
                }
              >
                {leads && (
                  <span aria-hidden className="mr-0.5 text-positive-ink">
                    &#9650;
                  </span>
                )}
                {fmt(value, metric.format)}
                {leads && <span className="sr-only"> - best of this group</span>}
                {thin && <span className="sr-only"> - not comparable, {gateNote}</span>}
              </div>
              {/* Bar length encodes share of the row, not absolute standard. */}
              <div className="par-track mt-1 h-1 overflow-hidden rounded-full bg-sunken">
                {drawBars && !thin && (
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(magnitudes[i] / total) * 100}%`,
                      backgroundColor: colours[i],
                    }}
                  />
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

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
  /** Identifiers already chosen elsewhere, so a player cannot be added twice -
   *  the API rejects a duplicate, and the picker should not offer one. */
  exclude: string[]
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
    const base = options.filter((p) => !exclude.includes(p.identifier))
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
  const f = useFilters()
  const { params, set, clear } = f

  // The selection lives in the URL, not in component state, so a comparison is
  // a link a scout can send to a colleague (§27). It is also what makes the
  // "Compare with another player" link on a profile work: that link arrives as
  // ?a=<identifier>, and state held only in the component would ignore it and
  // land the reader on an empty picker.
  //
  // `?a=&b=` is still read, because links shared before this page supported
  // more than two players have to keep resolving. The canonical form is
  // `?players=x,y,z`, and a legacy link is rewritten to it on arrival so
  // copying the URL again yields the new form.
  const scope = f.get('scope')
  const chosen = useMemo(() => {
    const listed = (params.get('players') ?? '')
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean)
    if (listed.length) return listed.slice(0, MAX_PLAYERS)
    return [params.get('a') ?? '', params.get('b') ?? ''].filter(Boolean)
  }, [params])

  const [data, setData] = useState<PlayerComparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function setChosen(next: string[]) {
    const kept = next.filter(Boolean)
    // The legacy pair is cleared in the same write once the canonical parameter
    // is set, or the two would disagree and `chosen` would silently prefer one.
    set({ players: kept.join(','), a: null, b: null })
  }

  function setScope(value: string) {
    set({ scope: value })
  }

  // Each picker searches within the current gender, so a cross-gender set
  // cannot even be expressed in the UI (the API rejects it too). Switching
  // gender clears the selection rather than carrying over foreign identifiers.
  //
  // Keyed off an actual *change* rather than firing on mount: on first render
  // this would otherwise wipe the ?players= a profile link just navigated with.
  const previousGender = useRef(apiGender)
  useEffect(() => {
    if (previousGender.current === apiGender) return
    previousGender.current = apiGender
    setData(null)
    clear()
  }, [apiGender, clear])

  const key = chosen.join(',')
  useEffect(() => {
    const ids = key.split(',').filter(Boolean)
    if (ids.length < 2) {
      setData(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .comparePlayers(ids, scope ? { competition: scope } : {})
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [key, scope])

  const names = data?.sides.map((s) => s.name) ?? []
  const colours = data?.sides.map((_, i) => chart.series[i % chart.series.length]) ?? []

  // Recharts addresses a series by a flat key, so the positional `values` array
  // is spread into p0..pN columns. Done here rather than server-side because it
  // is a rendering detail of one chart library, not a property of the data.
  const flatten = (rows: { season: string; values: number[] }[]) =>
    rows.map((row) => {
      const out: Record<string, string | number> = { season: row.season }
      row.values.forEach((v, i) => {
        out[`p${i}`] = v
      })
      return out
    })

  const runsBySeason = useMemo(
    () => flatten((data?.season_runs ?? []) as { season: string; values: number[] }[]),
    [data],
  )
  const wicketsBySeason = useMemo(
    () => flatten((data?.season_wickets ?? []) as { season: string; values: number[] }[]),
    [data],
  )
  const hasWickets = (data?.season_wickets ?? []).some((row) =>
    ((row as { values: number[] }).values ?? []).some((v) => v > 0),
  )

  const byCompetition = useMemo(() => {
    if (!data) return []
    const keys = new Set(
      data.sides.flatMap((s) => s.by_competition.map((c) => c.competition_key)),
    )
    return [...keys].map((competitionKey) => {
      const row: Record<string, string | number> = {
        competition:
          data.sides
            .flatMap((s) => s.by_competition)
            .find((c) => c.competition_key === competitionKey)?.display_name ?? competitionKey,
      }
      data.sides.forEach((side, i) => {
        row[`p${i}`] =
          side.by_competition.find((c) => c.competition_key === competitionKey)?.runs ?? 0
      })
      return row
    })
  }, [data])

  const seriesLegend = data && (
    <div className="flex flex-wrap gap-3 text-xs text-muted">
      {data.sides.map((side, i) => (
        <span key={side.identifier} className="inline-flex items-center gap-1.5">
          <span
            className="h-2 w-2 rounded-full"
            style={{ backgroundColor: colours[i] }}
            aria-hidden
          />
          {side.name}
        </span>
      ))}
    </div>
  )

  // One picker per chosen player, plus an empty one while there is room. The
  // empty slot is how a third and fourth player get added, so it is a control
  // rather than a placeholder.
  const slots = chosen.length < MAX_PLAYERS ? [...chosen, ''] : chosen

  const lines = (dataKeyPrefix: string) =>
    (data?.sides ?? []).map((side, i) => (
      <Line
        key={side.identifier}
        type="monotone"
        dataKey={`${dataKeyPrefix}${i}`}
        name={side.name}
        stroke={colours[i]}
        strokeWidth={2}
        dot={{ r: 3 }}
        activeDot={{ r: 5 }}
        isAnimationActive={false}
      />
    ))

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Players"
        title="Compare Players"
        blurb="Two to four players within one competition at a time - international and franchise figures are never summed together."
      />

      <div className="space-y-4 rounded-xl border border-border-subtle bg-surface p-4 shadow-card">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {slots.map((identifier, i) => (
            <div key={i} className="space-y-1.5">
              <PlayerPicker
                label={i < chosen.length ? `Player ${i + 1}` : 'Add a player'}
                value={identifier}
                apiGender={apiGender}
                exclude={chosen.filter((_, j) => j !== i)}
                onChange={(v) => {
                  const next = [...chosen]
                  if (i < next.length) next[i] = v
                  else if (v) next.push(v)
                  setChosen(next.filter(Boolean))
                }}
              />
              {i < chosen.length && chosen.length > 2 && (
                <button
                  type="button"
                  onClick={() => setChosen(chosen.filter((_, j) => j !== i))}
                  className="text-xs text-muted hover:text-negative-ink"
                >
                  Remove
                </button>
              )}
            </div>
          ))}
          <div className="space-y-2">
            <label className={fieldLabelClass}>Scope</label>
            <select value={scope} onChange={(e) => setScope(e.target.value)} className={fieldClass}>
              {SCOPES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {chosen.length >= MAX_PLAYERS && (
          <p className="text-xs text-dim">
            Four is the limit here. Identity across the charts below rests on colour, and the
            categorical palette is validated for four series in both themes - a fifth would mean
            two players sharing a colour, which is worse than comparing four.
          </p>
        )}
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner />}

      {chosen.length < 2 ? (
        <EmptyState
          title="Pick at least two players to compare"
          hint="Search any picker above by name. Every player must be in the same gender's register - an identifier from one is meaningless in the other."
        />
      ) : null}

      {data && !loading && (
        <>
          {/* Identity header - colour is introduced here and reused for every
              mark below, so a reader learns the mapping once. */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {data.sides.map((p, i) => (
              <div
                key={p.identifier}
                className="rounded-xl border border-border-subtle bg-surface p-4 shadow-card"
                style={{ borderTopColor: colours[i], borderTopWidth: 3 }}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <PlayerAvatar src={p.bio.image_url} alt={p.name} className="h-10 w-10" />
                  <PlayerName
                    name={p.name}
                    country={p.country}
                    countryCode={p.country_code}
                    to={`/${slug}/players/${p.identifier}`}
                    className="text-base font-semibold text-ink"
                  />
                  <StatusBadge status={p.status} />
                </div>
                <p className="mt-1 text-sm text-muted">
                  <span className="tnum">
                    {p.career_span.filter(Boolean).join('\u2013') || 'Span unknown'}
                  </span>
                </p>
                <p className="mt-1 text-xs text-dim">
                  {p.teams.length > 0 ? p.teams.map((t) => t.name).join(', ') : 'No teams recorded'}
                </p>
                <p className="mt-1 text-xs text-dim">
                  {p.bio.date_of_birth ? `Born ${p.bio.date_of_birth}` : 'Born: Not available'}
                  {p.bio.birth_place ? ` \u00b7 ${p.bio.birth_place}` : ''}
                </p>
                {p.icc_rankings.length > 0 && (
                  <p className="mt-2 text-xs text-muted">
                    ICC:{' '}
                    {p.icc_rankings
                      .map((r) => `#${r.position} ${r.rank_type.replace('-', ' ')}`)
                      .join(' \u00b7 ')}
                  </p>
                )}
              </div>
            ))}
          </div>

          {/* Legend is always present: identity must never rest on colour alone. */}
          <Panel title={`Head to head - ${data.scope_label}`} aside={seriesLegend}>
            {/* Column headings, so a figure can be read back to a player
                without counting across from the legend. */}
            <div
              className="mb-1 grid gap-2 border-b border-border-default pb-1.5"
              style={{ gridTemplateColumns: `repeat(${data.sides.length}, minmax(0, 1fr))` }}
            >
              {data.sides.map((side, i) => (
                <span
                  key={side.identifier}
                  className="truncate font-mono text-[10px] uppercase tracking-[0.08em]"
                  style={{ color: colours[i] }}
                  title={side.name}
                >
                  {side.name}
                </span>
              ))}
            </div>
            {data.metrics.map((m) => (
              <MetricRow key={m.key} metric={m} names={names} colours={colours} />
            ))}
            <div className="mt-3">
              <Provenance>
                A rate (average, strike rate, economy) declares a leader only among players who
                clear a minimum volume. A player below it keeps their figure, greyed, because the
                number is a fact about them but not a comparable one - and the threshold applies per
                player, so one thin sample does not blank the row for everybody.
              </Provenance>
            </div>
          </Panel>

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Runs by season">
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={runsBySeason} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="season" tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={tooltipStyle(chart)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} formatter={legendLabel(chart)} />
                  {lines('p')}
                </LineChart>
              </ResponsiveContainer>
            </Panel>

            {hasWickets && (
              <Panel title="Wickets by season">
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart
                    data={wicketsBySeason}
                    margin={{ top: 4, right: 8, bottom: 0, left: -12 }}
                  >
                    <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="season" tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} />
                    <YAxis tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={tooltipStyle(chart)} />
                    <Legend wrapperStyle={{ fontSize: 12 }} formatter={legendLabel(chart)} />
                    {lines('p')}
                  </LineChart>
                </ResponsiveContainer>
              </Panel>
            )}

            <Panel title="Runs by competition">
              <p className="-mt-2 mb-2 text-xs text-dim">
                Shown side by side, never added together.
              </p>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={byCompetition} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="competition" tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fill: chart.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={tooltipStyle(chart)} cursor={{ fill: 'transparent' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} formatter={legendLabel(chart)} />
                  {data.sides.map((side, i) => (
                    <Bar
                      key={side.identifier}
                      dataKey={`p${i}`}
                      name={side.name}
                      fill={colours[i]}
                      radius={[4, 4, 0, 0]}
                      isAnimationActive={false}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}
