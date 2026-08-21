import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useFilters } from '../state/useFilters'
import type { ScoutCandidate, ScoutResult } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { PlayerName } from '../components/PlayerName'
import { ParMeter } from '../components/ParMeter'
import { useGender } from '../gender/useGender'
import { change, rate, score } from '../format'
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
 * Find a Player (§17) - a scouting brief, not a leaderboard.
 *
 * §17 warns that shipping this before its inputs exist means "a filter that
 * quietly ignores half the brief". The page is built so that cannot happen:
 * the response carries `applied` and `ignored`, and both are rendered. A
 * constraint the data cannot honour is named on screen with its reason rather
 * than dropped silently, so a reader can never mistake an unfiltered list for
 * a filtered one.
 *
 * The second honesty device is coverage. Role, batting hand and bowling style
 * come from announced squads, which cover about a quarter of the register -
 * higher among current players, near zero among historical ones. So the count
 * of candidates carrying any sourced attribute sits above the results: a hand
 * or style filter can only ever match inside that subset, and a reader who
 * does not know it would read "no left-handers" as a fact about cricket.
 */

const ROLES = [
  { value: '', label: 'Any role' },
  { value: 'Batter', label: 'Batter' },
  { value: 'Bowler', label: 'Bowler' },
  { value: 'All-Rounder', label: 'All-rounder' },
  { value: 'Wicket Keeper', label: 'Wicketkeeper' },
]

const HANDS = [
  { value: '', label: 'Either hand' },
  { value: 'RHB', label: 'Right-hand bat' },
  { value: 'LHB', label: 'Left-hand bat' },
]

const FAMILIES = [
  { value: '', label: 'Any bowling' },
  { value: 'pace', label: 'Pace' },
  { value: 'spin', label: 'Spin' },
]

const FORM_STATES = [
  { value: '', label: 'Any form' },
  { value: 'in_form', label: 'In form' },
  { value: 'steady', label: 'Steady' },
]

const SCOPES = [
  { value: 'international', label: 'International' },
  { value: 'domestic_league', label: 'Franchise leagues' },
]

export function Scout() {
  const { slug, apiGender } = useGender()
  const f = useFilters()
  const { set: update } = f

  const scope = f.get('scope', 'international')
  const role = f.get('role')
  const hand = f.get('hand')
  const family = f.get('family')
  const formState = f.get('form')
  const maxAge = f.get('max_age')
  const minMatches = f.get('min_matches', '20')

  const [data, setData] = useState<ScoutResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)


  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .scout({
        gender: apiGender,
        competition_type: scope,
        role: role || undefined,
        batting_style: hand || undefined,
        bowling_family: family || undefined,
        form_state: formState || undefined,
        max_age: maxAge ? Number(maxAge) : undefined,
        min_matches: Number(minMatches) || 20,
        limit: 40,
      })
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [apiGender, scope, role, hand, family, formState, maxAge, minMatches])

  const sourcedShare =
    data && data.candidates_considered
      ? data.with_sourced_attributes / data.candidates_considered
      : 0
  const attributeFiltered = Boolean(hand || family)

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Scout"
        title="Find a Player"
        blurb="Describe the player you need. Every constraint the data cannot honour is named rather than dropped."
      />

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Scope</span>
          <select value={scope} onChange={(e) => update({ scope: e.target.value })} className={fieldClass}>
            {SCOPES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
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
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Bowling</span>
          <select value={family} onChange={(e) => update({ family: e.target.value })} className={fieldClass}>
            {FAMILIES.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Form</span>
          <select value={formState} onChange={(e) => update({ form: e.target.value })} className={fieldClass}>
            {FORM_STATES.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Max age</span>
          <input
            type="number"
            min={15}
            max={60}
            value={maxAge}
            placeholder="any"
            onChange={(e) => update({ max_age: e.target.value })}
            className={`${fieldClass} w-24`}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Min matches</span>
          <input
            type="number"
            min={1}
            max={500}
            value={minMatches}
            onChange={(e) => update({ min_matches: e.target.value })}
            className={`${fieldClass} w-24`}
          />
        </label>
      </div>

      {/* What the brief could and could not do, above the results. */}
      {data && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card>
            <p className="u-eyebrow">Coverage</p>
            <p className="mt-1.5 text-sm text-ink">
              <span className="tnum">{data.with_sourced_attributes.toLocaleString()}</span> of{' '}
              <span className="tnum">{data.candidates_considered.toLocaleString()}</span> candidates
              carry a sourced role, hand or bowling style
              <span className="text-muted"> ({Math.round(sourcedShare * 100)}%)</span>.
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              Those come from announced squads, so they cover current players far better than
              historical ones.
              {attributeFiltered && (
                <>
                  {' '}
                  This brief filters on one of them, so nobody outside that subset can appear -
                  their absence is missing data, not a missing player.
                </>
              )}
              {data.unknown_age > 0 && (
                <>
                  {' '}
                  <span className="tnum">{data.unknown_age.toLocaleString()}</span> have no recorded
                  date of birth; an age limit keeps them rather than dropping them.
                </>
              )}
            </p>
          </Card>

          <Card className={Object.keys(data.ignored).length ? 'border-warning/30 bg-warning-dim/30' : ''}>
            <p className="u-eyebrow">Constraints</p>
            {Object.keys(data.applied).length > 0 && (
              <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
                {Object.entries(data.applied).map(([key, text]) => (
                  <li key={key}>
                    <span className="text-positive-ink">applied</span>{' '}
                    <span className="text-ink">{key.replace(/_/g, ' ')}</span> - {text}
                  </li>
                ))}
              </ul>
            )}
            {Object.keys(data.ignored).length > 0 ? (
              <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
                {Object.entries(data.ignored).map(([key, text]) => (
                  <li key={key}>
                    <span className="text-warning-ink">not applied</span>{' '}
                    <span className="text-ink">{key.replace(/_/g, ' ')}</span> - {text}
                  </li>
                ))}
              </ul>
            ) : (
              Object.keys(data.applied).length === 0 && (
                <p className="mt-1.5 text-xs text-muted">
                  No constraints set - this is the whole candidate pool, ranked.
                </p>
              )
            )}
          </Card>
        </div>
      )}

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner />}

      {data && !loading && (
        <Panel
          title="Candidates"
          blurb="Ranked on career standing and the Performance Index, moved by recent form. Every row says why it is here."
          aside={<span className="tnum text-xs text-muted">{data.candidates.length} shown</span>}
          bodyClassName=""
        >
          {data.candidates.length === 0 ? (
            <div className="p-4">
              <EmptyState
                title="Nobody matches this brief"
                hint="Attribute filters only reach players with a sourced role or style. Try relaxing the hand or bowling constraint, or lowering the minimum matches."
              />
            </div>
          ) : (
            <ul className="divide-y divide-border-subtle">
              {data.candidates.map((c) => (
                <CandidateRow key={c.player_identifier} c={c} slug={slug} />
              ))}
            </ul>
          )}

          <Provenance>
            Role, batting hand and bowling style are read from ICC squad announcements. Where a
            squad has never named a player, role falls back to the share of deliveries they faced
            against bowled and is marked inferred; hand and style have no fallback and stay blank
            rather than being guessed. Age comes from Wikidata and is absent for most of the
            register.
          </Provenance>
        </Panel>
      )}
    </div>
  )
}

function CandidateRow({ c, slug }: { c: ScoutCandidate; slug: string }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3">
      <div className="min-w-0 flex-1">
        <PlayerName
          name={c.player_name}
          countryCode={c.country_code}
          country={c.country}
          to={`/${slug}/players/${c.player_identifier}`}
          nameClassName="font-medium"
        />
        <p className="mt-0.5 text-xs text-dim">{c.reason}</p>
      </div>

      <span
        className={`w-28 shrink-0 text-right text-xs ${c.role_sourced ? 'text-muted' : 'uncertain text-dim'}`}
        title={c.role_sourced ? 'Named in a squad with this role' : 'Inferred from balls faced against balls bowled'}
      >
        {c.role ?? '-'}
      </span>
      <span className="w-12 shrink-0 text-right font-mono text-[11px] text-muted" title="Batting hand">
        {c.batting_style ?? '-'}
      </span>
      <span
        className="w-16 shrink-0 text-right font-mono text-[11px] text-muted"
        title={c.bowling_style ? `Bowling style: ${c.bowling_style}` : 'No bowling style recorded'}
      >
        {c.bowling_style ?? '-'}
      </span>
      <span className="tnum w-12 shrink-0 text-right text-xs text-muted" title="Age">
        {c.age ?? '-'}
      </span>
      <span className="tnum w-14 shrink-0 text-right text-xs text-muted" title="Matches in scope">
        {c.matches}
      </span>

      {/* Recent standing on the par datum, so form is read in absolute terms
          rather than as a percentage against the player's own baseline. */}
      <span className="w-28 shrink-0" title="Recent output in par units - 1.00 is an average appearance">
        <ParMeter value={c.recent_mean ?? null} />
      </span>
      {/* Bounded 0-100 rather than the raw ratio: the candidate score above is
          built from this figure, and the percentage it replaced had no ceiling
          so the two disagreed. */}
      <span
        className={`tnum w-16 shrink-0 text-right text-xs ${
          (c.form_score ?? 50) > 50 ? 'text-positive-ink' : 'text-muted'
        }`}
        title={`Form score out of 100 in this scope · ${c.form_display ?? change(c.form_delta)}`}
      >
        {c.form_score == null ? '-' : score(c.form_score)}
      </span>
      <span className="tnum w-14 shrink-0 text-right text-sm font-semibold text-ink" title="Scout score">
        {rate(c.score)}
      </span>
    </li>
  )
}
