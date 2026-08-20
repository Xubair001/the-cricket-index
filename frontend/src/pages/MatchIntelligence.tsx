import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft } from '../components/Icon'
import { Link, useParams } from 'react-router-dom'
import {
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
import type { InningsIntelligence, MatchIntelligence as MatchIntel } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { useGender } from '../gender/useGender'
import { useChartTheme, legendLabel, tooltipStyle } from '../theme/useChartTheme'
import { rate } from '../format'
import {
  Card,
  PageHeader,
  Panel,
  Provenance,
  tableClass,
  tdClass,
  tdNumClass,
  thClass,
  thNumClass,
  theadRowClass,
  trClass,
} from '../components/ui'

/**
 * Match intelligence (§22) - what happened, and why it mattered.
 *
 * §22 is explicit that match pages do not compete with live-score products, so
 * this is deliberately not a scorecard: the scorecard lives on the match page
 * and says who scored what. This says which stand decided the innings and which
 * spell broke it.
 *
 * The lead device is the worm - cumulative runs against overs, one line per
 * innings, with the overs that took wickets marked. It is the standard cricket
 * reading of a match's shape, and it answers "when did this game turn" before a
 * reader has parsed a single figure.
 */

/** A stand below this is two batters briefly together, not a partnership. */
const NOTABLE_STAND = 30

/** Overs where a wicket fell get a visible marker; the rest stay quiet. */
function WicketDot(props: {
  cx?: number
  cy?: number
  payload?: Record<string, unknown>
  dataKey?: string
  stroke?: string
}) {
  const { cx, cy, payload, dataKey, stroke } = props
  const wickets = Number(payload?.[`${dataKey}_w`] ?? 0)
  if (!wickets || cx == null || cy == null) return null
  return <circle cx={cx} cy={cy} r={3.5} fill={stroke} stroke="var(--color-surface)" strokeWidth={1.5} />
}

export function MatchIntelligence() {
  const { slug } = useGender()
  const { matchId = '' } = useParams()
  const theme = useChartTheme()

  const [data, setData] = useState<MatchIntel | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .matchIntelligence(matchId)
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [matchId])

  /**
   * The worm. Each innings contributes a column keyed by over, plus a parallel
   * `_w` column carrying that over's wickets so the dot renderer can mark them
   * without a second pass over the data.
   */
  const worm = useMemo(() => {
    if (!data) return []
    const byOver = new Map<number, Record<string, number>>()
    for (const inn of data.innings) {
      for (const p of inn.overs) {
        const row = byOver.get(p.over) ?? { over: p.over + 1 }
        row[`i${inn.innings}`] = p.cumulative_runs
        row[`i${inn.innings}_w`] = p.wickets
        byOver.set(p.over, row)
      }
    }
    return [...byOver.values()].sort((a, b) => a.over - b.over)
  }, [data])

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorMessage message={error} />
  if (!data) return null

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Match"
        title="Match Intelligence"
        blurb="Which stand decided the innings, which spell broke it, and when the game turned."
        actions={
          <Link to={`/${slug}/matches/${matchId}`} className="text-sm text-analytic-ink hover:underline">
            <ArrowLeft className="mr-1" /> Scorecard
          </Link>
        }
      />

      <Panel
        title="How the innings unfolded"
        blurb="Cumulative runs against overs - the worm. A marked point is an over that took a wicket."
      >
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={worm} margin={{ top: 4, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={theme.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="over"
              tick={{ fill: theme.axis, fontSize: 11 }}
              tickLine={false}
              label={{ value: 'Over', position: 'insideBottomRight', offset: -2, fill: theme.axis, fontSize: 11 }}
            />
            <YAxis tick={{ fill: theme.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={tooltipStyle(theme)} />
            <Legend wrapperStyle={{ fontSize: 12 }} formatter={legendLabel(theme)} />
            {data.innings.map((inn, i) => (
              <Line
                key={inn.innings}
                type="monotone"
                dataKey={`i${inn.innings}`}
                name={`${inn.batting_team ?? `Innings ${inn.innings}`}${
                  data.innings.length > 2 ? ` (${inn.innings})` : ''
                }`}
                stroke={theme.series[i % 4]}
                strokeWidth={2}
                // Animation off: §23 asks for it, and a Recharts mount
                // animation also photographs as an empty chart.
                isAnimationActive={false}
                dot={<WicketDot />}
                activeDot={{ r: 5 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
        <Provenance>
          Read off the stored deliveries. Wickets exclude retirements, which end a stand without
          being a dismissal.
        </Provenance>
      </Panel>

      {data.innings.map((inn) => (
        <InningsPanel key={inn.innings} inn={inn} multiple={data.innings.length > 2} />
      ))}

      {/* What §22 defers, stated rather than left as an absence. */}
      <Card className="border-border-subtle">
        <p className="text-sm text-ink">Not shown here, and why</p>
        <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
          {Object.entries(data.deferred).map(([key, reason]) => (
            <li key={key}>
              <span className="text-ink">{key.replace(/_/g, ' ')}</span> - {reason}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

function InningsPanel({ inn, multiple }: { inn: InningsIntelligence; multiple: boolean }) {
  const stands = inn.partnerships.filter((p) => p.runs >= NOTABLE_STAND)
  const spells = [...inn.spells].sort((a, b) => b.wickets - a.wickets || (a.economy ?? 99) - (b.economy ?? 99))

  return (
    <Panel
      title={
        <>
          {inn.batting_team ?? `Innings ${inn.innings}`}
          {multiple && <span className="ml-2 text-muted">innings {inn.innings}</span>}
        </>
      }
      blurb={
        <>
          <span className="tnum">
            {inn.runs}/{inn.wickets}
          </span>{' '}
          off <span className="tnum">{inn.balls}</span> balls, run rate{' '}
          <span className="tnum">{rate(inn.run_rate)}</span>.
        </>
      }
      bodyClassName=""
    >
      <div className="grid gap-0 lg:grid-cols-2 lg:divide-x lg:divide-border-subtle">
        <div className="min-w-0">
          <h3 className="u-eyebrow px-4 pt-4">Partnerships</h3>
          {stands.length === 0 ? (
            <p className="px-4 py-4 text-sm text-muted">No stand reached {NOTABLE_STAND}.</p>
          ) : (
            <div className="scroll-x">
              <table className={`${tableClass} mt-2`}>
                <thead>
                  <tr className={theadRowClass}>
                    <th className={thClass}>Wkt</th>
                    <th className={thClass}>Pair</th>
                    <th className={thNumClass}>Runs</th>
                    <th className={thNumClass}>Balls</th>
                    <th className={thNumClass}>RR</th>
                  </tr>
                </thead>
                <tbody>
                  {stands.map((p) => (
                    <tr key={`${p.wicket}-${p.batter_a}`} className={trClass}>
                      <td className={`${tdNumClass} text-dim`}>{p.wicket}</td>
                      <td className={tdClass}>
                        {p.batter_a} &amp; {p.batter_b}
                        {p.unbroken && (
                          <span className="ml-1.5 text-xs text-muted" title="Still together when the innings ended">
                            *
                          </span>
                        )}
                        <span className="mt-0.5 block text-xs text-dim">
                          overs {p.start_over + 1}–{p.end_over + 1}
                          {p.ended_by && ` · ended ${p.ended_by}`}
                        </span>
                      </td>
                      <td className="tnum px-3 py-2.5 text-right font-semibold text-ink">{p.runs}</td>
                      <td className={tdNumClass}>{p.balls}</td>
                      <td className={tdNumClass}>{rate(p.run_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="min-w-0">
          <h3 className="u-eyebrow px-4 pt-4">Bowling spells</h3>
          <div className="scroll-x">
            <table className={`${tableClass} mt-2`}>
              <thead>
                <tr className={theadRowClass}>
                  <th className={thClass}>Bowler</th>
                  <th className={thNumClass}>Ov</th>
                  <th className={thNumClass}>Figures</th>
                  <th className={thNumClass}>Econ</th>
                </tr>
              </thead>
              <tbody>
                {spells.slice(0, 8).map((s, i) => (
                  <tr key={`${s.bowler}-${s.start_over}-${i}`} className={trClass}>
                    <td className={tdClass}>
                      {s.bowler}
                      <span className="mt-0.5 block text-xs text-dim">
                        overs {s.start_over + 1}–{s.end_over + 1}
                      </span>
                    </td>
                    <td className={tdNumClass}>{s.overs}</td>
                    <td className="tnum px-3 py-2.5 text-right font-semibold text-ink">
                      {s.wickets}/{s.runs_conceded}
                    </td>
                    <td className={tdNumClass}>{rate(s.economy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <Provenance>
        A spell is a run of a bowler's own overs with no break - bowlers alternate ends, so
        consecutive overs in a spell are two apart. Match figures hide this: the same bowler can
        have an expensive opening burst and a decisive later one, and only the spells show it.
      </Provenance>
    </Panel>
  )
}
