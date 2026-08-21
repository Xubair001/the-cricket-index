import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { useFilters } from '../state/useFilters'
import type { SquadAnalysis as SquadAnalysisType, TeamSummary } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { PlayerName } from '../components/PlayerName'
import { useGender } from '../gender/useGender'
import { rate } from '../format'
import {
  EmptyState,
  PageHeader,
  Panel,
  Provenance,
  Uncertain,
  fieldClass,
  fieldLabelClass,
  tableClass,
  tdClass,
  tdNumClass,
  tdNumStrongClass,
  thClass,
  thNumClass,
  theadRowClass,
  trClass,
} from '../components/ui'

/**
 * Squad analysis (§8) - who a side is picking now, and what that group is made of.
 *
 * The window is the team's own last N matches rather than a date range. Most of
 * the ~110 international sides in this dataset play a handful of matches a year
 * and then nothing for a long stretch; a calendar window reports them as having
 * no squad, which is a statement about the fixture list rather than the side.
 *
 * Every role on this page is **inferred** from where a player spent their
 * deliveries in this window, and is labelled as such on every row. That is the
 * only role signal the data carries. Wicketkeeper, batting position and
 * handedness are not derivable at any threshold, and the page says so rather
 * than leaving a reader to assume the picture is complete.
 */

const WINDOWS = [10, 20, 30, 50]

// Categorical identity, in the fixed order defined in index.css. Never cycled.
const ROLE_SERIES: Record<string, string> = {
  batter: 'var(--color-series-1)',
  allrounder: 'var(--color-series-2)',
  bowler: 'var(--color-series-3)',
  unknown: 'var(--color-border-strong)',
}

const ROLE_LABEL: Record<string, string> = {
  batter: 'Batters',
  allrounder: 'All-rounders',
  bowler: 'Bowlers',
  unknown: 'Unclassified',
}

const ROLE_CHIP: Record<string, string> = {
  batter: 'Bat',
  allrounder: 'All',
  bowler: 'Bowl',
  unknown: '-',
}

const ORDER = ['batter', 'allrounder', 'bowler', 'unknown']

/**
 * Squad composition as one bar.
 *
 * A 2px surface gap sits between segments so the boundary reads even where two
 * hues are close in value, and every segment is directly labelled - identity
 * never rests on colour alone.
 */
function CompositionBar({ counts }: { counts: Record<string, number> }) {
  const total = ORDER.reduce((sum, r) => sum + (counts[r] ?? 0), 0)
  if (!total) return null
  const present = ORDER.filter((r) => (counts[r] ?? 0) > 0)

  return (
    <div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-sunken">
        {present.map((role, i) => (
          <div key={role} className="flex h-full" style={{ width: `${((counts[role] ?? 0) / total) * 100}%` }}>
            {i > 0 && <span className="w-0.5 shrink-0 bg-surface" aria-hidden />}
            <span
              className="h-full flex-1"
              style={{ background: ROLE_SERIES[role] }}
              title={`${counts[role]} ${ROLE_LABEL[role].toLowerCase()}`}
            />
          </div>
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5">
        {present.map((role) => (
          <span key={role} className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span
              aria-hidden
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: ROLE_SERIES[role] }}
            />
            <span className="tnum font-medium text-ink">{counts[role]}</span>
            {ROLE_LABEL[role]}
          </span>
        ))}
      </div>
    </div>
  )
}

function Reliance({
  label,
  share,
  topN,
  unit,
}: {
  label: string
  share: number | null
  topN: number
  unit: string
}) {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-card">
      <p className="u-eyebrow">{label}</p>
      <p className="u-display tnum mt-2 text-2xl text-ink">
        {share === null ? '-' : `${share.toFixed(0)}%`}
      </p>
      <p className="mt-1 text-xs leading-relaxed text-dim">
        of the window's {unit} came from the top {topN}. A higher figure means a side that leans
        harder on a few players.
      </p>
    </div>
  )
}

export function SquadAnalysis() {
  const { slug, apiGender } = useGender()
  const f = useFilters()
  const { set: update, clear } = f

  // Selection lives in the URL so a squad view is a link a scout can send (§24).
  const teamId = f.get('team')
  const windowMatches = f.int('window', 20)

  const [teams, setTeams] = useState<TeamSummary[]>([])
  const [data, setData] = useState<SquadAnalysisType | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)


  useEffect(() => {
    api
      .teams(apiGender, undefined, { limit: 500 })
      .then((res) => setTeams(res.items))
      .catch(() => setTeams([]))
  }, [apiGender])

  // A team_id from one gender means nothing in the other, so switching clears
  // the selection rather than carrying a foreign id into a 404.
  //
  // Keyed off an actual *change* rather than firing on mount: unguarded, this
  // wiped the ?team= that a TeamDetail link had just navigated with, and - worse
  // - cancelled the request already in flight for it, so `loading` never
  // cleared and the page sat on its spinner forever.
  const previousGender = useRef(apiGender)
  useEffect(() => {
    if (previousGender.current === apiGender) return
    previousGender.current = apiGender
    setData(null)
    clear()
  }, [apiGender, clear])

  useEffect(() => {
    if (!teamId) {
      setData(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .teamSquad(Number(teamId), { window_matches: windowMatches })
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [teamId, windowMatches])

  // National sides first, then franchises: the two are never interleaved
  // anywhere else in the product and this control should not be the exception.
  const grouped = useMemo(() => {
    const national = teams.filter((t) => t.team_type === 'international')
    const other = teams.filter((t) => t.team_type !== 'international')
    return { national, other }
  }, [teams])

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Teams"
        title="Squad Analysis"
        blurb="What a side is currently made of, read from the last matches they actually played. Roles are inferred from deliveries, never sourced."
      />

      <div className="grid gap-4 rounded-xl border border-border-subtle bg-surface p-4 shadow-card sm:grid-cols-3">
        <div className="space-y-2 sm:col-span-2">
          <label className={fieldLabelClass} htmlFor="squad-team">
            Team
          </label>
          <select
            id="squad-team"
            value={teamId}
            onChange={(e) => update({ team: e.target.value })}
            className={fieldClass}
          >
            <option value="">Select a team…</option>
            <optgroup label="International">
              {grouped.national.map((t) => (
                <option key={t.team_id} value={t.team_id}>
                  {t.name} ({t.matches})
                </option>
              ))}
            </optgroup>
            {grouped.other.length > 0 && (
              <optgroup label="Franchise">
                {grouped.other.map((t) => (
                  <option key={t.team_id} value={t.team_id}>
                    {t.name} ({t.matches})
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>
        <div className="space-y-2">
          <label className={fieldLabelClass} htmlFor="squad-window">
            Window
          </label>
          <select
            id="squad-window"
            value={windowMatches}
            onChange={(e) => update({ window: e.target.value })}
            className={fieldClass}
          >
            {WINDOWS.map((w) => (
              <option key={w} value={w}>
                Last {w} matches
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner label="Reading the squad" />}

      {!teamId && !loading && (
        <EmptyState
          title="Pick a team"
          hint="Squad analysis works for franchises as well as national sides - a franchise squad is where the inferred roles are most worth reading, since the side is assembled rather than selected from one country."
        />
      )}

      {data && !loading && (
        <>
          {data.matches_in_window === 0 ? (
            <EmptyState
              title={`No matches on record for ${data.team_name}`}
              hint="This side appears in the teams list but has no per-player figures in the dataset."
            />
          ) : (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <Panel
                  title="Composition"
                  blurb={`${data.members.length} players used across ${data.matches_in_window} matches, ${data.first_match} to ${data.last_match}.`}
                >
                  <CompositionBar counts={data.role_counts} />
                  <div className="mt-4 grid grid-cols-3 gap-3 border-t border-border-subtle pt-3">
                    {['batter', 'allrounder', 'bowler'].map((role) => (
                      <div key={role}>
                        <p className="u-eyebrow">{ROLE_LABEL[role]}</p>
                        <p className="tnum mt-1 text-sm text-ink">
                          {data.runs_by_role[role]?.toLocaleString() ?? 0}
                          <span className="text-dim"> runs</span>
                        </p>
                        <p className="tnum text-sm text-ink">
                          {data.wickets_by_role[role] ?? 0}
                          <span className="text-dim"> wkts</span>
                        </p>
                      </div>
                    ))}
                  </div>
                </Panel>

                <div className="grid gap-4 sm:grid-cols-2">
                  <Reliance
                    label="Run reliance"
                    share={data.top_run_share}
                    topN={data.reliance_top_n}
                    unit="runs"
                  />
                  <Reliance
                    label="Wicket reliance"
                    share={data.top_wicket_share}
                    topN={data.reliance_top_n}
                    unit="wickets"
                  />
                </div>
              </div>

              <div className="scroll-x rounded-xl border border-border-subtle bg-surface shadow-card">
                <table className={`${tableClass} min-w-[900px]`}>
                  <thead>
                    <tr className={theadRowClass}>
                      <th className="px-4 py-2.5">Player</th>
                      <th className={thClass}>Role</th>
                      <th className={thNumClass}>Mat</th>
                      <th className={thNumClass}>Runs</th>
                      <th className={thNumClass}>Avg</th>
                      <th className={thNumClass}>SR</th>
                      <th className={thNumClass}>Wkts</th>
                      <th className={thNumClass}>Avg</th>
                      <th className={thNumClass}>Econ</th>
                      <th className={thNumClass}>Last</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.members.map((m) => (
                      <tr key={m.player_identifier} className={trClass}>
                        <td className="px-4 py-2.5">
                          <PlayerName
                            name={m.player_name}
                            country={m.country}
                            countryCode={m.country_code}
                            to={`/${slug}/players/${m.player_identifier}`}
                            nameClassName="font-medium"
                          />
                        </td>
                        <td className={tdClass}>
                          {/* The role is a guess from ball counts, so the chip
                              is neutral - green/red/amber stay reserved for
                              above/below par. A thin sample gets the dotted
                              uncertainty rule rather than a different colour. */}
                          <span
                            className="inline-flex items-center rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
                            title={
                              m.bowling_share === null
                                ? 'No deliveries recorded in this window'
                                : `${Math.round(m.bowling_share * 100)}% of their deliveries in this window were bowled - inferred, not a sourced role`
                            }
                          >
                            {m.role_confident ? (
                              ROLE_CHIP[m.role] ?? m.role
                            ) : (
                              <Uncertain reason="Too few deliveries in this window for the role to be more than a hint">
                                {ROLE_CHIP[m.role] ?? m.role}
                              </Uncertain>
                            )}
                          </span>
                        </td>
                        <td className={tdNumStrongClass}>{m.matches}</td>
                        <td className={tdNumClass}>{m.runs.toLocaleString()}</td>
                        <td className={tdNumClass}>{rate(m.batting_average)}</td>
                        <td className={tdNumClass}>{rate(m.strike_rate)}</td>
                        <td className={tdNumClass}>{m.wickets}</td>
                        <td className={tdNumClass}>{rate(m.bowling_average)}</td>
                        <td className={tdNumClass}>{rate(m.economy)}</td>
                        <td className={tdNumClass}>{m.last_played ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Stated in the API payload and rendered verbatim, so the page
                  cannot drift into presenting a partial picture as a whole one. */}
              <Panel
                title="What this cannot tell you"
                blurb="Everything above is derived from per-match totals. These are not thresholds that could be loosened - the records simply do not carry them."
              >
                <ul className="space-y-1.5 text-sm text-muted">
                  {data.unavailable.map((line) => (
                    <li key={line} className="flex gap-2">
                      <span aria-hidden className="text-dim">
                        ·
                      </span>
                      {line}
                    </li>
                  ))}
                </ul>
              </Panel>

              <Provenance>
                Roles come from each player's share of deliveries in this window - under 25% bowled
                reads as a batter, over 78% as a bowler, and the wide band between the two as an
                all-rounder. The cuts are permissive on purpose: leaving a genuine all-rounder off a
                list costs more than admitting a marginal one. A dotted underline on a role means
                fewer than 60 deliveries stand behind it. Figures are for this team only, within
                this window, and are never blended with the same player's record elsewhere.
              </Provenance>
            </>
          )}
        </>
      )}
    </div>
  )
}
