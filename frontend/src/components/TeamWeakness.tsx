import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { TeamWeakness as Weakness } from '../api/types'
import { useScope } from '../scope/scope'
import { SkeletonRows } from './LoadingSpinner'
import { rate } from '../format'

/**
 * Team weakness analysis (Section 19).
 *
 * The scope calls this "the differentiator" on a team page and gives the exact
 * shape of the answer: "death bowling performance has declined over the last 10
 * matches". Three properties of that sentence drive the whole component.
 *
 * It names a PHASE, not a total - "this side is weak" is not actionable. It
 * compares the side with ITSELF, because a side can be the best death-bowling
 * attack in the world and still be declining, and that is worth catching early.
 * And it is a window of the side's own last ten matches, not a date range.
 *
 * The empty state is deliberately a result rather than a blank. A page that
 * always finds three weaknesses is a horoscope, so when nothing has moved the
 * component says exactly that.
 */

function VerdictMark({ verdict }: { verdict: string }) {
  // Not colour alone. A declining phase gets the negative ink AND a glyph, for
  // the same reason the form boards do not lean on hue: the amber/red pair in
  // this palette cannot be separated under deuteranopia.
  const map: Record<string, { glyph: string; tone: string; label: string }> = {
    declined: { glyph: '▼', tone: 'text-negative-ink', label: 'Declined' },
    improved: { glyph: '▲', tone: 'text-positive-ink', label: 'Improved' },
    steady: { glyph: '·', tone: 'text-dim', label: 'Steady' },
    unmeasured: { glyph: '–', tone: 'text-dim', label: 'Not enough cricket' },
  }
  const v = map[verdict] ?? map.unmeasured
  return (
    <span className={`${v.tone} w-4 shrink-0 text-center`} title={v.label}>
      {v.glyph}
      <span className="sr-only">{v.label}</span>
    </span>
  )
}

export function TeamWeaknessPanel({ teamId }: { teamId: number }) {
  const { competitions } = useScope()
  // Phases are defined per competition, so this needs one chosen. Default to
  // the richest competition that HAS phases rather than to the first in the
  // list, or a Test-playing side opens on a panel that can say nothing.
  const withPhases = competitions.filter((c) => c.key !== 'tests')
  const [competition, setCompetition] = useState('')
  const [data, setData] = useState<Weakness | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!competition && withPhases.length) setCompetition(withPhases[0].key)
  }, [withPhases, competition])

  useEffect(() => {
    if (!competition) return
    let cancelled = false
    setLoading(true)
    api
      .teamWeakness(teamId, competition)
      .then((r) => !cancelled && setData(r))
      .catch(() => !cancelled && setData(null))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [teamId, competition])

  const measured = (data?.facets ?? []).filter((f) => f.verdict !== 'unmeasured')

  return (
    <section className="overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-card">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold tracking-tight text-ink">What has got worse</h2>
          <p className="mt-1 max-w-prose text-xs leading-relaxed text-muted">
            Each phase over the side's last {data?.recent_matches ?? 10} matches against their own
            previous {data?.baseline_matches ?? 40}. A weakness here is a decline against
            themselves, not a position in a table.
          </p>
        </div>
        <select
          value={competition}
          onChange={(e) => setCompetition(e.target.value)}
          className="rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink"
        >
          {withPhases.map((c) => (
            <option key={c.key} value={c.key}>
              {c.display_name}
            </option>
          ))}
        </select>
      </header>

      {loading ? (
        <SkeletonRows rows={6} className="p-4" />
      ) : !data || measured.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted">
          {data?.notes?.[0] ??
            'Not enough cricket in this competition to compare one window against another.'}
        </p>
      ) : (
        <>
          <ul className="divide-y divide-border-subtle">
            {measured.map((f) => (
              <li key={f.key} className="flex items-baseline gap-3 px-4 py-2.5">
                <VerdictMark verdict={f.verdict} />
                <span className="min-w-0 flex-1 text-sm text-ink">{f.label}</span>
                {/* Runs an over, recent then baseline, so the reader can check
                    the percentage rather than take it on trust. */}
                <span className="tnum w-28 shrink-0 text-right font-mono text-[11px] text-muted">
                  {rate(f.recent)} <span className="text-dim">from</span> {rate(f.baseline)}
                </span>
                <span
                  className={`tnum w-16 shrink-0 text-right text-sm font-semibold ${
                    f.verdict === 'declined'
                      ? 'text-negative-ink'
                      : f.verdict === 'improved'
                        ? 'text-positive-ink'
                        : 'text-muted'
                  }`}
                >
                  {f.delta_percent === null
                    ? '-'
                    : `${f.delta_percent > 0 ? '+' : ''}${f.delta_percent.toFixed(0)}%`}
                </span>
                <span
                  className="tnum w-16 shrink-0 text-right font-mono text-[11px] text-dim"
                  title="Against the core sides of this competition over the same window"
                >
                  {f.versus_peers_percent === null
                    ? '-'
                    : `${f.versus_peers_percent > 0 ? '+' : ''}${f.versus_peers_percent.toFixed(0)}%`}
                </span>
              </li>
            ))}
          </ul>
          <footer className="border-t border-border-subtle px-4 py-2">
            <p className="font-mono text-[9px] uppercase tracking-[0.1em] text-dim">
              Phase · runs per over now from then · vs own past · vs core sides
            </p>
          </footer>
        </>
      )}

      {data && (data.notes.length > 0 || Object.keys(data.unavailable).length > 0) && (
        <div className="space-y-2 border-t border-border-subtle bg-elevated px-4 py-3">
          {data.notes.map((n, i) => (
            <p key={i} className="text-xs leading-relaxed text-muted">
              {n}
            </p>
          ))}
          {Object.entries(data.unavailable).map(([k, v]) => (
            <p key={k} className="text-xs leading-relaxed text-dim">
              <span className="font-medium">{k.replace(/_/g, ' ')}</span> - {v}
            </p>
          ))}
        </div>
      )}
    </section>
  )
}
