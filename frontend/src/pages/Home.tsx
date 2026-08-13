import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DashboardStats, FormLeaderRow } from '../api/types'
import { useGender } from '../gender/useGender'

/**
 * The landing page.
 *
 * Its job is to say "cricket intelligence, not cricket scores" within one
 * screen, so it opens with questions a person can act on rather than a wall of
 * totals. The counts are present but small and below the fold of attention —
 * they establish the dataset's size, they are not the product.
 *
 * Every section here is a computed entry point into the product. Deliberately
 * not a news feed (§6).
 */

const ACTIONS = [
  { label: 'Find a Player', to: 'players', hint: 'Search and filter the full register' },
  { label: 'Compare Players', to: 'compare', hint: 'Two careers side by side' },
  { label: 'Explore Rankings', to: 'rankings', hint: 'Computed from ball-level aggregates' },
  { label: 'ICC Rankings', to: 'icc-rankings', hint: 'Official published ratings' },
]

function TrendGlyph({ trend }: { trend: FormLeaderRow['trend'] }) {
  const glyph = { rising: '↗', flat: '→', falling: '↘', unknown: '·' }[trend]
  const tone = trend === 'rising' ? 'text-positive' : trend === 'falling' ? 'text-warning' : 'text-dim'
  return <span className={`${tone} text-sm`} title={`Trend within the recent window`}>{glyph}</span>
}

function FormList({
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
    <section className="rounded-lg border border-border-default bg-surface">
      <header className="border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        <p className="mt-0.5 text-xs leading-relaxed text-muted">{blurb}</p>
      </header>
      {loading ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-6 animate-pulse rounded bg-elevated" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="p-4 text-sm text-muted">No players meet the evidence threshold in this scope.</p>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {rows.map((r) => (
            <li key={r.player_identifier}>
              <Link
                to={`/${slug}/players/${r.player_identifier}`}
                className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-elevated"
                title={r.explanation}
              >
                <span className="min-w-0 flex-1 truncate text-sm text-ink">{r.player_name}</span>
                <TrendGlyph trend={r.trend} />
                <span
                  className={`tnum w-16 text-right text-sm font-semibold ${
                    tone === 'positive' ? 'text-positive' : 'text-negative'
                  }`}
                >
                  {r.delta_percent !== null
                    ? `${r.delta_percent > 0 ? '+' : ''}${r.delta_percent.toFixed(0)}%`
                    : '—'}
                </span>
                {/* Confidence travels with every verdict, so a thin sample can
                    never look like a well-evidenced one. */}
                <span
                  className={`tnum w-9 text-right font-mono text-[10px] ${
                    r.confidence < 0.6 ? 'text-warning' : 'text-dim'
                  }`}
                  title={`Confidence ${Math.round(r.confidence * 100)}% — from ${r.recent_matches} recent and ${r.baseline_matches} earlier matches`}
                >
                  {Math.round(r.confidence * 100)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
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
    <div className="space-y-10">
      <section>
        <h1 className="max-w-2xl text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          Understand cricket beyond the scorecard.
        </h1>
        <p className="mt-3 max-w-2xl text-base leading-relaxed text-muted">
          Discover players, analyse performance, compare talent and track form — with the workings
          shown for every figure.
        </p>

        <div className="mt-6 flex flex-wrap gap-2">
          {ACTIONS.map((a) => (
            <Link
              key={a.label}
              to={`/${slug}/${a.to}`}
              title={a.hint}
              className="rounded-md border border-border-default bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:border-analytic hover:bg-elevated"
            >
              {a.label}
            </Link>
          ))}
          <span
            title="Needs squad lists per fixture, and the fixture feed carries no franchise cricket"
            className="cursor-not-allowed rounded-md border border-border-subtle px-4 py-2 text-sm text-dim"
          >
            Find Available Players
            <span className="ml-2 font-mono text-[9px] uppercase tracking-[0.1em] text-warning">
              soon
            </span>
          </span>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border-default bg-border-default sm:grid-cols-5">
        {kpis.map(([label, value]) => (
          <div key={label} className="bg-surface px-4 py-3">
            <div className="tnum text-xl font-semibold text-ink">
              {value === undefined ? '—' : value.toLocaleString()}
            </div>
            <div className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
              {label}
            </div>
          </div>
        ))}
      </section>

      <div className="grid gap-5 lg:grid-cols-3">
        <FormList
          title="Players in Form"
          blurb="Furthest above their own recent baseline, weighted by how much cricket the verdict rests on."
          rows={inForm}
          loading={loading}
          slug={slug}
          tone="positive"
        />
        <FormList
          title="Rising"
          blurb="Improving within their current run — the trend is upward, not just the level."
          rows={rising}
          loading={loading}
          slug={slug}
          tone="positive"
        />
        <FormList
          title="Losing Form"
          blurb="Furthest below their own baseline. A drop here is relative to the player, not to their peers."
          rows={losing}
          loading={loading}
          slug={slug}
          tone="negative"
        />
      </div>

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        Form compares a player against their own preceding 12 months, scoped to international
        cricket — never blended with franchise cricket. The number beside each name is the change
        against that baseline; the small figure after it is confidence, and it turns amber when the
        verdict rests on a thin sample. Opposition strength is not yet adjusted for, so players
        facing weaker attacks rise faster than their cricket warrants.
      </p>
    </div>
  )
}
