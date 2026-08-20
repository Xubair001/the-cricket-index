import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { TournamentDetail as Detail, TournamentEdition } from '../api/types'
import { useGender } from '../gender/useGender'
import { useScope } from '../scope/scope'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { PlayerName } from '../components/PlayerName'
import { count, rate } from '../format'
import {
  Panel,
  PageHeader,
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

/**
 * One tournament: every edition, who won it, and who scored the runs.
 *
 * The honesty problem this page has to solve is coverage. Cricsheet does not
 * hold every match of every edition - the 2019 men's World Cup was 48 matches
 * and this database has 36 - so an edition with no champion shown is almost
 * always an edition whose FINAL is missing, not an edition nobody won. The
 * distinction is carried by `has_final` and stated in the row rather than left
 * as an empty cell.
 */

function EditionRow({ e, slug }: { e: TournamentEdition; slug: string }) {
  return (
    <tr className={trClass}>
      <td className={`${tdClass} whitespace-nowrap font-medium`}>{e.season ?? '-'}</td>
      <td className={tdClass}>
        {e.winner_name ? (
          <span className="font-medium text-ink">{e.winner_name}</span>
        ) : e.has_final ? (
          <span className="text-dim" title="The final is held but records no winner">
            unknown
          </span>
        ) : (
          // Not "-". An empty cell reads as "nobody won", which is false; this
          // says which fact is missing.
          <span className="text-dim" title="This dataset does not hold the deciding match">
            final not held here
          </span>
        )}
        {e.decided_by_tiebreak && (
          <span
            className="ml-2 rounded bg-elevated px-1.5 py-0.5 align-middle font-mono text-[9px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
            title="The final was tied. Cricsheet records no winner for a tie, so the champion comes from the side that took the super over or boundary count."
          >
            tiebreak
          </span>
        )}
      </td>
      <td className={`${tdClass} text-muted`}>{e.runner_up_name ?? '-'}</td>
      <td className={tdNumClass}>{count(e.sides)}</td>
      <td className={tdNumClass}>{count(e.matches)}</td>
      <td className={`${tdClass} whitespace-nowrap text-xs text-dim`}>
        {e.first_date ? (
          <Link
            to={`/${slug}/matches?search=${encodeURIComponent(e.season ?? '')}`}
            className="hover:text-analytic-ink"
          >
            {e.first_date}
          </Link>
        ) : (
          '-'
        )}
      </td>
    </tr>
  )
}

export function TournamentDetail() {
  const { slug, apiGender } = useGender()
  const { tournament: tournamentSlug } = useParams<{ tournament: string }>()
  const { competitionType } = useScope()
  const [data, setData] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!tournamentSlug) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .tournament(tournamentSlug, apiGender, { competition_type: competitionType })
      .then((res) => !cancelled && setData(res))
      .catch((e: Error) => !cancelled && (setError(e.message), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [tournamentSlug, apiGender, competitionType])

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorMessage message={error} />
  if (!data) return <ErrorMessage message="Tournament not found" />

  const withFinal = data.editions_detail.filter((e) => e.has_final).length

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/${slug}/tournaments`} className="text-xs text-muted hover:text-ink">
          ← All tournaments
        </Link>
      </div>

      <PageHeader
        eyebrow={`${data.competition_name} · ${data.is_icc ? 'ICC event' : 'tournament'}`}
        title={data.name}
        blurb={
          <>
            {count(data.editions)} edition{data.editions === 1 ? '' : 's'} held here,{' '}
            {count(data.matches)} matches, {count(data.sides)} sides
            {data.first_date && data.last_date && (
              <>
                {' '}
                · {data.first_date.slice(0, 4)} to {data.last_date.slice(0, 4)}
              </>
            )}
            .
          </>
        }
      />

      {data.most_titles.length > 0 && (
        <Panel
          title="Champions"
          blurb={`Counted only from the ${withFinal} edition${
            withFinal === 1 ? '' : 's'
          } whose final this dataset holds, so this is not a complete honours list.`}
        >
          <div className="flex flex-wrap gap-2">
            {data.most_titles.map((t) => (
              <span
                key={t.team}
                className="rounded-lg border border-border-default bg-surface px-3 py-1.5 text-sm text-ink"
              >
                {t.team}
                <span className="tnum ml-2 font-semibold text-analytic-ink">{t.titles}</span>
              </span>
            ))}
          </div>
        </Panel>
      )}

      <Panel title="Editions" bodyClassName="overflow-x-auto">
        <table className={`${tableClass} min-w-[44rem]`}>
          <thead>
            <tr className={theadRowClass}>
              <th className={thClass}>Season</th>
              <th className={thClass}>Champion</th>
              <th className={thClass}>Runner-up</th>
              <th className={thNumClass}>Sides</th>
              <th className={thNumClass}>Matches</th>
              <th className={thClass}>From</th>
            </tr>
          </thead>
          <tbody>
            {data.editions_detail.map((e) => (
              <EditionRow key={e.season ?? String(e.first_date)} e={e} slug={slug} />
            ))}
          </tbody>
        </table>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel
          title="Leading run-scorers"
          blurb="Across every edition held here. Conventional totals, deliberately not adjusted for opposition strength - a tournament's leading scorer is a published figure and a weighted version would match no source."
          bodyClassName="overflow-x-auto"
        >
          <table className={tableClass}>
            <thead>
              <tr className={theadRowClass}>
                <th className={thClass}>Player</th>
                <th className={thNumClass}>M</th>
                <th className={thNumClass}>Runs</th>
                <th className={thNumClass}>Avg</th>
              </tr>
            </thead>
            <tbody>
              {data.top_run_scorers.map((r) => (
                <tr key={r.player_identifier} className={trClass}>
                  <td className={tdClass}>
                    <Link
                      to={`/${slug}/players/${r.player_identifier}`}
                      className="hover:text-analytic-ink"
                    >
                      <PlayerName name={r.player_name} />
                    </Link>
                  </td>
                  <td className={tdNumClass}>{count(r.matches)}</td>
                  <td className={tdNumStrongClass}>{count(r.runs)}</td>
                  <td className={tdNumClass}>{rate(r.average)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel
          title="Leading wicket-takers"
          blurb="Across every edition held here, on the same basis."
          bodyClassName="overflow-x-auto"
        >
          <table className={tableClass}>
            <thead>
              <tr className={theadRowClass}>
                <th className={thClass}>Player</th>
                <th className={thNumClass}>M</th>
                <th className={thNumClass}>Wkts</th>
              </tr>
            </thead>
            <tbody>
              {data.top_wicket_takers.map((r) => (
                <tr key={r.player_identifier} className={trClass}>
                  <td className={tdClass}>
                    <Link
                      to={`/${slug}/players/${r.player_identifier}`}
                      className="hover:text-analytic-ink"
                    >
                      <PlayerName name={r.player_name} />
                    </Link>
                  </td>
                  <td className={tdNumClass}>{count(r.matches)}</td>
                  <td className={tdNumStrongClass}>{count(r.wickets)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      {/* What the page cannot tell you, in its own panel rather than as a
          footnote - a missing champion is a fact about coverage and a reader
          deciding whether to trust the honours list needs it at the same
          weight as the list. */}
      {data.notes.length > 0 && (
        <Panel title="What this does not cover">
          <ul className="space-y-2">
            {data.notes.map((n, i) => (
              <li key={i} className="text-sm leading-relaxed text-muted">
                {n}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Provenance>
        A champion is read from the match Cricsheet marks as the Final, never inferred from
        whichever match happens to be last - a third-place play-off is often played after it, and
        coverage of an edition is frequently partial. A tied final has no winner in the source at
        all: Cricsheet records the 2019 World Cup final as a tie with England as the eliminator, so
        the champion comes from there and the row is marked. Runs and wickets are conventional
        totals over the matches held, not opposition-adjusted, so they can be checked against a
        published source.
      </Provenance>
    </div>
  )
}
