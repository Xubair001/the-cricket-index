import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { api } from '../api/client'
import type { ExplorerKind, ExplorerRow } from '../api/types'
import type { ApiGender } from '../gender/useGender'
import { Panel } from './ui'
import { rate } from '../format'
import { tooltipStyle, useChartTheme } from '../theme/useChartTheme'

/**
 * The one chart a batting or bowling table cannot replace.
 *
 * A leaderboard sorted by average tells you who scores most per dismissal. It
 * cannot tell you the thing a selector actually wants, which is the SHAPE of a
 * player: two batters averaging 45 are different cricketers if one strikes at 75
 * and the other at 140, and no ordering of a single column shows that. Plotting
 * the two against each other does, at a glance, and puts every player in one of
 * four quadrants against the field's own medians:
 *
 *     high average, high strike rate   the players who decide matches
 *     high average, low strike rate    accumulators - anchors
 *     low average, high strike rate    hitters - impact without insurance
 *     low average, low strike rate     below the standard of this cut
 *
 * The reference lines are the MEDIANS OF THE ROWS ON SCREEN, not fixed
 * thresholds, so the quadrants mean "against this filtered field" and move with
 * the filters. A fixed line would be wrong the moment the reader narrows to one
 * format, because a Test strike rate of 55 and a T20I strike rate of 55 are not
 * the same statement.
 *
 * Bowling inverts: for an economy-versus-strike-rate plot, LOW is good on both
 * axes, so the axes are reversed and the good quadrant is bottom-left. The
 * labels are generated from the metric rather than hardcoded, so the chart can
 * never describe the wrong corner.
 *
 * Colour carries role, which is three values - the maximum the design system
 * allows on an all-pairs form like a scatter, where every series can sit beside
 * every other.
 */

type Axis = {
  key: string
  label: string
  /** True when a lower figure is better, which flips the axis and the labels. */
  lowerIsBetter?: boolean
}

const AXES: Record<ExplorerKind, { x: Axis; y: Axis; size: string; caption: string } | null> = {
  batting: {
    x: { key: 'strike_rate', label: 'Strike rate' },
    y: { key: 'average', label: 'Batting average' },
    size: 'runs',
    caption:
      'Average against strike rate. Two batters on the same average are different cricketers if one strikes at 75 and the other at 140, which is the thing a sorted column cannot show. Dot size is runs scored.',
  },
  bowling: {
    x: { key: 'economy', label: 'Economy', lowerIsBetter: true },
    y: { key: 'average', label: 'Bowling average', lowerIsBetter: true },
    size: 'wickets',
    caption:
      'Bowling average against economy, both of which are better lower, so the strongest bowlers sit bottom-left. It separates the bowler who takes wickets expensively from the one who simply does not concede. Dot size is wickets taken.',
  },
  // The all-round view is already expressed in par units on one axis, so a
  // second axis would be the same quantity twice.
  allround: null,
}

/** How many players to plot. Enough for a median to describe a field, and
 *  within the API's own page ceiling of 100. */
const FIELD_SIZE = 100

/** The filter set the page holds, passed straight through. */
export type ExplorerQuery = {
  competition?: string
  competition_type?: string
  opposition_team_id?: number
  date_from?: string
  date_to?: string
  min_innings?: number
  min_balls?: number
  role?: string
  venue?: string
}

const ROLE_LABEL: Record<string, string> = {
  batter: 'Batter',
  bowler: 'Bowler',
  allrounder: 'All-rounder',
}
const ROLE_ORDER = ['batter', 'allrounder', 'bowler']

function median(values: number[]): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

export function ExplorerScatter({
  kind,
  gender,
  query,
  scopeLabel,
}: {
  kind: ExplorerKind
  gender: ApiGender
  /** The page's live filters, so the chart describes the same cut as the table. */
  query: ExplorerQuery
  scopeLabel: string
}) {
  const chart = useChartTheme()
  const spec = AXES[kind]

  // The chart fetches its OWN field rather than plotting the table's page, and
  // the reason is the reference lines. The table shows 25 rows ordered by
  // whatever the reader sorted on, so their median is the median of the top 25
  // by that column - not of the field. Sorted by runs, every one of those 25 is
  // a high-volume player and the "median strike rate" is the median of the
  // heaviest scorers, which is a different and much higher number.
  //
  // So this asks for a wider slice under the same filters, ordered by
  // participation rather than by the metric being plotted, which is the one
  // ordering that does not bias either axis.
  const [rows, setRows] = useState<ExplorerRow[]>([])
  // The page rebuilds `query` on every render, so an identity comparison would
  // refetch forever. Serialised once here, and the effect depends on the string,
  // which is a value the dependency checker can actually see.
  const queryKey = JSON.stringify(query)
  useEffect(() => {
    if (!spec) return
    let cancelled = false
    api
      .explorer(kind, gender, {
        ...(JSON.parse(queryKey) as ExplorerQuery),
        sort_by: 'matches',
        limit: FIELD_SIZE,
        offset: 0,
      })
      .then((page) => {
        if (!cancelled) setRows(page.items)
      })
      .catch(() => {
        if (!cancelled) setRows([])
      })
    return () => {
      cancelled = true
    }
  }, [kind, gender, queryKey, spec])

  const points = useMemo(() => {
    if (!spec) return []
    return rows
      .map((r) => ({
        name: r.player_name,
        role: r.role ?? 'unknown',
        x: typeof r[spec.x.key] === 'number' ? (r[spec.x.key] as number) : null,
        y: typeof r[spec.y.key] === 'number' ? (r[spec.y.key] as number) : null,
        z: typeof r[spec.size] === 'number' ? (r[spec.size] as number) : 0,
      }))
      .filter((p) => typeof p.x === 'number' && typeof p.y === 'number')
  }, [rows, spec])

  if (!spec || points.length < 4) return null

  const xMedian = median(points.map((p) => p.x as number))
  const yMedian = median(points.map((p) => p.y as number))

  // Padding has to be PROPORTIONAL to each axis's own range, not a fixed
  // amount. A flat +/-5 is reasonable on strike rate, which spans 119 to 179,
  // and absurd on economy, which spans 2.5 to 4.5: it produced an axis running
  // -2.61 to 9.11 with every point squashed into the middle third, so the chart
  // showed no separation at all in the dimension it exists to show.
  // Clamped at zero, because none of these metrics can be negative: an average,
  // a strike rate and an economy all have a floor of 0. Proportional padding
  // alone pushed the axis to -8.96 on a batting board, which is not a value any
  // batter can hold and reads as a broken chart.
  const pad = (values: number[]): [number, number] => {
    const lo = Math.min(...values)
    const hi = Math.max(...values)
    const margin = (hi - lo) * 0.08 || Math.abs(hi) * 0.08 || 1
    return [Math.max(0, lo - margin), hi + margin]
  }
  const xDomain = pad(points.map((p) => p.x as number))
  const yDomain = pad(points.map((p) => p.y as number))

  const colourFor = (role: string) => {
    const index = ROLE_ORDER.indexOf(role)
    return chart.series[index >= 0 ? index : 3]
  }

  // Which corner is good depends on the metric, so the label is derived rather
  // than written. Getting this wrong would praise the worst players on screen.
  const bestCorner = spec.x.lowerIsBetter
    ? 'bottom-left'
    : 'top-right'

  return (
    <Panel
      title={`${spec.y.label} against ${spec.x.label}`}
      blurb={spec.caption}
      aside={
        <div className="flex flex-wrap gap-3 text-xs text-muted">
          {ROLE_ORDER.map((role) => (
            <span key={role} className="inline-flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: colourFor(role) }}
                aria-hidden
              />
              {ROLE_LABEL[role]}
            </span>
          ))}
        </div>
      }
    >
      <ResponsiveContainer width="100%" height={340}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: -8 }}>
          <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="x"
            name={spec.x.label}
            tick={{ fill: chart.axis, fontSize: 11 }}
            tickLine={false}
            domain={xDomain}
            tickFormatter={(v: number) => rate(v)}
            label={{
              value: spec.x.label + (spec.x.lowerIsBetter ? ' (lower is better)' : ''),
              position: 'insideBottom',
              offset: -4,
              fill: chart.axis,
              fontSize: 11,
            }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={spec.y.label}
            tick={{ fill: chart.axis, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            domain={yDomain}
            tickFormatter={(v: number) => rate(v)}
          />
          {/* Dot area carries volume. A rate computed off few balls should not
              look as substantial as one off thousands, and the volume filter
              above the table is a floor rather than a leveller. */}
          <ZAxis type="number" dataKey="z" range={[40, 420]} />

          {/* The field's own medians. Fixed thresholds would be wrong the moment
              the reader narrows to one format. */}
          {xMedian !== null && (
            <ReferenceLine
              x={xMedian}
              stroke={chart.border}
              strokeDasharray="4 4"
              label={{
                value: `median ${rate(xMedian)}`,
                position: 'insideTopRight',
                fill: chart.axis,
                fontSize: 10,
              }}
            />
          )}
          {yMedian !== null && (
            <ReferenceLine
              y={yMedian}
              stroke={chart.border}
              strokeDasharray="4 4"
              label={{
                value: `median ${rate(yMedian)}`,
                position: 'insideBottomLeft',
                fill: chart.axis,
                fontSize: 10,
              }}
            />
          )}

          {/* A custom renderer rather than `formatter`: the default puts the
              raw dataKeys (x, y, z) in front of the reader, and a scatter point
              needs the player's name, which is not on any axis. */}
          <Tooltip
            contentStyle={tooltipStyle(chart)}
            content={({ payload }) => {
              const p = payload?.[0]?.payload as
                | { name: string; role: string; x: number; y: number; z: number }
                | undefined
              if (!p) return null
              return (
                <div
                  className="rounded-lg border border-border-default bg-surface px-3 py-2 text-xs shadow-card"
                  style={{ minWidth: 160 }}
                >
                  <div className="font-semibold text-ink">{p.name}</div>
                  <div className="mt-0.5 text-dim">{ROLE_LABEL[p.role] ?? p.role} (inferred)</div>
                  <div className="tnum mt-1.5 text-muted">
                    {spec.y.label} {rate(p.y)}
                  </div>
                  <div className="tnum text-muted">
                    {spec.x.label} {rate(p.x)}
                  </div>
                  <div className="tnum text-muted">
                    {spec.size} {p.z.toLocaleString()}
                  </div>
                </div>
              )
            }}
          />
          <Scatter data={points} isAnimationActive={false}>
            {points.map((p, i) => (
              <Cell key={i} fill={colourFor(p.role)} fillOpacity={0.72} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>

      <p className="u-note mt-3">
        The {points.length} most experienced players matching these filters, within {scopeLabel}.
        Ordered by matches rather than by either axis, so neither is biased by the selection. The
        dashed lines are this field's own medians, so the quadrants describe the filtered set rather
        than cricket in general - narrow the filters and they move. The strongest players sit{' '}
        {bestCorner}. Role is <em>inferred</em> from each player's share of deliveries, never
        sourced.
      </p>
    </Panel>
  )
}

export default ExplorerScatter
