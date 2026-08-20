import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { MatchSummary, TeamDetail as TeamDetailType } from '../api/types'
import { CompetitionBadge } from '../components/CompetitionBadge'
import { TeamStrengthPanel } from '../components/TeamStrength'
import { TeamWeaknessPanel } from '../components/TeamWeakness'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { StatCard } from '../components/StatCard'
import { Flag } from '../components/Flag'
import { useGender } from '../gender/useGender'
import { useScope } from '../scope/scope'
import { percent, rate } from '../format'
import { PlayerName } from '../components/PlayerName'
import {
  tableClass,
  tdClass,
  tdNumStrongClass,
  trClass,
} from '../components/ui'

/**
 * A team's record and its leading players.
 *
 * The leaderboards here are that player's figures *for this team*, not their
 * gender-wide career totals - the API scopes them by team_id, which is what
 * stops a franchise page crediting a player with their Test runs.
 */

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border-subtle bg-surface shadow-card">
      <h2 className="border-b border-border-subtle px-4 py-3 text-sm font-semibold text-ink">
        {title}
      </h2>
      {children}
    </section>
  )
}

/* The one place win/loss earns semantic colour: on a specific team's page the
 * result varies row to row, so the colour carries information. In the Teams
 * list it would tint a whole column uniformly and say nothing. */
function Result({ match, teamId }: { match: MatchSummary; teamId: number }) {
  if (!match.winner) {
    return <span className="text-muted">{match.outcome_result ?? 'No result'}</span>
  }
  const won = match.winner.team_id === teamId
  return (
    <span className={won ? 'text-positive-ink' : 'text-negative-ink'}>
      {won ? 'Won' : `Lost - ${match.winner.name}`}
    </span>
  )
}

export function TeamDetail() {
  const { slug } = useGender()
  const { teamId = '' } = useParams()
  const [team, setTeam] = useState<TeamDetailType | null>(null)
  const [error, setError] = useState<string | null>(null)

  // One competition for both team-intelligence panels. Phases are defined per
  // competition and Tests have none, so a Test-playing side must not default to
  // Tests or the weakness panel opens on something it cannot measure.
  const { competitions } = useScope()
  const phaseCompetitions = competitions.filter((c) => c.key !== 'tests')
  const [intelCompetition, setIntelCompetition] = useState('')
  useEffect(() => {
    if (!intelCompetition && phaseCompetitions.length) {
      setIntelCompetition(phaseCompetitions[0].key)
    }
  }, [phaseCompetitions, intelCompetition])

  useEffect(() => {
    // Guards against a slower request for a previous team resolving after
    // a newer one and overwriting it with the wrong team's data.
    let cancelled = false
    setTeam(null)
    setError(null)
    api
      .teamDetail(Number(teamId))
      .then((res) => {
        if (!cancelled) setTeam(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [teamId])

  if (error) return <ErrorMessage message={error} />
  if (!team) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/${slug}/teams`} className="text-sm text-muted transition-colors hover:text-ink">
          &larr; All teams
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Flag code={team.country_code} name={team.name} className="text-2xl" />
          <h1 className="u-display text-title text-ink">{team.name}</h1>
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">
            {team.team_type}
          </span>
        </div>
        {/* This page is the side's whole record; the squad view is the same
            side over its recent matches only, which is a different question. */}
        <Link
          to={`/${slug}/teams/squad?team=${team.team_id}`}
          className="mt-2 inline-block text-sm text-analytic-ink hover:underline"
        >
          Squad analysis &rarr;
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Matches" value={team.matches.toLocaleString()} />
        <StatCard label="Won" value={team.wins} />
        <StatCard label="Lost" value={team.losses} />
        <StatCard
          label="Win %"
          value={percent(team.win_pct)}
          subtext="Decided matches only"
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Leading Run Scorers">
          {team.top_run_scorers.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted">No batting records for this team.</p>
          ) : (
            <table className={tableClass}>
              <tbody>
                {team.top_run_scorers.map((p) => (
                  <tr
                    key={p.player_identifier ?? p.player_name}
                    className={trClass}
                  >
                    <td className="px-4 py-2.5">
                      <PlayerName
                        name={p.player_name}
                        country={p.country}
                        countryCode={p.country_code}
                        to={
                          p.player_identifier
                            ? `/${slug}/players/${p.player_identifier}`
                            : undefined
                        }
                        nameClassName="font-medium"
                      />
                    </td>
                    <td className={tdNumStrongClass}>
                      {p.runs.toLocaleString()}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right text-muted">avg {rate(p.average)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title="Leading Wicket Takers">
          {team.top_wicket_takers.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted">No bowling records for this team.</p>
          ) : (
            <table className={tableClass}>
              <tbody>
                {team.top_wicket_takers.map((p) => (
                  <tr
                    key={p.player_identifier ?? p.player_name}
                    className={trClass}
                  >
                    <td className="px-4 py-2.5">
                      <PlayerName
                        name={p.player_name}
                        country={p.country}
                        countryCode={p.country_code}
                        to={
                          p.player_identifier
                            ? `/${slug}/players/${p.player_identifier}`
                            : undefined
                        }
                        nameClassName="font-medium"
                      />
                    </td>
                    <td className={tdNumStrongClass}>
                      {p.wickets}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right text-muted">avg {rate(p.average)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      {/* Section 19 pairs these two: strength says where the side is deep,
          weakness says what has declined against its own past. Strength first,
          because a reader needs the shape of the side before the change in it.

          ONE competition selector drives both. Each panel owning its own put two
          dropdowns on the page and let them disagree, so a reader saw depth over
          all international cricket beside a decline measured in T20Is. Phases
          are defined per competition and Tests have none, so the default is the
          richest competition that has them. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="u-eyebrow">Team intelligence</h2>
        <label className="flex items-center gap-2">
          <span className="u-eyebrow">Competition</span>
          <select
            value={intelCompetition}
            onChange={(e) => setIntelCompetition(e.target.value)}
            className="rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink"
          >
            {phaseCompetitions.map((c) => (
              <option key={c.key} value={c.key}>
                {c.display_name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <TeamStrengthPanel teamId={team.team_id} competition={intelCompetition || undefined} />

      <TeamWeaknessPanel teamId={team.team_id} competition={intelCompetition} />

      <Panel title="Recent Matches">
        {team.recent_matches.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted">No matches recorded for this team.</p>
        ) : (
          <div className="scroll-x">
            <table className={`${tableClass} min-w-[640px]`}>
              <tbody>
                {team.recent_matches.map((m) => (
                  <tr
                    key={m.match_id}
                    className={trClass}
                  >
                    <td className="px-4 py-2.5">
                      <CompetitionBadge competition={m.competition_key} />
                    </td>
                    <td className="tnum px-3 py-2.5 text-muted">{m.match_date_start ?? '-'}</td>
                    <td className={tdClass}>
                      <Link to={`/${slug}/matches/${m.match_id}`} className="text-ink hover:text-analytic-ink">
                        <Flag code={m.team1?.country_code} name={m.team1?.name} />{' '}
                        {m.team1?.name} v {m.team2?.name}{' '}
                        <Flag code={m.team2?.country_code} name={m.team2?.name} />
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Result match={m} teamId={team.team_id} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        Run and wicket leaders are scoped to this team, not to the player's whole career - a
        franchise page shows what a player did for that franchise. Squad composition and role
        balance are on the squad analysis page, derived from each player's share of deliveries in
        the side's own recent window - this footnote said they needed data the dataset did not
        store, which stopped being true when deliveries landed.
      </p>
    </div>
  )
}
