import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DashboardStats, FormLeaderRow } from '../api/types'
import { useGender } from '../gender/useGender'
import { ParMeter } from '../components/ParMeter'
import { SkeletonRows } from '../components/LoadingSpinner'
import { Provenance, Uncertain } from '../components/ui'

/**
 * The landing page.
 *
 * Its job is to say "cricket intelligence, not cricket scores" within one
 * screen, so it opens with questions a person can act on rather than a wall of
 * totals. The counts are present but small and below the fold of attention —
 * they establish the dataset's size, they are not the product.
 *
 * The hero is the par scale rather than a headline figure. Every board on this
 * page is ordered on par units, and a reader who has not been told what 1.00
 * means cannot read any of them; putting the unit first turns the boards from
 * a list of names into something checkable. It is also the one device that is
 * particular to this product — par here is fitted against the strength of the
 * opposition, not against a raw average.
 *
 * Every section is a computed entry point into the product. Deliberately not a
 * news feed (§6).
 */

const ACTIONS = [
  { label: 'Find a Player', to: 'players', hint: 'Search and filter the full register' },
  { label: 'Compare Players', to: 'compare', hint: 'Two careers side by side' },
  { label: 'Explore Rankings', to: 'rankings', hint: 'Computed from ball-level aggregates' },
  { label: 'ICC Rankings', to: 'icc-rankings', hint: 'Official published ratings' },
]

function TrendGlyph({ trend }: { trend: FormLeaderRow['trend'] }) {
  const glyph = { rising: '↗', flat: '→', falling: '↘', unknown: '·' }[trend]
  const tone =
    trend === 'rising' ? 'text-positive-ink' : trend === 'falling' ? 'text-negative-ink' : 'text-dim'
  const description = {
    rising: 'Improving within the recent window',
    flat: 'Level within the recent window',
    falling: 'Declining within the recent window',
    unknown: 'Not enough cricket to read a trend',
  }[trend]
  return (
    <span className={`${tone} w-3 shrink-0 text-center text-sm`} title={description}>
      {glyph}
      <span className="sr-only">{description}</span>
    </span>
  )
}

/**
 * The par scale — the legend for every board on this page.
 *
 * Drawn rather than described, and drawn with the same track the rows use, so
 * the meters below are already familiar by the time they appear.
 */
function ParScale() {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-card sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="u-eyebrow">The unit on this page</p>
        <p className="text-xs text-muted">
          Every board below is ordered on par units gained, not on the percentage.
        </p>
      </div>

      {/* Same track and same datum position as the row meters — a third of the
          way in, because the scale runs to 3.00. Drawing the legend on a
          different scale to the thing it explains would be worse than not
          drawing it. The 2px gaps either side of the datum are what keep the
          line readable where two fills meet it. */}
      <div className="relative mt-4">
        <div className="par-track h-2.5" style={{ ['--par-pos' as string]: 1 / 3 }}>
          <span
            className="par-fill"
            style={{ left: '6%', width: '26.1%', background: 'var(--color-negative)' }}
          />
          <span
            className="par-fill"
            style={{ left: '34.5%', width: '55%', background: 'var(--color-positive)' }}
          />
        </div>
        <div className="relative mt-2 h-8 font-mono text-[10px]">
          <span className="absolute left-0 text-negative-ink">▼ below par</span>
          <span
            className="tnum absolute -translate-x-1/2 text-center text-ink"
            style={{ left: '33.33%' }}
          >
            1.00
            <span className="block text-dim">an average appearance</span>
          </span>
          <span className="absolute right-0 text-positive-ink">above par ▲</span>
        </div>
      </div>

      <p className="mt-3 max-w-3xl text-xs leading-relaxed text-muted">
        A par unit is what one average appearance is worth, after every performance has been scaled
        by the strength of the side it came against. A player at{' '}
        <span className="tnum font-mono text-negative-ink">0.70x</span> is producing less than an
        average appearance even if their form is improving sharply — which is why the absolute
        figure sits beside the change on every row.
      </p>
    </div>
  )
}

function FormBoard({
  title,
  blurb,
  rows,
  loading,
  slug,
  tone,
}: {
  title: string
  blurb: string
  rows: FormLeaderRow[]
  loading: boolean
  slug: string
  tone: 'positive' | 'negative'
}) {
  return (
    <section className="flex flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-card">
      <header className="border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted">{blurb}</p>
      </header>

      {loading ? (
        <SkeletonRows rows={6} className="p-4" />
      ) : rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted">
          No players meet the evidence threshold in this scope.
        </p>
      ) : (
        <ul className="flex-1 divide-y divide-border-subtle">
          {rows.map((r) => {
            // Confidence below 0.6 is the product saying "thin sample". It is
            // rendered as a dotted rule rather than an amber figure: amber and
            // the red of a below-par delta cannot be separated (ΔE ~12 for
            // normal vision), and here they would sit in adjacent columns.
            const thin = r.confidence < 0.6
            const deltaText =
              r.delta_percent !== null
                ? `${r.delta_percent > 0 ? '+' : ''}${r.delta_percent.toFixed(0)}%`
                : '—'
            const confidenceNote = `Confidence ${Math.round(r.confidence * 100)}% — from ${
              r.recent_matches
            } recent and ${r.baseline_matches} earlier matches`

            return (
              <li key={r.player_identifier}>
                <Link
                  to={`/${slug}/players/${r.player_identifier}`}
                  className="flex items-center gap-2.5 px-4 py-2.5 transition-colors hover:bg-elevated"
                  title={r.explanation}
                >
                  <TrendGlyph trend={r.trend} />
                  <span className="min-w-0 flex-1 truncate text-sm text-ink">{r.player_name}</span>

                  {/* The absolute standard, drawn against the datum. A player
                      can post a huge percentage and still be below par, having
                      improved from very poor — the board is ordered on par
                      units gained, so this is what explains the order. */}
                  <ParMeter value={r.recent_mean} className="w-14 shrink-0" />
                  <span
                    className={`tnum w-11 shrink-0 text-right font-mono text-[11px] ${
                      (r.recent_mean ?? 0) >= 1 ? 'text-muted' : 'text-negative-ink'
                    }`}
                  >
                    {r.recent_mean !== null ? `${r.recent_mean.toFixed(2)}x` : '—'}
                  </span>

                  <span
                    className={`tnum w-14 shrink-0 text-right text-sm font-semibold ${
                      tone === 'positive' ? 'text-positive-ink' : 'text-negative-ink'
                    }`}
                  >
                    {thin ? <Uncertain reason={confidenceNote}>{deltaText}</Uncertain> : deltaText}
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}

      <footer className="border-t border-border-subtle px-4 py-2">
        <p className="font-mono text-[9px] uppercase tracking-[0.1em] text-dim">
          Trend · Player · Par · Change
        </p>
      </footer>
    </section>
  )
}

export function Home() {
  const { slug, apiGender } = useGender()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [inForm, setInForm] = useState<FormLeaderRow[]>([])
  const [rising, setRising] = useState<FormLeaderRow[]>([])
  const [losing, setLosing] = useState<FormLeaderRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      api.dashboard(apiGender),
      api.formLeaderboard(apiGender, { state: 'in_form', limit: 6 }),
      api.formLeaderboard(apiGender, { trend: 'rising', limit: 6 }),
      api.formLeaderboard(apiGender, { state: 'out_of_form', limit: 6 }),
    ])
      .then(([d, f, r, l]) => {
        if (cancelled) return
        setStats(d)
        setInForm(f.items)
        setRising(r.items)
        setLosing(l.items)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [apiGender])

  const kpis: [string, number | undefined][] = [
    ['Players', stats?.total_players],
    ['Matches', stats?.total_matches],
    ['Teams', stats?.total_teams],
    ['Competitions', stats?.by_competition.length],
    ['Seasons', stats?.matches_by_season.length],
  ]

  return (
    <div className="space-y-8">
      <section>
        <p className="u-eyebrow">
          {slug === 'men' ? "Men's" : "Women's"} cricket · derived from ball-by-ball
        </p>
        <h1 className="u-display mt-3 max-w-3xl text-display text-ink">
          Understand cricket beyond the scorecard.
        </h1>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted">
          Discover players, analyse performance, compare talent and track form — with the workings
          shown for every figure.
        </p>

        <div className="mt-6 flex flex-wrap gap-2">
          {ACTIONS.map((a) => (
            <Link
              key={a.label}
              to={`/${slug}/${a.to}`}
              title={a.hint}
              className="rounded-lg border border-border-default bg-surface px-4 py-2 text-sm font-medium text-ink shadow-card transition-colors hover:border-border-strong hover:bg-elevated"
            >
              {a.label}
            </Link>
          ))}
          <span
            title="Needs squad lists per fixture, and the fixture feed carries no franchise cricket"
            className="inline-flex cursor-not-allowed items-center gap-2 rounded-lg border border-dashed border-border-default px-4 py-2 text-sm text-dim"
          >
            Find Available Players
            <span className="rounded bg-warning-dim px-1 py-px font-mono text-[9px] uppercase tracking-[0.08em] text-warning-ink">
              soon
            </span>
          </span>
        </div>
      </section>

      <ParScale />

      <div className="grid gap-5 lg:grid-cols-3">
        <FormBoard
          title="Players in Form"
          blurb="Furthest above their own recent baseline, weighted by how much cricket the verdict rests on."
          rows={inForm}
          loading={loading}
          slug={slug}
          tone="positive"
        />
        <FormBoard
          title="Rising"
          blurb="Improving within their current run — the trend is upward, not just the level."
          rows={rising}
          loading={loading}
          slug={slug}
          tone="positive"
        />
        <FormBoard
          title="Losing Form"
          blurb="Furthest below their own baseline. A drop here is relative to the player, not to their peers."
          rows={losing}
          loading={loading}
          slug={slug}
          tone="negative"
        />
      </div>

      {/* The dataset's size. Present because it sets the scale of everything
          above, small because it is not the product. */}
      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border-subtle bg-border-subtle shadow-card sm:grid-cols-5">
        {kpis.map(([label, value]) => (
          <div key={label} className="bg-surface px-4 py-3">
            <div className="u-display tnum text-lg text-ink">
              {value === undefined ? '—' : value.toLocaleString()}
            </div>
            <div className="u-eyebrow mt-0.5">{label}</div>
          </div>
        ))}
      </section>

      <Provenance>
        Form compares a player against their own preceding 12 months, scoped to international
        cricket — never blended with franchise cricket. The percentage is the change against that
        baseline; the meter beside it is the absolute standard against par. A dotted rule under a
        change means confidence below 60%, from a thin sample. Every performance is weighted by the
        strength of the side it came against, fitted from what every team concedes across the whole
        fixture list — so runs against a weak attack count for less. Boards are ordered on par units
        gained rather than on the percentage, because a player improving from poor to below-average
        can post a bigger percentage than one playing the best cricket in the world.
      </Provenance>
    </div>
  )
}
