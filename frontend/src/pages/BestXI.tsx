import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { SelectedSide, SelectionPick, TeamSummary } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { PlayerName } from '../components/PlayerName'
import { useGender } from '../gender/useGender'
import { useScope, useScopedCompetition } from '../scope/scope'
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
 * Best XI / XV (§18).
 *
 * The page has to answer "why is this player in the side", not just list names -
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

const SIZES = [
  { value: 11, label: 'XI' },
  { value: 15, label: 'XV' },
]

/**
 * Which question the side answers.
 *
 * These are genuinely different questions, not a filter on one answer, which
 * is why they are named rather than offered as a checkbox. An all-time side
 * picks from everyone who ever played enough in the scope - so it returns
 * Sangakkara, Warne and Ryan Harris for Tests, which is right for "the best
 * there has been" and useless for "who do we pick next".
 */
const POOLS = [
  {
    value: 'current',
    label: 'Current squad',
    hint: 'Only players still in the picture - last appearance in this scope within a year, and no sourced retirement. This is the one to pick a next squad from, and the page default.',
  },
  {
    value: 'all_time',
    label: 'All time',
    hint: 'Everyone with enough of a record in this competition, retired players included. Answers "the best there has been", not "who do we pick".',
  },
]

/*
 * Section 18's optimisation objectives. Kept in the client only as labels for
 * the control - the API validates the value against its own table and returns
 * the label and the explanation it actually applied, which is what the page
 * renders. So adding an objective server-side does not silently produce a
 * dropdown entry that means nothing.
 */
const OBJECTIVES = [
  { value: 'overall', label: 'Overall quality' },
  { value: 'form', label: 'Current form' },
  { value: 'batting', label: 'Batting strength' },
  { value: 'bowling', label: 'Bowling strength' },
  { value: 'balance', label: 'Balance' },
  { value: 'youth', label: 'Youth' },
  { value: 'experience', label: 'Experience' },
]

/** Conventional reading order for a team sheet, not the order picked. */
const SLOT_ORDER = ['batter', 'wicketkeeper', 'allrounder', 'bowler']

const SLOT_LABEL: Record<string, string> = {
  batter: 'Batter',
  wicketkeeper: 'Wicketkeeper',
  allrounder: 'All-rounder',
  bowler: 'Bowler',
  unknown: '-',
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

/**
 * Form as a short, honest phrase.
 *
 * Reads the bounded score rather than `form_delta`, because the selection
 * weighting is built from the score: showing the raw ratio here meant a pick
 * chosen partly on a form term of 92 was labelled "+18%", with no way to see
 * the relationship. The move itself is still stated, worded by the API so it is
 * never a percentage over 100.
 */
function formNote(p: SelectionPick): { text: string; tone: string } {
  if (p.form_score === null) {
    return { text: p.form_delta === null ? 'form unknown' : 'form not placeable', tone: 'text-dim' }
  }
  const tone =
    p.form_score > 60 ? 'text-positive-ink' : p.form_score < 40 ? 'text-negative-ink' : 'text-muted'
  const move = p.form_display ?? change(p.form_delta)
  return { text: `form ${score(p.form_score)}/100 · ${move}`, tone }
}

export function BestXI() {
  const { apiGender, slug } = useGender()
  const [params, setParams] = useSearchParams()

  const requestedCompetition = params.get('competition') ?? ''
  const size = Number(params.get('size') ?? 11)
  const teamId = params.get('team') ?? ''
  // The PAGE defaults to the current squad; the API still defaults to all-time.
  //
  // Two different requirements. A reader who opens "Best XI" is almost always
  // asking who to pick next, and landing on a side containing Shane Warne and
  // Muttiah Muralitharan reads as the product ignoring that they retired. But
  // the API default has to stay `all_time`, because links already shared carry
  // no `pool` parameter and must keep returning the side they returned before.
  //
  // So the page sends its intent explicitly rather than relying on the default,
  // and `?pool=all_time` still selects the all-time side.
  const pool = params.get('pool') === 'all_time' ? 'all_time' : 'current'
  const objective = params.get('objective') || 'overall'
  const venue = params.get('venue') ?? ''

  const { competitions } = useScope()
  const {
    competition: scopedCompetition,
    options: competitionOptions,
  } = useScopedCompetition(requestedCompetition)
  // A side has to be picked within ONE competition - blending Tests and T20Is
  // would field a side for a format nobody plays - so unlike the boards there
  // is no "all" option here. Falling back to the family's first competition
  // keeps the page working the moment the switch changes family.
  const competition = scopedCompetition || competitions[0]?.key || ''

  const [teams, setTeams] = useState<TeamSummary[]>([])
  const [grounds, setGrounds] = useState<{ venue: string; matches: number }[]>([])
  const [side, setSide] = useState<SelectedSide | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // `side.scope` is the API's own key ('psl'), which is a query value and not
  // a name. Resolve it against the competition list rather than title-casing
  // it, so "T20I" and "ODI" keep the capitalisation the data gives them.
  const scopeLabel =
    competitions.find((c) => c.key === side?.scope)?.display_name ?? side?.scope ?? ''

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
    api
      .venues(apiGender)
      .then((res) => setGrounds(res.map((g) => ({ venue: g.venue, matches: g.matches }))))
      .catch(() => setGrounds([]))
  }, [apiGender])

  useEffect(() => {
    if (!competition) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .bestSide(apiGender, {
        competition,
        size,
        pool,
        objective,
        venue: venue || undefined,
        team_id: teamId ? Number(teamId) : undefined,
      })
      .then((res) => !cancelled && setSide(res))
      .catch((e) => !cancelled && (setError(String(e)), setSide(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [apiGender, competition, size, teamId, pool, objective, venue])

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Discover"
        title={size === 15 ? 'Best XV' : 'Best XI'}
        blurb="A side picked to a role shape - not the top eleven on rating, which returns six openers and no keeper. Every place shows what it was picked on."
      />


      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Optimise for</span>
          <select
            value={objective}
            onChange={(e) => update({ objective: e.target.value === 'overall' ? '' : e.target.value })}
            className={fieldClass}
            title={side?.objective_detail}
          >
            {OBJECTIVES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Pick from</span>
          <select
            value={pool}
            onChange={(e) => update({ pool: e.target.value === 'all_time' ? 'all_time' : '' })}
            className={fieldClass}
            title={POOLS.find((p) => p.value === pool)?.hint}
          >
            {POOLS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Ground</span>
          <select
            value={venue}
            onChange={(e) => update({ venue: e.target.value })}
            className={fieldClass}
            title="Tilts the side towards players with a record at this ground. Not a re-scope: at any one ground most players have one or two matches, so a side picked only on venue records would be picked on noise."
          >
            <option value="">Any ground</option>
            {grounds.slice(0, 200).map((g) => (
              <option key={g.venue} value={g.venue}>
                {g.venue} ({g.matches})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Competition</span>
          <select
            value={competition}
            onChange={(e) => update({ competition: e.target.value, team: '' })}
            className={fieldClass}
          >
            {competitionOptions
              .filter((c) => c.value !== '')
              .map((c) => (
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
                <span className="text-ink">{key.replace(/_/g, ' ')}</span> - {reason}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-dim">
            The roles below are balanced. Batting hand and bowling type are now sourced from ICC
            squad announcements, but only for players who appear in one - so the seam/spin split and
            the left-right pairing are reported beneath the side rather than selected for. Filling a
            quota on partial coverage would prefer players who happen to have squad data over better
            players who do not.
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
              title={side.team_name ? `${side.team_name} - best ${size === 15 ? 'XV' : 'XI'}` : `Best ${size === 15 ? 'XV' : 'XI'}`}
              blurb={
                <>
                  Picked from {scopeLabel} cricket
                  {/* The pool is stated in the panel header, not left to the
                      dropdown, because the same heading means two different
                      things depending on it. */}
                  {side.pool === 'current' ? (
                    <>
                      {' '}
                      from{' '}
                      <span className="font-semibold text-ink">
                        {side.pool_size} current players
                      </span>{' '}
                      of {side.pool_considered} who have played enough
                    </>
                  ) : (
                    <>
                      {' '}
                      from all {side.pool_considered} who have played enough, retired players
                      included
                    </>
                  )}
                  . Shape:{' '}
                  {Object.entries(side.shape)
                    .map(([role, n]) => `${n} ${SLOT_LABEL[role]?.toLowerCase() ?? role}`)
                    .join(', ')}
                  {/* Only say this when the shape actually leaves a place open.
                      The default shape sums to ten of eleven, but the batting,
                      bowling and balance objectives fill all eleven - and
                      promising "the remaining places on merit" when there are
                      none describes a step that did not happen. */}
                  {Object.values(side.shape).reduce((sum, n) => sum + n, 0) < side.size
                    ? ', with the remaining places on merit.'
                    : ', which fills the side.'}
                  {side.venue && (
                    <>
                      {' '}
                      Tilted towards <strong className="font-semibold text-ink">
                        {side.venue}
                      </strong>
                      , where{' '}
                      <span className="tnum">{side.venue_candidates_with_record}</span> of{' '}
                      <span className="tnum">{side.pool_size}</span> candidates have any record -
                      a record at one ground moves a player within the side rather than deciding
                      it, because at most grounds the median player has one or two matches.
                    </>
                  )}
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
                              title={
                                p.keeper_source === 'squad'
                                  ? 'Named a wicketkeeper in an ICC squad announcement'
                                  : 'Identified from stumpings - only a keeper can take one'
                              }
                            >
                              wk
                            </span>
                          )}
                          {p.batting_style && (
                            <span
                              className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
                              title="Batting hand, from an ICC squad announcement"
                            >
                              {p.batting_style}
                            </span>
                          )}
                          {/* Only on a bowling slot: the feed records a style
                              for any occasional bowler, so it says nothing
                              useful beside a specialist batter's name. */}
                          {p.bowling_family && (p.slot === 'bowler' || p.slot === 'allrounder') && (
                            <span
                              className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
                              title="Bowling type, from an ICC squad announcement"
                            >
                              {p.bowling_family}
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
                        {/* The at-ground record, always with its sample beside
                            it. Three matches at a ground is not a venue record,
                            and a figure shown without its count invites reading
                            it as one. */}
                        {p.venue_matches !== null && p.venue_mean !== null && (
                          <p className="mt-0.5 text-xs text-muted">
                            At this ground:{' '}
                            <span className="tnum font-medium text-ink">
                              {rate(p.venue_mean)}x par
                            </span>{' '}
                            from{' '}
                            <span className="tnum">
                              {p.venue_matches} {p.venue_matches === 1 ? 'match' : 'matches'}
                            </span>
                            {p.venue_matches < 4 && ' - too few to move them much'}
                          </p>
                        )}
                      </div>

                      <span
                        className="w-24 shrink-0 text-right text-xs text-muted"
                        title="Inferred from balls faced versus balls bowled - never a sourced fact"
                      >
                        {SLOT_LABEL[p.slot] ?? p.slot}
                      </span>
                      <span className={`w-40 shrink-0 text-right text-xs ${form.tone}`}>
                        {form.text}
                      </span>
                      <span
                        className="tnum w-12 shrink-0 text-right text-sm font-semibold text-ink"
                        title="Career standing 55%, Performance Index 30%, current form 15% - all within this scope"
                      >
                        {rate(p.selection_score)}
                      </span>
                    </li>
                  )
                })}
              </ol>

              {/* The blend is different for a current squad - career standing
                  drops from 55% to 40% and the two recent-evidence terms rise,
                  because inside a pool already restricted to current players
                  the career record is what discriminates least. Shown rather
                  than described, so the change is checkable. */}
              {Object.keys(side.weights).length > 0 && (
                <div className="border-t border-border-subtle px-4 py-2.5">
                  <p className="text-xs text-dim">
                    Scored on{' '}
                    {Object.entries(side.weights)
                      .map(([k, v]) => `${Math.round(v * 100)}% ${k === 'index' ? 'Performance Index' : k === 'career' ? 'career standing' : 'current form'}`)
                      .join(', ')}
                    {side.cutoff_date && (
                      <>
                        {' '}· current means an appearance since{' '}
                        <span className="tnum">{side.cutoff_date}</span>, measured from the most
                        recent match here ({side.reference_date}) rather than from today
                      </>
                    )}
                    .
                  </p>
                </div>
              )}

              {/* Section 18 requires this outright: "Show what was traded off -
                  the highest-rated player omitted, and the constraint that
                  omitted them." Without it the side is an assertion; with it a
                  selector can see the decision they are being asked to accept.
                  Only players who out-score somebody actually picked appear -
                  a candidate below every pick was not traded off, they simply
                  were not good enough. */}
              {side.tradeoffs.length > 0 && (
                <div className="border-t border-border-subtle px-4 py-3">
                  <h3 className="u-eyebrow mb-2">What this side cost</h3>
                  {/* The benchmark is stated once rather than repeated on every
                      row: it is the same player each time, and five copies of
                      "against 85.13 for the lowest place (Kumar Sangakkara)"
                      buries the part that differs, which is the constraint. */}
                  {side.tradeoffs[0]?.displaced && (
                    <p className="mb-1.5 text-xs text-dim">
                      The lowest place in this side scores{' '}
                      <span className="tnum">{rate(side.tradeoffs[0].displaced_score)}</span> (
                      {side.tradeoffs[0].displaced}). These players score higher and are still out:
                    </p>
                  )}
                  <ul className="space-y-1.5">
                    {side.tradeoffs.map((t) => (
                      <li key={t.player_identifier} className="text-xs leading-relaxed text-muted">
                        <Link
                          to={`/${slug}/players/${t.player_identifier}`}
                          className="font-medium text-ink hover:text-analytic-ink"
                        >
                          {t.player_name}
                        </Link>{' '}
                        <span className="text-dim">({SLOT_LABEL[t.role] ?? t.role})</span>{' '}
                        <span className="tnum">{rate(t.selection_score)}</span> - {t.reason}.
                      </li>
                    ))}
                  </ul>
                  {side.unknown_age > 0 && (
                    <p className="mt-2 text-xs text-dim">
                      {side.unknown_age} candidate{side.unknown_age === 1 ? '' : 's'} had no
                      recorded date of birth. This objective depends on age, so they were scored
                      neutrally rather than dropped - date of birth is known for about 42% of the
                      register and a hard bound would discard the majority.
                    </p>
                  )}
                </div>
              )}

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
                {/* The percentages are NOT repeated here. They differ between
                    the two pools, and a footnote that hardcoded the all-time
                    blend sat directly under a line stating the current one and
                    contradicted it. The line above is the single place they
                    are written, and it reads them from the response. */}
                Each place is scored on career standing in this scope, the Performance Index over
                the last 15 matches, and current form against the player's own baseline - in the
                proportions given above, which differ between the two pools. Career carries the
                most weight in both, because a best side is not the same as the side in the best
                touch, but it carries less for a current squad: inside a pool already restricted to
                players still in the picture, the career record is what separates them least. Roles
                are<em> inferred</em>: batter, bowler and all-rounder from balls faced versus
                bowled, openers from who faces the first ball, and the keeper from stumpings,
                because only a keeper can take one.
              </Provenance>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}
