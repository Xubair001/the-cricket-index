import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AvailabilityWindow, PlayerAvailabilityRow } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { PlayerName } from '../components/PlayerName'
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
 * Player availability (§16).
 *
 * The page is built around an asymmetry that governs the whole feature:
 * **committed is sourced, available is not.** A player named in a squad is a
 * fact from ICC's feed. A player absent from every squad is not evidence of
 * anything, because squads are announced a few weeks out — so most fixtures in
 * a forward window have none published.
 *
 * That is why this page never shows a list called "available players". It shows
 * commitments, and it puts the coverage figure — how many fixtures in the window
 * actually have a squad — above the results rather than in a footnote. A scout
 * reading "142 free players" from an empty squad table would be badly misled.
 */

const ROLES = [
  { value: '', label: 'Any role' },
  { value: 'Batter', label: 'Batters' },
  { value: 'Bowler', label: 'Bowlers' },
  { value: 'All-Rounder', label: 'All-rounders' },
  { value: 'Wicket Keeper', label: 'Wicketkeepers' },
]

const HANDS = [
  { value: '', label: 'Either hand' },
  { value: 'RHB', label: 'Right-handed' },
  { value: 'LHB', label: 'Left-handed' },
]

/** Bowling styles the feed uses, split into the two families that matter. */
const SPIN = new Set(['OB', 'SLO', 'LB', 'LBG', 'OS', 'SLA', 'LWS'])

function bowlingFamily(style: string | null): string | null {
  if (!style) return null
  return SPIN.has(style) ? 'spin' : 'pace'
}

function todayISO(offsetDays = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  return d.toISOString().slice(0, 10)
}

export function Availability() {
  const { slug } = useGender()
  const [params, setParams] = useSearchParams()

  const from = params.get('from') || todayISO()
  const to = params.get('to') || todayISO(60)
  const role = params.get('role') ?? ''
  const hand = params.get('hand') ?? ''

  const [data, setData] = useState<AvailabilityWindow | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v)
      else merged.delete(k)
    }
    setParams(merged, { replace: true })
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .availability({
        date_from: from,
        date_to: to,
        role: role || undefined,
        batting_style: hand || undefined,
        limit: 100,
      })
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [from, to, role, hand])

  const coverage =
    data && data.fixtures_in_window
      ? data.fixtures_with_squads / data.fixtures_in_window
      : 0

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Fixtures"
        title="Player Availability"
        blurb="Who is committed to international cricket in a window — from announced squads, not inferred from recent appearances."
      />

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>From</span>
          <input type="date" value={from} onChange={(e) => update({ from: e.target.value })} className={fieldClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>To</span>
          <input type="date" value={to} onChange={(e) => update({ to: e.target.value })} className={fieldClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Role</span>
          <select value={role} onChange={(e) => update({ role: e.target.value })} className={fieldClass}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Batting hand</span>
          <select value={hand} onChange={(e) => update({ hand: e.target.value })} className={fieldClass}>
            {HANDS.map((h) => (
              <option key={h.value} value={h.value}>
                {h.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Coverage above the results, not under them. A reader who does not know
          that most squads are unannounced will read absence as freedom. */}
      {data && (
        <Card className="border-warning/30 bg-warning-dim/30">
          <p className="text-sm text-warning-ink">
            <span className="tnum">{data.fixtures_with_squads}</span> of{' '}
            <span className="tnum">{data.fixtures_in_window}</span> fixtures in this window have a
            squad announced
            {data.fixtures_in_window > 0 && (
              <span className="text-muted"> ({Math.round(coverage * 100)}%)</span>
            )}
            .
          </p>
          <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
            {Object.entries(data.caveats).map(([key, text]) => (
              <li key={key}>{text}</li>
            ))}
          </ul>
        </Card>
      )}

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner />}

      {data && !loading && (
        <Panel
          title="Committed players"
          blurb="Named in a squad for at least one fixture in this window. This is a commitment, not a rating."
          aside={<span className="tnum text-xs text-muted">{data.players.length} shown</span>}
          bodyClassName=""
        >
          {data.players.length === 0 ? (
            <div className="p-4">
              <EmptyState
                title="No squads announced for this window"
                hint="Squads are published a few weeks before a series. Try a nearer window, or widen the filters."
              />
            </div>
          ) : (
            <ul className="divide-y divide-border-subtle">
              {data.players.map((p) => (
                <PlayerRow key={p.player_identifier ?? p.player_name} p={p} slug={slug} />
              ))}
            </ul>
          )}

          <Provenance>
            Squads come from the ICC scorecard feed, which carries a full squad for a fixture that
            has not been played — including each player's role, batting hand and bowling style.
            Those three were listed as unavailable in this project until this feed was read for
            them. Names are linked to a player profile where they resolve confidently; about one in
            five do not, and those still appear because the commitment is real either way.
          </Provenance>
        </Panel>
      )}
    </div>
  )
}

function PlayerRow({ p, slug }: { p: PlayerAvailabilityRow; slug: string }) {
  const family = bowlingFamily(p.bowling_style)
  const next = p.commitments[0]
  return (
    <li className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3">
      <div className="min-w-0 flex-1">
        {p.player_identifier ? (
          <PlayerName
            name={p.player_name}
            to={`/${slug}/players/${p.player_identifier}`}
            nameClassName="font-medium"
          />
        ) : (
          <span className="font-medium text-muted" title="No confident match to a player in this dataset">
            {p.player_name}
          </span>
        )}
        {next && (
          <p className="mt-0.5 text-xs text-dim">
            {next.team_name} v {next.opponent}
            {next.start_date && <span className="tnum"> · from {next.start_date}</span>}
            {next.series_name && ` · ${next.series_name}`}
          </p>
        )}
      </div>

      <span className="w-28 shrink-0 text-right text-xs text-muted">{p.role ?? '—'}</span>
      <span className="w-16 shrink-0 text-right font-mono text-[11px] text-muted" title="Batting hand, from the squad feed">
        {p.batting_style ?? '—'}
      </span>
      <span
        className="w-20 shrink-0 text-right font-mono text-[11px] text-muted"
        title={p.bowling_style ? `Bowling style: ${p.bowling_style}` : 'No bowling style recorded'}
      >
        {p.bowling_style ?? '—'}
        {family && <span className="ml-1 text-dim">{family === 'spin' ? 'sp' : 'pc'}</span>}
      </span>
      <span className="tnum w-24 shrink-0 text-right text-sm text-ink">
        {p.commitments.length} {p.commitments.length === 1 ? 'fixture' : 'fixtures'}
      </span>
    </li>
  )
}
