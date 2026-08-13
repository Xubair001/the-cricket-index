import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { FormVerdict, PlayerDetail as PlayerDetailType } from '../api/types'
import FormVerdictCard from '../components/FormVerdictCard'
import { CompetitionBadge } from '../components/CompetitionBadge'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { PlayerAvatar } from '../components/PlayerAvatar'
import { StatusBadge } from '../components/StatusBadge'
import { useGender } from '../gender/useGender'
import { rate } from '../format'

const sectionLabel = 'font-mono text-[10px] uppercase tracking-[0.1em] text-muted'

export function PlayerDetail() {
  const { slug } = useGender()
  const { identifier = '' } = useParams()
  const [player, setPlayer] = useState<PlayerDetailType | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<FormVerdict | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    // Guards against a slower request for a previous `identifier` resolving
    // after a newer one and overwriting it with the wrong player's data.
    let cancelled = false
    setPlayer(null)
    setError(null)
    api
      .playerDetail(identifier)
      .then((res) => {
        if (!cancelled) setPlayer(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [identifier])

  // Fetched separately from the profile so a slow form computation never holds
  // up the page, and so a failure here degrades to "form unavailable" rather
  // than taking the whole profile down with it.
  useEffect(() => {
    let cancelled = false
    setForm(null)
    setFormError(null)
    api
      .playerForm(identifier, { competition_type: 'international' })
      .then((res) => {
        if (!cancelled) setForm(res)
      })
      .catch((e) => {
        if (!cancelled) setFormError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [identifier])

  if (error) return <ErrorMessage message={error} />
  if (!player) return <LoadingSpinner />

  const bio = player.bio
  const hasAnyBio = bio.date_of_birth || bio.birth_place || bio.nationality

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/${slug}/players`} className="text-sm text-muted transition-colors hover:text-ink">
          &larr; All players
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-4">
          <PlayerAvatar src={player.bio.image_url} alt={player.name} />
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">{player.name}</h1>
            <StatusBadge status={player.status} />
            {/* Both name forms are shown when they differ: the scorecard form is
                the one a cricket source will use, and it is not stale data. */}
            {player.scorecard_name && player.scorecard_name !== player.name && (
              <span
                className="text-sm text-dim"
                title="How the name appears on a scorecard (all initials, then surname)"
              >
                {player.scorecard_name}
              </span>
            )}
          </div>
        </div>
        <p className="mt-1 text-sm text-muted">{player.teams.map((t) => t.name).join(', ')}</p>
        <Link
          to={`/${slug}/compare?a=${player.identifier}`}
          className="mt-2 inline-block text-sm text-analytic hover:underline"
        >
          Compare with another player &rarr;
        </Link>
      </div>

      {/* Form sits above the career record deliberately: Rule 3 treats "how is
          this player going now" as a different question from "what have they
          done", and it is the one a selector opens the page to answer. */}
      {formError ? (
        <p className="text-sm text-muted">Form unavailable: {formError}</p>
      ) : form ? (
        <FormVerdictCard verdict={form} scopeLabel="international cricket" />
      ) : (
        <div className="h-36 animate-pulse rounded-lg border border-border-default bg-surface" />
      )}

      <section className="rounded-lg border border-border-default bg-surface p-4">
        <h3 className={`mb-3 ${sectionLabel}`}>Bio</h3>
        {hasAnyBio ? (
          <dl className="grid grid-cols-2 gap-y-3 text-sm sm:grid-cols-3">
            <BioPair label="Date of birth" value={bio.date_of_birth} />
            <BioPair label="Birthplace" value={bio.birth_place} />
            <BioPair label="Nationality" value={bio.nationality} />
          </dl>
        ) : (
          /* Bio coverage is partial by source, not by omission — around 4 in 10
             players have any of these. Nothing here is ever inferred. */
          <p className="text-sm text-dim">Not available for this player.</p>
        )}
      </section>

      {player.icc_rankings.length > 0 && (
        <section className="rounded-lg border border-border-default bg-surface p-4">
          <h3 className={`mb-3 ${sectionLabel}`}>Current ICC Ranking</h3>
          <div className="flex flex-wrap gap-3 text-sm">
            {player.icc_rankings.map((r) => (
              <div
                key={r.rank_type}
                className="rounded-md border border-border-default bg-elevated px-3 py-2"
              >
                <div className="font-semibold text-ink">
                  <span className="tnum">#{r.position}</span>{' '}
                  <span className="font-normal text-muted">{r.rank_type.replace('-', ' ')}</span>
                </div>
                <div className="tnum mt-0.5 text-xs text-dim">
                  {r.points ?? '—'} rating &middot; published {r.rank_date}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-dim">
            Published by the ICC — not computed here.
          </p>
        </section>
      )}

      <div className="space-y-4">
        {player.by_competition.map((c) => (
          <section key={c.competition_key} className="rounded-lg border border-border-default bg-surface">
            <div className="flex items-center gap-2 border-b border-border-subtle px-4 py-3">
              <CompetitionBadge competition={c.competition_key} />
              <span className="tnum text-sm text-muted">{c.matches} matches</span>
            </div>
            <div className="grid grid-cols-1 divide-y divide-border-subtle sm:grid-cols-2 sm:divide-x sm:divide-y-0">
              <div className="p-4">
                <h3 className={`mb-3 ${sectionLabel}`}>Batting</h3>
                <dl className="grid grid-cols-2 gap-y-3 text-sm sm:grid-cols-3">
                  <StatPair label="Runs" value={c.runs.toLocaleString()} />
                  <StatPair label="Average" value={rate(c.batting_average)} />
                  <StatPair label="Strike rate" value={rate(c.strike_rate)} />
                  <StatPair label="Balls faced" value={c.balls_faced.toLocaleString()} />
                  <StatPair label="4s" value={c.fours} />
                  <StatPair label="6s" value={c.sixes} />
                </dl>
              </div>
              <div className="p-4">
                <h3 className={`mb-3 ${sectionLabel}`}>Bowling</h3>
                {c.wickets > 0 || c.balls_bowled > 0 ? (
                  <dl className="grid grid-cols-2 gap-y-3 text-sm sm:grid-cols-3">
                    <StatPair label="Wickets" value={c.wickets} />
                    <StatPair label="Average" value={rate(c.bowling_average)} />
                    <StatPair label="Economy" value={rate(c.economy)} />
                    <StatPair label="Runs conceded" value={c.runs_conceded.toLocaleString()} />
                  </dl>
                ) : (
                  <p className="text-sm text-dim">Did not bowl</p>
                )}
              </div>
            </div>
          </section>
        ))}
      </div>

      <section className="rounded-lg border border-border-default bg-surface">
        <h2 className="border-b border-border-subtle px-4 py-3 text-sm font-semibold text-ink">
          Recent Matches
        </h2>
        {player.recent_matches.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted">No matches recorded for this player.</p>
        ) : (
          <div className="scroll-x">
            <table className="w-full min-w-[640px] text-sm">
              <tbody>
                {player.recent_matches.map((m) => (
                  <tr
                    key={m.match_id}
                    className="border-b border-border-subtle last:border-0 hover:bg-elevated"
                  >
                    <td className="px-4 py-2.5">
                      <CompetitionBadge competition={m.competition_key} />
                    </td>
                    <td className="tnum px-3 py-2.5 text-muted">{m.match_date_start ?? '—'}</td>
                    <td className="px-3 py-2.5">
                      <Link to={`/${slug}/matches/${m.match_id}`} className="text-ink hover:text-analytic">
                        {m.team1?.name} v {m.team2?.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-right text-muted">
                      {m.winner ? `${m.winner.name} won` : (m.outcome_result ?? '—')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        Career figures are kept separate by competition and never summed across international and
        franchise cricket. Batting average divides runs by dismissals rather than by innings, which
        is why a Test average here matches the published one.
      </p>
    </div>
  )
}

function StatPair({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="tnum font-semibold text-ink">{value}</dd>
    </div>
  )
}

function BioPair({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      {/* "Not available" is a statement about the source, never a guess. */}
      <dd className={value ? 'font-semibold text-ink' : 'text-dim'}>{value ?? 'Not available'}</dd>
    </div>
  )
}
