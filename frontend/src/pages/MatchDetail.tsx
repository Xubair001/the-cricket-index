import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { MatchDetail as MatchDetailType, MatchPerformer, TeamRef } from '../api/types'
import { CompetitionBadge } from '../components/CompetitionBadge'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Flag } from '../components/Flag'
import { useGender } from '../gender/useGender'
import { PlayerName } from '../components/PlayerName'
import { tableClass, theadRowClass, trClass } from '../components/ui'

/**
 * A single match, at the granularity this dataset actually holds.
 *
 * There is no scorecard here and there cannot be one: ingestion accumulates
 * per-player totals and discards the deliveries, so there is no batting order,
 * no fall of wickets and no innings sequence to render. What is shown is what
 * was derived - runs, balls, and bowling figures - and nothing is inferred to
 * fill the gap.
 */

function PerformerTable({
  performers,
  team,
  slug,
}: {
  performers: MatchPerformer[]
  team: TeamRef
  slug: string
}) {
  const teamPerformers = performers.filter((p) => p.team_id === team.team_id)
  return (
    <section className="rounded-xl border border-border-subtle bg-surface shadow-card">
      <h3 className="border-b border-border-subtle px-4 py-3 text-sm font-semibold text-ink">
        {team.name}
      </h3>
      {teamPerformers.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted">No per-player figures recorded for this side.</p>
      ) : (
        <div className="scroll-x">
          <table className={`${tableClass} min-w-[380px]`}>
            <thead>
              <tr className={theadRowClass}>
                <th className="px-4 py-2">Player</th>
                <th className="px-3 py-2 text-right">Runs</th>
                <th className="px-3 py-2 text-right">Balls</th>
                <th className="px-4 py-2 text-right">Bowling</th>
              </tr>
            </thead>
            <tbody>
              {teamPerformers.map((p) => (
                <tr
                  key={p.player_name}
                  className={trClass}
                >
                  <td className="px-4 py-2 text-ink">
                    <PlayerName
                      name={p.player_name}
                      country={p.country}
                      countryCode={p.country_code}
                      to={
                        p.player_identifier
                          ? `/${slug}/players/${p.player_identifier}`
                          : undefined
                      }
                    />
                  </td>
                  <td className="tnum px-3 py-2 text-right text-ink">
                    {p.runs_scored}
                    {/* Not out, in the scorecard sense: they faced deliveries and
                        were never dismissed in this match. */}
                    {p.dismissals === 0 && p.balls_faced > 0 ? '*' : ''}
                  </td>
                  <td className="tnum px-3 py-2 text-right text-muted">{p.balls_faced || '-'}</td>
                  <td className="tnum px-4 py-2 text-right text-muted">
                    {p.balls_bowled > 0 ? `${p.wickets_taken}/${p.runs_conceded}` : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function MatchDetail() {
  const { slug } = useGender()
  const { matchId = '' } = useParams()
  const [match, setMatch] = useState<MatchDetailType | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Guards against a slower request for a previous `matchId` resolving
    // after a newer one and overwriting it with the wrong match's data.
    let cancelled = false
    setMatch(null)
    setError(null)
    api
      .matchDetail(matchId)
      .then((res) => {
        if (!cancelled) setMatch(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [matchId])

  if (error) return <ErrorMessage message={error} />
  if (!match) return <LoadingSpinner />

  const margin = match.win_by_runs
    ? ` by ${match.win_by_runs} runs`
    : match.win_by_wickets
      ? ` by ${match.win_by_wickets} wickets`
      : ''

  // Cricsheet's venue string often already carries the city ("Queen's Park
  // Oval, Port of Spain, Trinidad"), so appending the city column unconditionally
  // reads as "…, Trinidad, Port of Spain". Only add it when it isn't there.
  const where = [
    match.venue,
    match.city && !match.venue?.toLowerCase().includes(match.city.toLowerCase())
      ? match.city
      : null,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/${slug}/matches`} className="text-sm text-muted transition-colors hover:text-ink">
          &larr; All matches
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <CompetitionBadge competition={match.competition_key} />
          <h1 className="flex flex-wrap items-center gap-2 u-display text-title text-ink">
            <Flag code={match.team1?.country_code} name={match.team1?.name} />
            {match.team1?.name} v {match.team2?.name}
            <Flag code={match.team2?.country_code} name={match.team2?.name} />
          </h1>
        </div>
        <p className="mt-1 text-sm text-muted">
          {match.event_name && `${match.event_name} · `}
          {where || 'Venue not recorded'}
          {match.match_date_start && <span className="tnum"> · {match.match_date_start}</span>}
        </p>
      </div>

      {/* The result is a recorded fact, not a verdict, so it carries no
          semantic colour - it earns its weight from size and position. */}
      <div className="rounded-xl border border-border-subtle bg-surface shadow-card p-4">
        <p className="text-lg font-semibold text-ink">
          {match.winner ? `${match.winner.name} won${margin}` : (match.outcome_result ?? 'Result unknown')}
        </p>
        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted">
          {match.toss_winner && (
            <p>
              Toss: {match.toss_winner.name} chose to {match.toss_decision}
            </p>
          )}
          {match.player_of_match && <p>Player of the match: {match.player_of_match}</p>}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {match.team1 && (
          <PerformerTable performers={match.performers} team={match.team1} slug={slug} />
        )}
        {match.team2 && (
          <PerformerTable performers={match.performers} team={match.team2} slug={slug} />
        )}
      </div>

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        These are per-match totals, not a scorecard. Batting order, fall of wickets and the sequence
        of innings need per-delivery records, which this pipeline aggregates and then discards. An
        asterisk means the player faced deliveries and was not dismissed.
      </p>
    </div>
  )
}
