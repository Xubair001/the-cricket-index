import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { VenueOption, VenueProfile } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { useGender } from '../gender/useGender'
import { useScope } from '../scope/scope'
import { GroundCharacterChart } from '../components/GroundCharacterChart'
import { competitionLabel } from '../competitions'
import { rate } from '../format'
import {
  Card,
  EmptyState,
  PageHeader,
  Panel,
  Provenance,
  SectionHeading,
  fieldClass,
  fieldLabelClass,
} from '../components/ui'

/**
 * Venue intelligence (§20) - what kind of cricket does this ground produce?
 *
 * The page is organised around that one question rather than around a table of
 * everything known about the ground. The lead figure is therefore the bat-first
 * win rate, because it is the decision a captain actually makes at the toss,
 * and it is set beside what captains *choose* here - where those two disagree
 * is the most interesting thing a venue page can show.
 *
 * Every rate is scoped to one competition. A ground that hosts Tests and T20Is
 * has two completely different characters and averaging them describes neither.
 */

/** Bat-first rates cluster near 50%, so the scale is stretched around it. */
function BatFirstBar({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="text-dim">-</span>
  // 30–70% spans the bar; anything beyond is pinned rather than clipped.
  const position = Math.max(0, Math.min(100, ((pct - 30) / 40) * 100))
  return (
    <div className="relative h-2 w-full overflow-hidden rounded-full bg-elevated">
      {/* The even-split datum. Everything on this page is read against it. */}
      <span className="absolute inset-y-0 left-1/2 w-px bg-border-strong" aria-hidden />
      <span
        className="absolute inset-y-0 w-1.5 -translate-x-1/2 rounded-full bg-analytic"
        style={{ left: `${position}%` }}
      />
    </div>
  )
}

/** An index against the format's own par, where 1.00 is typical. */
function ParIndex({ value, label }: { value: number | null; label: string }) {
  if (value === null) return <span className="tnum text-dim">-</span>
  const pct = Math.round((value - 1) * 100)
  const sign = pct > 0 ? '+' : ''
  return (
    <span
      className="tnum"
      title={`${label}: ${value.toFixed(2)}x the typical figure for this format`}
    >
      {value.toFixed(2)}
      <span className={`ml-1 text-xs ${Math.abs(pct) < 3 ? 'text-dim' : 'text-muted'}`}>
        ({sign}
        {pct}%)
      </span>
    </span>
  )
}

export function VenueAnalytics() {
  const { slug, apiGender } = useGender()
  const [params, setParams] = useSearchParams()
  const selected = params.get('venue') ?? ''

  const [grounds, setGrounds] = useState<VenueOption[]>([])
  const [profile, setProfile] = useState<VenueProfile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api
      .venues(apiGender)
      .then(setGrounds)
      .catch(() => setGrounds([]))
  }, [apiGender])

  useEffect(() => {
    if (!selected) {
      setProfile(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .venueProfile(selected, apiGender)
      .then((res) => !cancelled && setProfile(res))
      .catch((e) => !cancelled && (setError(String(e)), setProfile(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [selected, apiGender])

  // The cross-ground chart needs ONE competition, because a ground hosting
  // Tests and T20Is has two characters. Defaults to the competition with the
  // most cricket in the current family rather than to a fixed key, so the
  // Leagues switch does not open the chart on an empty international format.
  const { competitions } = useScope()
  const [charCompetition, setCharCompetition] = useState('')
  useEffect(() => {
    if (!charCompetition && competitions.length) setCharCompetition(competitions[0].key)
  }, [competitions, charCompetition])

  function choose(venue: string) {
    const merged = new URLSearchParams(params)
    if (venue) merged.set('venue', venue)
    else merged.delete('venue')
    setParams(merged, { replace: true })
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Analytics"
        title="Venue Analytics"
        blurb="What kind of cricket a ground produces - how it scores, how hard wickets are to take, and whether batting first is worth it."
      />

      {/* The population view FIRST. "Which grounds produce which cricket" is
          the question a reader has before they know which ground to open, and
          the per-ground panels below cannot answer it. */}
      <SectionHeading
        title="Where every ground sits"
        note="One competition at a time, because a ground that hosts two formats has two characters."
        aside={
          <label className="flex items-center gap-2">
            <span className="u-eyebrow">Competition</span>
            <select
              value={charCompetition}
              onChange={(e) => setCharCompetition(e.target.value)}
              className="rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink"
            >
              {competitions.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.display_name}
                </option>
              ))}
            </select>
          </label>
        }
      />

      {charCompetition && (
        <GroundCharacterChart
          gender={apiGender}
          competition={charCompetition}
          competitionLabel={competitionLabel(charCompetition)}
        />
      )}

      <SectionHeading
        title="One ground in detail"
        note="Every spelling of a ground contributes to one page, so a total here is its whole history."
      />

      <div className="max-w-xl">
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Ground</span>
          <select value={selected} onChange={(e) => choose(e.target.value)} className={fieldClass}>
            <option value="">Choose a ground…</option>
            {grounds.map((g) => (
              <option key={g.venue} value={g.venue}>
                {g.venue}
                {g.city && !g.venue.includes('(') ? ` - ${g.city}` : ''} ({g.matches})
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner />}

      {!selected && !loading && (
        <EmptyState
          title="Pick a ground"
          // Reads the live count rather than a number typed in once: the raw
          // spelling total was hardcoded at 593 and is now 636, so the sentence
          // had quietly become false.
          hint={`${grounds.length.toLocaleString()} grounds in this scope, normalised from the source's own spellings - every spelling of a ground contributes to one page.`}
        />
      )}

      {profile && !loading && (
        <>
          <Card>
            <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
              <div>
                <h2 className="text-lg font-semibold tracking-tight text-ink">{profile.venue}</h2>
                <p className="mt-0.5 text-sm text-muted">
                  {profile.city && <>{profile.city} · </>}
                  <span className="tnum">{profile.matches.toLocaleString()}</span> matches
                  {profile.first_match && (
                    <span className="tnum">
                      {' '}
                      · {profile.first_match.slice(0, 4)}–{profile.last_match?.slice(0, 4)}
                    </span>
                  )}
                </p>
              </div>
              {/* The normalisation receipt. Shown rather than hidden, because a
                  reader who knows the source spells this ground six ways is the
                  reader who trusts the totals. */}
              {profile.raw_spellings.length > 1 && (
                <p
                  className="max-w-sm text-xs text-dim"
                  title={profile.raw_spellings.join('\n')}
                >
                  Pooled from{' '}
                  <span className="tnum text-muted">{profile.raw_spellings.length}</span> spellings
                  in the source data
                </p>
              )}
            </div>
          </Card>

          {profile.formats.length === 0 ? (
            <EmptyState
              title="No cricket here in this scope"
              hint="This ground has matches in the dataset, but none for the currently selected gender."
            />
          ) : (
            profile.formats.map((f) => (
              <Panel
                key={f.competition_key}
                title={f.competition_name}
                blurb={
                  f.reliable
                    ? `${f.matches} matches at this ground.`
                    : `Only ${f.matches} matches here - too few for these rates to describe the ground, so read them as indicative.`
                }
                aside={
                  !f.reliable && (
                    <span className="rounded-full bg-warning-dim px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-warning-ink ring-1 ring-inset ring-warning/30">
                      Thin sample
                    </span>
                  )
                }
              >
                <div className="grid gap-5 lg:grid-cols-2">
                  {/* The question a captain asks at the toss. */}
                  <div>
                    <p className={fieldLabelClass}>Batting first</p>
                    <p className="tnum mt-1 text-2xl font-semibold text-ink">
                      {f.bat_first_win_pct !== null ? `${rate(f.bat_first_win_pct)}%` : '-'}
                      <span className="ml-2 text-sm font-normal text-muted">
                        of {f.decided_matches} decided
                      </span>
                    </p>
                    <div className="mt-3">
                      <BatFirstBar pct={f.bat_first_win_pct} />
                      <div className="mt-1 flex justify-between font-mono text-[10px] text-dim">
                        <span>30%</span>
                        <span className="text-muted">even</span>
                        <span>70%</span>
                      </div>
                    </div>
                    <p className="mt-3 text-xs leading-relaxed text-muted">
                      Captains choose to bat{' '}
                      <span className="tnum text-ink">
                        {f.chose_to_bat_pct !== null ? `${rate(f.chose_to_bat_pct)}%` : '-'}
                      </span>{' '}
                      of the time here.
                      {f.bat_first_win_pct !== null && f.chose_to_bat_pct !== null && (
                        <>
                          {' '}
                          {describeToss(f.bat_first_win_pct, f.chose_to_bat_pct)}
                        </>
                      )}
                    </p>
                  </div>

                  {/* How the ground plays, always against its own format. */}
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                    <Figure
                      label="Scoring rate"
                      value={<ParIndex value={f.scoring_index} label="Scoring rate" />}
                      note="vs this format"
                    />
                    <Figure
                      label="Wickets"
                      value={<ParIndex value={f.wicket_index} label="Balls per wicket" />}
                      note="above 1 = harder"
                    />
                    <Figure
                      label="Runs per wicket"
                      value={<span className="tnum">{rate(f.runs_per_wicket)}</span>}
                    />
                    <Figure
                      label="Boundaries"
                      value={<span className="tnum">{rate(f.boundary_rate)}</span>}
                      note="per 100 balls"
                    />
                    <Figure
                      label="Runs off the bat"
                      value={<span className="tnum">{rate(f.runs_off_bat_per_match)}</span>}
                      note="per match, both sides"
                    />
                    <Figure
                      label="Toss winner wins"
                      value={
                        <span className="tnum">
                          {f.toss_win_pct !== null ? `${rate(f.toss_win_pct)}%` : '-'}
                        </span>
                      }
                    />
                  </dl>
                </div>

                <Provenance>
                  Who batted first is derived from the toss - the toss winner if they chose to bat,
                  otherwise their opponent - which is recorded for every match, so this needs no
                  ball-by-ball data. “Runs off the bat” excludes extras, which are not attributed to
                  a batter, so it runs about 5% under a true team total; the indices against par are
                  unaffected because both sides are measured the same way.{' '}
                  <Link
                    to={`/${slug}/analytics/batting?venue=${encodeURIComponent(profile.venue)}`}
                    className="text-analytic-ink hover:underline"
                  >
                    See the players who scored them →
                  </Link>
                </Provenance>
              </Panel>
            ))
          )}

          <p className="max-w-3xl text-xs leading-relaxed text-dim">
            Phase splits, dot-ball rates and pace-versus-spin are absent rather than approximated:
            all three need the per-delivery records this pipeline aggregates and discards. What is
            here is everything the match-level data genuinely supports.
          </p>
        </>
      )}
    </div>
  )
}

function Figure({
  label,
  value,
  note,
}: {
  label: string
  value: React.ReactNode
  note?: string
}) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-semibold text-ink">{value}</dd>
      {note && <dd className="text-[11px] text-dim">{note}</dd>}
    </div>
  )
}

/**
 * The interesting case is disagreement between what captains choose and what
 * actually wins - that is where a venue page tells a selector something they
 * did not already assume.
 *
 * A strong preference that does not pay is worth saying even when the win rate
 * itself is unremarkable: at Sharjah, ODI captains bat first 88% of the time
 * and win 45% doing it. "The toss decides little" is true of the outcome and
 * misses the point about the decision.
 */
function describeToss(batFirstWin: number, choseBat: number): string {
  const chasing = batFirstWin < 45
  const batting = batFirstWin > 55
  const prefersBat = choseBat > 65
  const prefersField = choseBat < 35

  if (chasing && prefersBat) return 'They mostly bat - and mostly lose doing it.'
  if (batting && prefersField) return 'Batting first wins here, yet most captains field.'
  if (chasing) return 'Chasing wins here, and captains largely act on it.'
  if (batting) return 'Batting first wins here, and captains act on it.'
  // Even outcome, lopsided decision: the habit is not being rewarded.
  if (prefersBat) return 'Captains strongly prefer to bat, though it wins no more often than chasing.'
  if (prefersField) return 'Captains strongly prefer to field, though it wins no more often than batting.'
  return 'The toss decides little here.'
}
