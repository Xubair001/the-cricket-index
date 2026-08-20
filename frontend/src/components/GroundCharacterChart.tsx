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
import type { GroundCharacter } from '../api/types'
import type { ApiGender } from '../gender/useGender'
import { EmptyState, Panel } from './ui'
import { rate } from '../format'
import { useChartTheme } from '../theme/useChartTheme'

/**
 * Which grounds produce which cricket, in one competition.
 *
 * A ground page answers "what kind of cricket does THIS ground produce". It
 * cannot answer the question a touring side or a selector asks first, which is
 * how a ground compares with the others they will play on - and that needs every
 * ground on one scale at once.
 *
 * Both axes are indices against the competition's OWN par, with the datum at
 * 1.00, which is the same device the par meter uses everywhere else in this
 * product. That is what makes the quadrants mean something:
 *
 *     scoring high, wickets hard    a batting ground - big first innings
 *     scoring high, wickets easy    fast cricket both ways, results
 *     scoring low,  wickets hard    attritional - hard to score, hard to bowl out
 *     scoring low,  wickets easy    a bowler's ground
 *
 * Scoped to one competition because a ground hosting Tests and T20Is has two
 * characters and one figure describes neither. That is also why the endpoint
 * refuses to answer without a competition rather than defaulting to one.
 *
 * Colour is NOT a fourth variable here. It carries the bat-first record, which
 * is the third genuinely useful fact about a pitch, and it uses the semantic
 * positive/negative pair rather than a categorical one - because unlike role or
 * team, "batting first wins more often" has a direction.
 */

/** Below this a ground's rates describe a handful of matches, not a pitch. */
const DEFAULT_MIN_MATCHES = 8

type Point = {
  venue: string
  city: string | null
  x: number
  y: number
  z: number
  batFirst: number | null
  reliable: boolean
}

export function GroundCharacterChart({
  gender,
  competition,
  competitionLabel,
}: {
  gender: ApiGender
  competition: string
  competitionLabel: string
}) {
  const chart = useChartTheme()
  const [rows, setRows] = useState<GroundCharacter[] | null>(null)
  const [minMatches, setMinMatches] = useState(DEFAULT_MIN_MATCHES)

  useEffect(() => {
    if (!competition) return
    let cancelled = false
    setRows(null)
    api
      .groundCharacter(gender, competition, { min_matches: 1 })
      .then((d) => {
        if (!cancelled) setRows(d)
      })
      .catch(() => {
        if (!cancelled) setRows([])
      })
    return () => {
      cancelled = true
    }
  }, [gender, competition])

  const points: Point[] = useMemo(
    () =>
      (rows ?? [])
        .filter(
          (g) =>
            g.matches >= minMatches &&
            typeof g.scoring_index === 'number' &&
            typeof g.wicket_index === 'number',
        )
        .map((g) => ({
          venue: g.venue,
          city: g.city,
          x: g.scoring_index as number,
          y: g.wicket_index as number,
          z: g.matches,
          batFirst: g.bat_first_win_pct,
          reliable: g.reliable,
        })),
    [rows, minMatches],
  )

  if (rows === null) {
    return (
      <Panel title="Ground character">
        <div className="h-64 animate-pulse rounded-lg bg-sunken" />
      </Panel>
    )
  }
  if (points.length < 4) {
    return (
      <Panel title="Ground character">
        <EmptyState
          title="Not enough grounds in this competition to compare"
          hint={`Only ${points.length} ground${points.length === 1 ? '' : 's'} has at least ${minMatches} matches here. Lower the threshold or pick a competition with more cricket.`}
        />
      </Panel>
    )
  }

  // Colour by bat-first record, and the fill is a DIRECTION rather than an
  // identity, so the semantic pair is right and a categorical palette would be
  // wrong. A ground with too few decided matches gets the neutral mark rather
  // than being coloured on noise.
  const fillFor = (p: Point) => {
    if (p.batFirst === null) return chart.axis
    if (p.batFirst >= 55) return chart.positive
    if (p.batFirst <= 45) return chart.negative
    return chart.series[0]
  }

  return (
    <Panel
      title={`Ground character in ${competitionLabel} cricket`}
      blurb="Every ground on one scale, against this format's own par. 1.00 on either axis is typical, so a ground's position is its character rather than its raw figures - which cannot be compared across formats at all."
      aside={
        <label className="flex items-center gap-2 text-xs text-muted">
          <span className="u-eyebrow">Min matches</span>
          <input
            type="number"
            min={1}
            max={100}
            value={minMatches}
            onChange={(e) => setMinMatches(Math.max(1, Number(e.target.value) || 1))}
            className="tnum w-16 rounded-md border border-border-default bg-surface px-2 py-1 text-right text-ink"
          />
        </label>
      }
    >
      <ResponsiveContainer width="100%" height={380}>
        {/* Left margin has to make room for a ROTATED axis label. At -6 the
            label was clipped to a sliver against the plot edge. */}
        <ScatterChart margin={{ top: 10, right: 20, bottom: 14, left: 18 }}>
          <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="x"
            tick={{ fill: chart.axis, fontSize: 11 }}
            tickLine={false}
            tickFormatter={(v: number) => rate(v)}
            domain={[(v: number) => Math.max(0, v - 0.03), (v: number) => v + 0.03]}
            label={{
              value: 'Scoring rate against par  ->  higher scoring',
              position: 'insideBottom',
              offset: -8,
              fill: chart.axis,
              fontSize: 11,
            }}
          />
          <YAxis
            type="number"
            dataKey="y"
            tick={{ fill: chart.axis, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => rate(v)}
            domain={[(v: number) => Math.max(0, v - 0.03), (v: number) => v + 0.03]}
            label={{
              value: 'Wickets harder to take  ->',
              angle: -90,
              position: 'insideLeft',
              offset: 8,
              style: { textAnchor: 'middle' },
              fill: chart.axis,
              fontSize: 11,
            }}
          />
          {/* Dot area is matches, so a ground with 60 Tests does not look like
              one with nine. */}
          <ZAxis type="number" dataKey="z" range={[50, 480]} />

          {/* The par datum on both axes. Not a median of the grounds on screen:
              par here is the competition's own measured figure, which is what
              makes 1.00 mean "typical for this format" rather than "typical of
              whichever grounds cleared the filter". */}
          <ReferenceLine x={1} stroke={chart.border} strokeWidth={1.5} />
          <ReferenceLine y={1} stroke={chart.border} strokeWidth={1.5} />

          <Tooltip
            content={({ payload }) => {
              const p = payload?.[0]?.payload as Point | undefined
              if (!p) return null
              return (
                <div className="rounded-lg border border-border-default bg-surface px-3 py-2 text-xs shadow-card">
                  <div className="font-semibold text-ink">{p.venue}</div>
                  {p.city && <div className="text-dim">{p.city}</div>}
                  <div className="tnum mt-1.5 text-muted">
                    Scoring {rate(p.x)}x par
                    {p.x >= 1 ? ' (higher scoring)' : ' (lower scoring)'}
                  </div>
                  <div className="tnum text-muted">
                    Wickets {rate(p.y)}x par
                    {p.y >= 1 ? ' (harder to take)' : ' (easier to take)'}
                  </div>
                  <div className="tnum text-muted">
                    Batting first wins {p.batFirst === null ? '-' : `${rate(p.batFirst)}%`}
                  </div>
                  <div className="tnum mt-1 text-dim">{p.z} matches</div>
                  {!p.reliable && (
                    <div className="mt-1 text-warning-ink">Too few matches to be a character</div>
                  )}
                </div>
              )
            }}
          />
          <Scatter data={points} isAnimationActive={false}>
            {points.map((p, i) => (
              <Cell key={i} fill={fillFor(p)} fillOpacity={p.reliable ? 0.75 : 0.35} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>

      <div className="mt-3 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        <Quadrant
          title="Top right: a batting ground"
          detail="Higher scoring and wickets harder to take. Big first innings, draws in Tests."
        />
        <Quadrant
          title="Bottom right: fast cricket"
          detail="Higher scoring but wickets fall. Results rather than attrition."
        />
        <Quadrant
          title="Top left: attritional"
          detail="Hard to score and hard to bowl a side out. Patience wins."
        />
        <Quadrant
          title="Bottom left: a bowler's ground"
          detail="Lower scoring and wickets fall. Low totals defended successfully."
        />
      </div>

      <p className="u-note mt-3">
        {points.length} grounds with at least {minMatches} matches in {competitionLabel} cricket.
        Fill shows who wins batting first here:{' '}
        <span className="font-medium text-positive-ink">batting first favoured</span>,{' '}
        <span className="font-medium text-negative-ink">chasing favoured</span>, blue for even, and a
        neutral mark where too few matches were decided to say. Faded dots fall below the match count
        at which these rates describe a pitch rather than a handful of games - shown rather than
        dropped, so a thin ground is visible as thin.
      </p>
    </Panel>
  )
}

function Quadrant({ title, detail }: { title: string; detail: string }) {
  return (
    <p className="text-xs leading-relaxed text-muted">
      <span className="font-semibold text-ink">{title}.</span> {detail}
    </p>
  )
}

export default GroundCharacterChart
