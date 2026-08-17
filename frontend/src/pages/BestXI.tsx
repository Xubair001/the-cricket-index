import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { SelectedSide, SelectionPick, TeamSummary } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { PlayerName } from '../components/PlayerName'
import { useGender } from '../gender/useGender'
import { rate } from '../format'
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
 * Best XI / XV (§18).
 *
 * The page has to answer "why is this player in the side", not just list names —
 * §18's whole point is a selection a coach could defend. So every row carries
 * the slot it was picked for, the standard it was picked on and the form it is
 * in, and the caveats sit above the side rather than under it.
 *
 * The two caveats are not decoration. Handedness and bowling type do not exist
 * in any source, so "balanced" here means the roles are balanced, not that the
 * attack is balanced between seam and spin or that the openers are a left-right
 * pair. A selector who assumed otherwise would be misled, so the page says it
 * before showing the side.
 */

const COMPETITIONS = [
  { value: 'tests', label: 'Tests' },
  { value: 'odis', label: 'ODIs' },
  { value: 't20is', label: 'T20Is' },
  { value: 'psl', label: 'PSL' },
]

const SIZES = [
  { value: 11, label: 'XI' },
  { value: 15, label: 'XV' },
]

/** Conventional reading order for a team sheet, not the order picked. */
const SLOT_ORDER = ['batter', 'wicketkeeper', 'allrounder', 'bowler']

const SLOT_LABEL: Record<string, string> = {
  batter: 'Batter',
  wicketkeeper: 'Wicketkeeper',
  allrounder: 'All-rounder',
  bowler: 'Bowler',
  unknown: '—',
}

function orderForSheet(picks: SelectionPick[]): SelectionPick[] {
  return [...picks].sort((a, b) => {
    // Openers head the sheet, as they do a scorecard.
    if (a.opens !== b.opens) return a.opens ? -1 : 1
    const ai = SLOT_ORDER.indexOf(a.slot)
    const bi = SLOT_ORDER.indexOf(b.slot)
    if (ai !== bi) return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi)
    return b.selection_score - a.selection_score
  })
}

/** Form as a short, honest phrase rather than a raw percentage. */
function formNote(p: SelectionPick): { text: string; tone: string } {
  if (p.form_delta === null) return { text: 'form unknown', tone: 'text-dim' }
  const sign = p.form_delta > 0 ? '+' : ''
  const tone =
    p.form_delta > 15 ? 'text-positive-ink' : p.form_delta < -15 ? 'text-negative-ink' : 'text-muted'
  return { text: `${sign}${p.form_delta.toFixed(0)}% vs own baseline`, tone }
}

export function BestXI() {
  const { apiGender, slug } = useGender()
  const [params, setParams] = useSearchParams()

  const competition = params.get('competition') ?? 't20is'
  const size = Number(params.get('size') ?? 11)
  const teamId = params.get('team') ?? ''

  const [teams, setTeams] = useState<TeamSummary[]>([])
  const [side, setSide] = useState<SelectedSide | null>(null)
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

  // A PSL side is picked from franchises; an international side from nations.
  const teamType = competition === 'psl' ? 'franchise' : 'international'

  useEffect(() => {
    api
      .teams(apiGender, teamType, { limit: 500 })
      .then((res) => setTeams(res.items))
      .catch(() => setTeams([]))
  }, [apiGender, teamType])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .bestSide(apiGender, {
        competition,
        size,
        team_id: teamId ? Number(teamId) : undefined,
      })
      .then((res) => !cancelled && setSide(res))
      .catch((e) => !cancelled && (setError(String(e)), setSide(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [apiGender, competition, size, teamId])

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Discover"
        title={size === 15 ? 'Best XV' : 'Best XI'}
        blurb="A side picked to a role shape — not the top eleven on rating, which returns six openers and no keeper. Every place shows what it was picked on."
      />

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Competition</span>
          <select
            value={competition}
            onChange={(e) => update({ competition: e.target.value, team: '' })}
            className={fieldClass}
          >
            {COMPETITIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Squad</span>
          <select
            value={String(size)}
            onChange={(e) => update({ size: e.target.value })}
            className={fieldClass}
          >
            {SIZES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>
            {teamType === 'franchise' ? 'Franchise' : 'Nation'}
          </span>
          <select value={teamId} onChange={(e) => update({ team: e.target.value })} className={fieldClass}>
            <option value="">Anyone in this competition</option>
            {teams.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* §18's balance caveats, before the side rather than after it. */}
      {side && Object.keys(side.unavailable).length > 0 && (
        <Card className="border-warning/30 bg-warning-dim/30">
          <p className="text-sm text-warning-ink">What "balanced" does not cover here</p>
          <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
            {Object.entries(side.unavailable).map(([key, reason]) => (
              <li key={key}>
                <span className="text-ink">{key.replace(/_/g, ' ')}</span> — {reason}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-dim">
            The roles below are balanced. A left-right opening pair and a seam/spin split are not
            checked, because no source carries either.
          </p>
        </Card>
      )}

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner />}

      {side && !loading && (
        <>
          {side.picks.length === 0 ? (
            <EmptyState
              title="No side can be picked here"
              hint="Too few players clear the minimum number of matches in this scope."
            />
          ) : (
            <Panel
              title={side.team_name ? `${side.team_name} — best ${size === 15 ? 'XV' : 'XI'}` : `Best ${size === 15 ? 'XV' : 'XI'}`}
              blurb={
                <>
                  Picked from {side.scope} cricket. Shape:{' '}
                  {Object.entries(side.shape)
                    .map(([role, n]) => `${n} ${SLOT_LABEL[role]?.toLowerCase() ?? role}`)
                    .join(', ')}
                  , with the remaining places on merit.
                </>
              }
              bodyClassName=""
            >
              <ol className="divide-y divide-border-subtle">
                {orderForSheet(side.picks).map((p, i) => {
                  const form = formNote(p)
                  return (
                    <li key={p.player_identifier} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3">
                      <span className="tnum w-5 shrink-0 text-sm text-dim">{i + 1}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <PlayerName
                            name={p.player_name}
                            country={p.country}
                            countryCode={p.country_code}
                            to={`/${slug}/players/${p.player_identifier}`}
                            nameClassName="font-medium"
                          />
                          {p.is_wicketkeeper && (
                            <span
                              className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
                              title="Identified from stumpings — only a keeper can take one"
                            >
                              wk
                            </span>
                          )}
                          {p.opens && (
                            <span
                              className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
                              title="Regularly one of the two batters on the first ball of an innings"
                            >
                              opens
                            </span>
                          )}
                        </div>
                        <p className="mt-0.5 text-xs text-dim">{p.reason}</p>
                      </div>

                      <span
                        className="w-24 shrink-0 text-right text-xs text-muted"
                        title="Inferred from balls faced versus balls bowled — never a sourced fact"
                      >
                        {SLOT_LABEL[p.slot] ?? p.slot}
                      </span>
                      <span className={`w-40 shrink-0 text-right text-xs ${form.tone}`}>
                        {form.text}
                      </span>
                      <span
                        className="tnum w-12 shrink-0 text-right text-sm font-semibold text-ink"
                        title="Career standing 55%, Performance Index 30%, current form 15% — all within this scope"
                      >
                        {rate(p.selection_score)}
                      </span>
                    </li>
                  )
                })}
              </ol>

              {side.notes.length > 0 && (
                <div className="border-t border-border-subtle px-4 py-3">
                  {side.notes.map((n) => (
                    <p key={n} className="text-xs leading-relaxed text-warning-ink">
                      {n}
                    </p>
                  ))}
                </div>
              )}

              <Provenance>
                Each place is scored on career standing in this scope (55%), the Performance Index
                over the last 15 matches (30%) and current form against the player's own baseline
                (15%). Career dominates because a best side is not the same as the side in the best
                touch — but form still moves a player who is badly out of nick. Roles are
                <em> inferred</em>: batter, bowler and all-rounder from balls faced versus bowled,
                openers from who faces the first ball, and the keeper from stumpings, because only a
                keeper can take one.
              </Provenance>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}
