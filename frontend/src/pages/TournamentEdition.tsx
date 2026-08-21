import { useEffect, useState } from 'react'
import { ActionLink } from '../components/ActionLink'

import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { EditionFixture, EditionLeader, TournamentEditionDetail } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Flag } from '../components/Flag'
import { PlayerName } from '../components/PlayerName'
import {
  EmptyState,
  PageHeader,
  Panel,
  Provenance,
  tableClass,
  tdClass,
  tdNumClass,
  tdNumStrongClass,
  thClass,
  thNumClass,
  theadRowClass,
  trClass,
} from '../components/ui'
import { count, rate } from '../format'
import { useGender } from '../gender/useGender'
import { useScope } from '../scope/scope'

/**
 * One edition of one tournament: the 2019 World Cup, the 2017 Champions Trophy.
 *
 * The page the tournament list used to stop short of. A tournament page can say
 * England won in 2019; only this page can say who they beat, what the group
 * table looked like, who scored the runs and which match was the final - and
 * every row here links onward to the match or the player.
 *
 * Three things it is careful about, all of them inherited from the API rather
 * than invented here:
 *
 * - **The table is not the published table.** It is computed from the matches
 *   this dataset holds, which for the 2019 World Cup is 33 of 45 group games.
 *   The API detects that directly - a round-robin gives every side the same
 *   number of matches, so an uneven "played" column is proof rather than a
 *   guess - and the note it returns is rendered above the table, not tucked
 *   into a tooltip.
 * - **Knockouts are excluded from the table and listed in the fixtures.** They
 *   are not part of any group's record, and counting the tied 2019 final into
 *   England's line gave them 13 points against a published 12.
 * - **Player-of-the-match counts are not "player of the tournament."** That is
 *   a panel's decision. This is a count of awards, and it is labelled as one.
 */
export function TournamentEdition() {
  const { apiGender, slug } = useGender()
  const { competitionType } = useScope()
  // The season is a splat because Cricsheet labels a tournament crossing a new
  // year "2023/24", and more than half the editions here are labelled that way.
  const { tournament: tournamentSlug, '*': season } = useParams()

  const [data, setData] = useState<TournamentEditionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!tournamentSlug || !season) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .tournamentEdition(tournamentSlug, season, apiGender, {
        competition_type: competitionType ?? undefined,
      })
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load this edition')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tournamentSlug, season, apiGender, competitionType])

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorMessage message={error} />
  if (!data) return <ErrorMessage message="Edition not found" />

  const knockouts = data.fixtures.filter((f) => f.stage)
  const groupGames = data.fixtures.filter((f) => !f.stage)

  return (
    <div className="space-y-6">
      <div>
        <ActionLink to={`/${slug}/tournaments/${data.tournament_slug}`} weight="quiet" direction="back">{data.tournament_name}</ActionLink>
      </div>

      <PageHeader
        eyebrow={`${data.competition_name} · ${data.season ?? 'edition'}`}
        title={`${data.tournament_name} ${data.season ?? ''}`.trim()}
        blurb={
          <>
            {count(data.matches)} matches held here across {count(data.sides)} sides
            {data.first_date && data.last_date && (
              <>
                , {data.first_date} to {data.last_date}
              </>
            )}
            .{' '}
            {data.champion_name ? (
              <>
                <strong className="font-semibold text-ink">{data.champion_name}</strong> won
                {data.runner_up_name && <>, beating {data.runner_up_name} in the final</>}
                {data.decided_by_tiebreak && <> on a tiebreak after the match was tied</>}.
              </>
            ) : data.has_final ? (
              <>The final is held here but records no winner.</>
            ) : (
              <>
                This dataset does not hold the final, so no champion is shown - which is different
                from nobody having won it.
              </>
            )}
          </>
        }
      />

      {/* Coverage first. A reader who takes this table for the official one has
          been misled by the page, not by the data. */}
      {data.notes.length > 0 && (
        <div className="space-y-2 rounded-xl border border-border-default bg-elevated px-4 py-3">
          <h2 className="u-eyebrow">What this edition does and does not hold</h2>
          <ul className="space-y-1.5">
            {data.notes.map((n) => (
              <li key={n} className="text-xs leading-relaxed text-muted">
                {n}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Standings data={data} />

      <div className="grid gap-5 lg:grid-cols-2">
        <LeaderPanel
          title="Leading run-scorers"
          blurb="Conventional totals within this edition, deliberately not adjusted for opposition strength - a tournament's leading scorer is a published figure and a weighted version would match no source."
          rows={data.top_run_scorers}
          slug={slug}
          columns={[
            ['M', (r) => count(r.matches)],
            ['Runs', (r) => count(r.runs), true],
            ['Avg', (r) => rate(r.average)],
            ['SR', (r) => rate(r.strike_rate)],
            ['100', (r) => count(r.hundreds)],
            ['50', (r) => count(r.fifties)],
            ['HS', (r) => count(r.highest)],
          ]}
        />
        <LeaderPanel
          title="Leading wicket-takers"
          blurb="On the same basis. Best is the most wickets in a single match, not a single innings, because the aggregate is stored per match."
          rows={data.top_wicket_takers}
          slug={slug}
          columns={[
            ['M', (r) => count(r.matches)],
            ['Wkts', (r) => count(r.wickets), true],
            ['Econ', (r) => rate(r.economy)],
            ['Avg', (r) => rate(r.bowling_average)],
            ['Best', (r) => count(r.best_innings)],
          ]}
        />
      </div>

      {data.most_awards.length > 0 && (
        <Panel
          title="Most player-of-the-match awards"
          blurb="The closest this data comes to a player of the tournament. It is a count of match awards, not that award - which is a selection panel's decision and is not recorded here."
        >
          <div className="flex flex-wrap gap-2">
            {data.most_awards.map((r) => (
              <Link
                key={r.player_identifier}
                to={`/${slug}/players/${r.player_identifier}`}
                className="flex items-center gap-2 rounded-lg border border-border-default bg-surface px-3 py-1.5 text-sm text-ink transition-colors hover:border-border-strong hover:bg-elevated"
              >
                <PlayerName name={r.player_name} countryCode={r.country_code ?? undefined} />
                <span className="tnum font-semibold text-analytic-ink">{r.awards}</span>
              </Link>
            ))}
          </div>
        </Panel>
      )}

      {knockouts.length > 0 && (
        <FixtureTable
          title="Knockout matches"
          blurb="Excluded from the table above, because a single-elimination match is not part of any group's record."
          fixtures={knockouts}
          slug={slug}
          showStage
        />
      )}

      <FixtureTable
        title={knockouts.length > 0 ? 'Group and league matches' : 'Every match held'}
        blurb="Scores come from the ball record, so they include extras and exclude any super over. A match with no score has no deliveries stored - those are ICC-sourced stand-ins, which carry a result and per-player figures but no balls."
        fixtures={groupGames.length > 0 ? groupGames : data.fixtures}
        slug={slug}
        showStage={groupGames.length === 0}
      />

      {data.venues.length > 0 && (
        <Panel title={`Venues (${data.venues.length})`}>
          <p className="text-sm leading-relaxed text-muted">{data.venues.join(' · ')}</p>
        </Panel>
      )}

      <Provenance>
        Champions are read from the match Cricsheet marks as the Final, never from whichever match
        happens to be last - which would be wrong wherever a third-place play-off follows it. A
        final tied and settled on a super over or boundary count records no winner at all in the
        source; the side that took the tiebreak is used instead, which is why England appear as 2019
        champions rather than nobody.
      </Provenance>
    </div>
  )
}

/** The points table, split by group where the edition had groups. */
function Standings({ data }: { data: TournamentEditionDetail }) {
  if (data.standings.length === 0) {
    return (
      <Panel title="Table">
        <EmptyState
          title="No table for this edition"
          hint="Every match held here is a knockout, so there is no group record to tabulate."
        />
      </Panel>
    )
  }

  const groups = Array.from(new Set(data.standings.map((r) => r.group)))
  const anyNrr = data.standings.some((r) => r.net_run_rate !== null)

  return (
    <Panel
      title="Table"
      blurb="Two points for a win, one for a tie or an abandoned match - the near-universal limited-overs convention, applied to the matches held. Not an official points table."
      bodyClassName="overflow-x-auto"
    >
      {data.standings_caveats.length > 0 && (
        <ul className="mb-3 space-y-1">
          {data.standings_caveats.map((c) => (
            <li key={c} className="text-xs leading-relaxed text-warning-ink">
              {c}
            </li>
          ))}
        </ul>
      )}

      {groups.map((group) => {
        const rows = data.standings.filter((r) => r.group === group)
        return (
          <div key={group ?? 'all'} className="mb-4 last:mb-0">
            {group && <h3 className="u-eyebrow mb-2">Group {group}</h3>}
            <table className={`${tableClass} min-w-[40rem]`}>
              <thead>
                <tr className={theadRowClass}>
                  <th className={thClass}>Side</th>
                  <th className={thNumClass}>P</th>
                  <th className={thNumClass}>W</th>
                  <th className={thNumClass}>L</th>
                  <th className={thNumClass} title="Matches that finished level">
                    T
                  </th>
                  <th className={thNumClass} title="Abandoned or no result">
                    NR
                  </th>
                  <th className={thNumClass}>Pts</th>
                  {anyNrr && (
                    <th
                      className={thNumClass}
                      title="Net run rate. A side bowled out is charged its full overs quota, not the overs it used."
                    >
                      NRR
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.team_id}-${r.group ?? ''}`} className={trClass}>
                    <td className={tdClass}>
                      <span className="flex items-center gap-2">
                        <Flag code={r.country_code} name={r.team_name} />
                        {r.team_name}
                      </span>
                    </td>
                    <td className={tdNumClass}>{r.played}</td>
                    <td className={tdNumClass}>{r.won}</td>
                    <td className={tdNumClass}>{r.lost}</td>
                    <td className={tdNumClass}>{r.tied || '-'}</td>
                    <td className={tdNumClass}>{r.no_result || '-'}</td>
                    <td className={tdNumStrongClass}>{r.points}</td>
                    {anyNrr && (
                      <td
                        className={`tnum px-3 py-2.5 text-right ${
                          (r.net_run_rate ?? 0) >= 0 ? 'text-positive-ink' : 'text-negative-ink'
                        }`}
                      >
                        {r.net_run_rate === null ? '-' : r.net_run_rate.toFixed(3)}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      })}
    </Panel>
  )
}

/** Fixtures, each linking to its own match page. */
function FixtureTable({
  title,
  blurb,
  fixtures,
  slug,
  showStage = false,
}: {
  title: string
  blurb: string
  fixtures: EditionFixture[]
  slug: string
  showStage?: boolean
}) {
  if (fixtures.length === 0) return null
  return (
    <Panel title={`${title} (${fixtures.length})`} blurb={blurb} bodyClassName="overflow-x-auto">
      <table className={`${tableClass} min-w-[52rem]`}>
        <thead>
          <tr className={theadRowClass}>
            <th className={thClass}>Date</th>
            {showStage && <th className={thClass}>Stage</th>}
            <th className={thClass}>Match</th>
            <th className={thClass}>Result</th>
            <th className={thClass}>Player of the match</th>
            <th className={thClass}>Venue</th>
          </tr>
        </thead>
        <tbody>
          {fixtures.map((f) => (
            <tr key={f.match_id} className={trClass}>
              <td className={`${tdNumClass} whitespace-nowrap`}>{f.match_date ?? '-'}</td>
              {showStage && (
                <td className={`${tdClass} whitespace-nowrap text-muted`}>
                  {f.stage ?? (f.group ? `Group ${f.group}` : '-')}
                </td>
              )}
              <td className={tdClass}>
                <Link
                  to={`/${slug}/matches/${encodeURIComponent(f.match_id)}`}
                  className="hover:text-analytic-ink"
                >
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className="flex items-center gap-1.5">
                      <Flag code={f.team1_code} name={f.team1_name ?? ''} />
                      {f.team1_name ?? 'TBC'}
                      {f.team1_score && (
                        <span className="tnum text-xs text-muted">{f.team1_score}</span>
                      )}
                    </span>
                    <span className="text-dim">v</span>
                    <span className="flex items-center gap-1.5">
                      <Flag code={f.team2_code} name={f.team2_name ?? ''} />
                      {f.team2_name ?? 'TBC'}
                      {f.team2_score && (
                        <span className="tnum text-xs text-muted">{f.team2_score}</span>
                      )}
                    </span>
                  </span>
                </Link>
              </td>
              <td className={`${tdClass} text-muted`}>{f.result_text}</td>
              <td className={tdClass}>
                {f.player_of_match_identifier ? (
                  <Link
                    to={`/${slug}/players/${f.player_of_match_identifier}`}
                    className="text-muted hover:text-analytic-ink"
                    title={f.player_of_match_scorecard ?? undefined}
                  >
                    {f.player_of_match}
                  </Link>
                ) : (
                  // The name is stored even when it does not resolve to one of
                  // our players, so it is shown unlinked rather than dropped.
                  <span className="text-muted">{f.player_of_match ?? '-'}</span>
                )}
              </td>
              <td className={`${tdClass} text-muted`}>{f.venue ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

/** A leaderboard, with the column set the discipline actually needs. */
function LeaderPanel({
  title,
  blurb,
  rows,
  slug,
  columns,
}: {
  title: string
  blurb: string
  rows: EditionLeader[]
  slug: string
  columns: [string, (r: EditionLeader) => string, boolean?][]
}) {
  return (
    <Panel title={title} blurb={blurb} bodyClassName="overflow-x-auto">
      {rows.length === 0 ? (
        <EmptyState title="Nothing recorded for this edition" />
      ) : (
        <table className={tableClass}>
          <thead>
            <tr className={theadRowClass}>
              <th className={thClass}>Player</th>
              {columns.map(([label]) => (
                <th key={label} className={thNumClass}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.player_identifier} className={trClass}>
                <td className={tdClass}>
                  <Link
                    to={`/${slug}/players/${r.player_identifier}`}
                    className="hover:text-analytic-ink"
                  >
                    <PlayerName name={r.player_name} countryCode={r.country_code ?? undefined} />
                  </Link>
                </td>
                {columns.map(([label, render, strong]) => (
                  <td key={label} className={strong ? tdNumStrongClass : tdNumClass}>
                    {render(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

export default TournamentEdition
