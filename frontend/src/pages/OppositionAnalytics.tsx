import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useFilters } from '../state/useFilters'
import type { HeadToHead, TeamStrengthRow, TeamStrengthTable, TeamSummary } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Flag } from '../components/Flag'
import { useGender } from '../gender/useGender'
import {
  Card,
  EmptyState,
  PageHeader,
  Panel,
  Provenance,
  fieldClass,
  fieldLabelClass,
} from '../components/ui'

/**
 * Opposition analytics - how hard is each side to play against?
 *
 * This surfaces the model that already scales every performance elsewhere in
 * the product: the form boards, the Performance Index and the all-round
 * explorer all divide by it. Until now it was invisible, which meant a reader
 * could see an adjusted figure but not check the adjustment. §30 asks for the
 * opposite, so the model gets its own page.
 *
 * The framing is load-bearing and is stated on the page rather than buried in a
 * tooltip. This is a *difficulty* rating - how hard a side is to play against -
 * and it is neither an official rating nor a prediction of who wins a match. It
 * also merges batting and bowling strength into one number, because separating
 * them needs per-innings data this dataset does not hold.
 */

/** The era curve, drawn small. Difficulty clusters near 1.0 so the band is tight. */
function EraCurve({ eras }: { eras: TeamStrengthRow['eras'] }) {
  if (eras.length < 2) return <span className="text-dim">-</span>
  const width = 96
  const height = 22
  // 0.6–1.5 covers the fitted range with room to spare; values are clamped
  // rather than allowed to escape the box.
  const y = (d: number) => height - ((Math.max(0.6, Math.min(1.5, d)) - 0.6) / 0.9) * height
  const step = width / (eras.length - 1)
  const points = eras.map((e, i) => `${i * step},${y(e.difficulty).toFixed(1)}`).join(' ')
  const parY = y(1).toFixed(1)

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="overflow-visible"
      role="img"
      aria-label={eras.map((e) => `${e.era}: ${e.difficulty}`).join(', ')}
    >
      {/* Par. Every point is read against this line, so it is drawn first. */}
      <line x1="0" y1={parY} x2={width} y2={parY} stroke="currentColor" className="text-border-strong" strokeWidth="1" strokeDasharray="2 2" />
      <polyline points={points} fill="none" stroke="currentColor" className="text-analytic" strokeWidth="1.5" strokeLinejoin="round" />
      {/* Thin eras are drawn hollow: the line still connects them, because the
          side did play, but the point does not assert a figure it cannot carry. */}
      {eras.map((e, i) => (
        <circle
          key={e.era}
          cx={i * step}
          cy={y(e.difficulty)}
          r={i === eras.length - 1 ? 2.5 : 1.5}
          className={e.reliable ? 'fill-analytic' : 'fill-surface stroke-analytic'}
          strokeWidth="1"
        />
      ))}
    </svg>
  )
}

function Difficulty({ value }: { value: number | null }) {
  if (value === null) return <span className="tnum text-dim">-</span>
  const pct = Math.round((value - 1) * 100)
  return (
    <span className="tnum" title={`${value.toFixed(2)}x an average side to play against`}>
      {value.toFixed(2)}
      <span className={`ml-1 text-xs ${Math.abs(pct) < 3 ? 'text-dim' : 'text-muted'}`}>
        ({pct > 0 ? '+' : ''}
        {pct}%)
      </span>
    </span>
  )
}

export function OppositionAnalytics() {
  const { slug, apiGender } = useGender()
  const f = useFilters()
  const { set: update } = f
  const a = f.get('a')
  const b = f.get('b')

  const [table, setTable] = useState<TeamStrengthTable | null>(null)
  const [teams, setTeams] = useState<TeamSummary[]>([])
  const [h2h, setH2h] = useState<HeadToHead | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)


  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      api.teamStrength(apiGender),
      api.teams(apiGender, 'international', { limit: 500 }),
    ])
      .then(([strength, t]) => {
        if (cancelled) return
        setTable(strength)
        setTeams(t.items)
      })
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [apiGender])

  useEffect(() => {
    if (!a || !b || a === b) {
      setH2h(null)
      return
    }
    let cancelled = false
    api
      .headToHead(Number(a), Number(b))
      .then((res) => !cancelled && setH2h(res))
      .catch(() => !cancelled && setH2h(null))
    return () => {
      cancelled = true
    }
  }, [a, b])

  // Difficulty for the two chosen sides, so the head-to-head reads against it.
  const strengthOf = useMemo(() => {
    const map = new Map<number, TeamStrengthRow>()
    table?.items.forEach((r) => map.set(r.team_id, r))
    return map
  }, [table])

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Analytics"
        title="Opposition Analytics"
        blurb="How hard each side is to play against - the model that scales every adjusted figure elsewhere in this product."
      />

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner />}

      {/* The qualifications belong on the page, not in a tooltip: a ladder of
          teams invites two readings this model does not support. */}
      {table && (
        <Card className="border-analytic/25 bg-analytic-dim/25">
          <p className="text-sm text-ink">What this is, and what it is not</p>
          <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
            <li>
              It measures <span className="text-ink">difficulty to play against</span>, fitted from
              how sides share the cricket in their own matches - not who would win a given match.
            </li>
            <li>
              It merges batting and bowling strength into one figure. A side with a fearsome attack
              and a brittle top order reads the same as a balanced one of equal difficulty.
            </li>
            <li>
              It is <span className="text-ink">not an official rating</span>. It agrees with ICC's
              published team ratings at {table.validated_against_icc} - but that is a check on the
              model, never an input to it. For the official tables see{' '}
              <Link to={`/${slug}/icc-rankings`} className="text-analytic-ink hover:underline">
                ICC Rankings
              </Link>
              .
            </li>
          </ul>
        </Card>
      )}

      {table && (
        <Panel
          title="Difficulty ladder"
          blurb={`${table.total} sides with enough cricket to rate. 1.00 is an average opponent in an average match; the curve tracks each side across five-year eras.`}
        >
          <div className="scroll-x">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-border-subtle text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                  <th className="px-3 py-2.5">#</th>
                  <th className="px-3 py-2.5">Side</th>
                  <th className="px-3 py-2.5 text-right">All-time</th>
                  <th className="px-3 py-2.5 text-right">Now</th>
                  <th className="px-3 py-2.5">Era curve</th>
                  <th className="px-3 py-2.5 text-right">Matches</th>
                </tr>
              </thead>
              <tbody>
                {table.items.map((r, i) => (
                  <tr
                    key={r.team_id}
                    className="border-b border-border-subtle last:border-0 hover:bg-elevated"
                  >
                    <td className="tnum px-3 py-2.5 text-dim">{i + 1}</td>
                    <td className="px-3 py-2.5">
                      <Link
                        to={`/${slug}/teams/${r.team_id}`}
                        className="inline-flex items-center gap-2 font-medium text-ink hover:text-analytic-ink"
                      >
                        <Flag code={r.country_code} name={r.name} />
                        {r.name}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <Difficulty value={r.difficulty} />
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {r.current_difficulty === null ? (
                        <span
                          className="text-dim"
                          title="Too few matches in the most recent era to state a current figure"
                        >
                          -
                        </span>
                      ) : (
                        <Difficulty value={r.current_difficulty} />
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <EraCurve eras={r.eras} />
                    </td>
                    <td className="tnum px-3 py-2.5 text-right text-muted">
                      {r.matches.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Provenance>
            Fitted with a Bradley-Terry model so that difficulty is transitive - beating a side that
            beats strong sides counts, beating Malta does not. Each era is referenced against a
            stable core of sides present across eras, because the 2019 expansion of T20I status to
            every ICC member would otherwise make every established side look harder in the 2020s
            simply by weakening the average opponent. A curve begins at a side's first era of
            international cricket, and an era with fewer than 15 matches is drawn hollow; where the
            most recent era is that thin, no current figure is stated at all.
          </Provenance>
        </Panel>
      )}

      {table && (
        <Panel
          title="Head to head"
          blurb="A record between two sides, read beside how hard each is to play against."
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {(['a', 'b'] as const).map((side) => (
              <label key={side} className="flex flex-col gap-1">
                <span className={fieldLabelClass}>{side === 'a' ? 'Side A' : 'Side B'}</span>
                <select
                  value={side === 'a' ? a : b}
                  onChange={(e) => update({ [side]: e.target.value })}
                  className={fieldClass}
                >
                  <option value="">Choose a side…</option>
                  {teams
                    .filter((t) => String(t.team_id) !== (side === 'a' ? b : a))
                    .map((t) => (
                      <option key={t.team_id} value={t.team_id}>
                        {t.name}
                      </option>
                    ))}
                </select>
              </label>
            ))}
          </div>

          {!a || !b ? (
            <div className="mt-4">
              <EmptyState title="Pick two sides" hint="Their record, and how each rates as opposition." />
            </div>
          ) : h2h ? (
            <div className="mt-5">
              <div className="flex items-baseline justify-between gap-4 text-sm">
                <span className="font-medium text-ink">{h2h.team_a.name}</span>
                <span className="tnum text-xs text-muted">
                  {h2h.matches} matches
                  {h2h.ties_or_no_result > 0 && ` · ${h2h.ties_or_no_result} tied/NR`}
                </span>
                <span className="font-medium text-ink">{h2h.team_b.name}</span>
              </div>

              {/* A proportional bar with a 2px surface gap, so the boundary
                  reads even where the two segments meet. */}
              <div className="mt-2 flex h-2.5 w-full overflow-hidden rounded-full bg-elevated">
                <div
                  className="rounded-l-full bg-analytic"
                  style={{ width: `${share(h2h.team_a_wins, h2h)}%` }}
                  title={`${h2h.team_a.name}: ${h2h.team_a_wins} wins`}
                />
                <div className="w-0.5 shrink-0 bg-surface" />
                <div
                  className="rounded-r-full bg-muted"
                  style={{ width: `calc(${share(h2h.team_b_wins, h2h)}% - 2px)` }}
                  title={`${h2h.team_b.name}: ${h2h.team_b_wins} wins`}
                />
              </div>
              <div className="tnum mt-1 flex justify-between text-sm">
                <span className="font-semibold text-ink">{h2h.team_a_wins}</span>
                <span className="font-semibold text-ink">{h2h.team_b_wins}</span>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
                {[h2h.team_a, h2h.team_b].map((t) => {
                  const s = strengthOf.get(t.team_id)
                  return (
                    <div key={t.team_id}>
                      <p className="text-xs text-muted">Difficulty to play against</p>
                      <p className="font-semibold text-ink">
                        <Difficulty value={s?.difficulty ?? null} />
                      </p>
                    </div>
                  )
                })}
              </div>

              <Provenance>
                The record counts decided matches only. Difficulty is fitted across all of a side's
                cricket, not just these fixtures, so a lopsided head-to-head between two sides of
                similar difficulty usually means a small sample rather than a mismatch.
              </Provenance>
            </div>
          ) : (
            <p className="mt-4 text-sm text-muted">
              These two sides have not met in this dataset.
            </p>
          )}
        </Panel>
      )}
    </div>
  )
}

function share(wins: number, h: HeadToHead): number {
  const decided = h.team_a_wins + h.team_b_wins
  return decided ? (wins / decided) * 100 : 50
}
