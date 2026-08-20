import { useState } from 'react'
import type { FormState, FormVerdict } from '../api/types'
import { change, score } from '../format'

/**
 * A form verdict with its workings attached.
 *
 * Rule 5 says a rating is incomplete without its reasoning, so the label is
 * never shown alone: the delta, both means, the sample sizes behind them and a
 * confidence figure are all on the card, and the full decomposition is one
 * click away. The confidence bar turns amber below the point where the verdict
 * rests on enough cricket to be trusted - a classification drawn from four
 * innings must not look like one drawn from forty.
 */

const TONE: Record<FormState, { fg: string; bg: string; ring: string }> = {
  in_form: { fg: 'text-positive-ink', bg: 'bg-positive-dim', ring: 'ring-positive/40' },
  improving: { fg: 'text-positive-ink', bg: 'bg-positive-dim', ring: 'ring-positive/30' },
  stable: { fg: 'text-analytic-ink', bg: 'bg-analytic-dim', ring: 'ring-analytic/30' },
  declining: { fg: 'text-warning-ink', bg: 'bg-warning-dim', ring: 'ring-warning/30' },
  out_of_form: { fg: 'text-negative-ink', bg: 'bg-negative-dim', ring: 'ring-negative/40' },
  insufficient_data: { fg: 'text-muted', bg: 'bg-elevated', ring: 'ring-border-default' },
}

const TREND_GLYPH: Record<FormVerdict['trend'], string> = {
  rising: '↗',
  flat: '→',
  falling: '↘',
  unknown: '·',
}

// Below this, the verdict is reported but visibly qualified rather than
// presented with the same weight as a well-evidenced one.
const LOW_CONFIDENCE = 0.5

function Sparkline({ verdict }: { verdict: FormVerdict }) {
  const points = [...verdict.timeline].reverse() // oldest first, so it reads left to right
  if (points.length < 2) return null

  const baseline = verdict.baseline_mean ?? 0
  const values = points.map((p) => p.impact_normalized)
  const peak = Math.max(...values, baseline, 1)
  const width = 100
  const height = 34
  const gap = 2
  const barWidth = Math.max(1.5, width / points.length - gap)

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-9 w-full"
      preserveAspectRatio="none"
      role="img"
      aria-label={`Impact across the ${verdict.recent_window}, oldest to newest`}
    >
      {/* The baseline is the thing every bar is being judged against, so it is
          drawn rather than left implicit.

          `non-scaling-stroke` is load-bearing: the SVG is stretched to the
          card's width with preserveAspectRatio="none", which squashes a 0.5
          unit stroke to well under a device pixel and made the line the label
          promises invisible at every width the card is ever rendered at. */}
      <line
        x1="0"
        x2={width}
        y1={height - (baseline / peak) * height}
        y2={height - (baseline / peak) * height}
        stroke="var(--color-ink)"
        strokeOpacity="0.5"
        strokeWidth="1"
        strokeDasharray="4 3"
        vectorEffect="non-scaling-stroke"
      />
      {points.map((p, i) => {
        const value = Math.max(0, p.impact_normalized)
        const barHeight = (value / peak) * height
        const above = p.impact_normalized >= baseline
        return (
          <rect
            key={p.match_id}
            x={i * (barWidth + gap)}
            y={height - barHeight}
            width={barWidth}
            height={Math.max(barHeight, 0.6)}
            // Below-baseline reads red, the same above/below language the par
            // meters use everywhere else. It was a neutral grey, which made a
            // poor match look like a missing one.
            fill={above ? 'var(--color-positive)' : 'var(--color-negative)'}
          >
            <title>
              {`${p.impact_normalized.toFixed(2)} par units - ${above ? 'at or above' : 'below'} the baseline`}
            </title>
          </rect>
        )
      })}
    </svg>
  )
}

export default function FormVerdictCard({
  verdict,
  scopeLabel,
}: {
  verdict: FormVerdict
  scopeLabel?: string
}) {
  const [showWorkings, setShowWorkings] = useState(false)
  const tone = TONE[verdict.state] ?? TONE.insufficient_data
  const lowConfidence = verdict.confidence < LOW_CONFIDENCE
  // The headline is the bounded 0-100 score. `delta_percent` is the raw ratio
  // against this player's own baseline and has no ceiling - it reached +306% in
  // this dataset - so it is shown as the supporting move, worded by the API.
  const delta = verdict.delta_percent
  const move = verdict.delta_display ?? change(delta)

  return (
    <section className="rounded-xl border border-border-subtle bg-surface shadow-card">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle px-5 py-4">
        <div>
          <h2 className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
            Current form
          </h2>
          <div className="mt-2 flex items-center gap-3">
            <span
              className={`rounded px-2.5 py-1 text-sm font-semibold ring-1 ${tone.fg} ${tone.bg} ${tone.ring}`}
            >
              {verdict.label}
            </span>
            {verdict.form_score !== null && (
              <span
                className={`tnum text-2xl font-semibold ${tone.fg}`}
                title="Form score out of 100: where this move sits among every player in this scope"
              >
                {score(verdict.form_score)}
                <span className="ml-0.5 text-sm font-normal text-muted">/100</span>
              </span>
            )}
            {delta !== null && (
              <span className="text-sm text-muted" title="Change against this player's own baseline">
                {move}
              </span>
            )}
            <span className="text-lg text-muted" title={`Trend within the ${verdict.recent_window}`}>
              {TREND_GLYPH[verdict.trend]}
            </span>
          </div>
        </div>

        <div className="min-w-[140px]">
          <div className="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
            <span>Confidence</span>
            <span className="tnum">{Math.round(verdict.confidence * 100)}%</span>
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-elevated">
            <div
              className={`h-full rounded-full ${lowConfidence ? 'bg-warning' : 'bg-positive'}`}
              style={{ width: `${Math.max(verdict.confidence * 100, 2)}%` }}
            />
          </div>
          {lowConfidence && (
            <p className="mt-1.5 text-[11px] leading-snug text-warning-ink">
              Thin sample - treat as indicative.
            </p>
          )}
        </div>
      </header>

      <div className="px-5 py-4">
        <p className="max-w-prose text-sm leading-relaxed text-ink">{verdict.explanation}</p>
        {scopeLabel && (
          <p className="mt-1.5 text-xs text-dim">
            Scope: {scopeLabel}. Internationals and franchise cricket are never blended into one
            figure.
          </p>
        )}

        {verdict.timeline.length > 1 && (
          <div className="mt-4">
            <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
              <span>Impact per match - oldest to newest</span>
              <span>Dashed line = baseline</span>
            </div>
            <div className="mt-2">
              <Sparkline verdict={verdict} />
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={() => setShowWorkings((v) => !v)}
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface px-3 py-1.5 text-xs font-medium text-ink shadow-card transition-colors hover:bg-elevated"
          aria-expanded={showWorkings}
        >
          {showWorkings ? 'Hide workings' : 'How is this calculated?'}
        </button>

        {showWorkings && (
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-border-subtle pt-3 text-sm sm:grid-cols-3">
            {[
              ['Recent window', verdict.recent_window],
              ['Recent mean', verdict.recent_mean?.toFixed(2) ?? '-'],
              ['Recent matches', String(verdict.recent_matches)],
              ['Baseline window', verdict.baseline_window],
              ['Baseline mean', verdict.baseline_mean?.toFixed(2) ?? '-'],
              ['Baseline matches', String(verdict.baseline_matches)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">
                  {label}
                </dt>
                <dd className="tnum mt-0.5 text-ink">{value}</dd>
              </div>
            ))}
            <p className="col-span-full mt-1 max-w-prose text-xs leading-relaxed text-muted">
              Means are per match, expressed as a multiple of a par performance in the same
              competition - 1.00 is exactly par. Each performance is valued in runs-equivalent
              (runs scored, plus runs above the going scoring rate, plus wickets valued at what a
              wicket costs and runs saved against par economy), then divided by what a typical
              appearance in that competition is worth so formats stay comparable. The recent mean
              is shrunk toward the baseline in proportion to how few matches it rests on.
            </p>
          </dl>
        )}
      </div>
    </section>
  )
}
