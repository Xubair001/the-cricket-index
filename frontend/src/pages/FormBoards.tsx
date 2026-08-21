import { useEffect, useState } from 'react'
import { ActionLink } from '../components/ActionLink'

import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useFilters } from '../state/useFilters'
import type { FormLeaderRow, FormLeaderboard } from '../api/types'
import { ErrorMessage, SkeletonRows } from '../components/LoadingSpinner'
import { change, score } from '../format'
import { Pagination } from '../components/Pagination'
import { ParMeter } from '../components/ParMeter'
import { PlayerName } from '../components/PlayerName'
import { useGender } from '../gender/useGender'
import { useScopedCompetition } from '../scope/scope'
import {
  EmptyState,
  fieldClass,
  fieldLabelClass,
  PageHeader,
  Panel,
  Provenance,
  tableClass,
  tdClass,
  tdNumClass,
  thClass,
  theadRowClass,
  thNumClass,
  trClass,
  Uncertain,
} from '../components/ui'

/**
 * The form boards (§7 - In Form, Rising Players).
 *
 * One page serves every board for the same reason the Explorer serves three
 * metric sets: they share a filter model and a reading. Splitting them into
 * separate files is how two views of one engine drift into disagreeing about
 * what "in form" means.
 *
 * The home page shows the top six of three of these. This is the full board -
 * paginated, scoped, and with the evidence each verdict rests on visible in the
 * row rather than in a tooltip.
 *
 * The column that matters most is the par meter, not the percentage. Form is
 * self-relative, so a player who was dreadful and is now merely below average
 * posts a large percentage; the meter is what stops that reading as good. The
 * server orders on par units gained for the same reason.
 */

const LIMIT = 25

type Board = {
  slug: string
  label: string
  /** API params - a board is either a state or a trend, never both. */
  query: { state?: string; trend?: string }
  blurb: string
  tone: 'positive' | 'negative'
}

const BOARDS: Board[] = [
  {
    slug: 'in-form',
    label: 'In Form',
    query: { state: 'in_form' },
    blurb:
      'Furthest above their own preceding baseline, weighted by how much cricket the verdict rests on.',
    tone: 'positive',
  },
  {
    slug: 'rising',
    label: 'Rising',
    query: { trend: 'rising' },
    blurb:
      'Improving within their current run - the direction is upward, which is a different claim from being above baseline.',
    tone: 'positive',
  },
  {
    slug: 'improving',
    label: 'Improving',
    query: { state: 'improving' },
    blurb: 'Above their baseline, but by less than the in-form band requires.',
    tone: 'positive',
  },
  {
    slug: 'declining',
    label: 'Declining',
    query: { state: 'declining' },
    blurb: 'Below their own baseline, though not yet by the margin that reads as out of form.',
    tone: 'negative',
  },
  {
    slug: 'losing-form',
    label: 'Losing Form',
    query: { state: 'out_of_form' },
    blurb: 'Furthest below their own baseline. A drop here is relative to the player, not to peers.',
    tone: 'negative',
  },
]

const TREND_GLYPH: Record<FormLeaderRow['trend'], { glyph: string; tone: string; note: string }> = {
  rising: { glyph: '\u2197', tone: 'text-positive-ink', note: 'Improving within the recent window' },
  flat: { glyph: '\u2192', tone: 'text-dim', note: 'Level within the recent window' },
  falling: { glyph: '\u2198', tone: 'text-negative-ink', note: 'Declining within the recent window' },
  unknown: { glyph: '·', tone: 'text-dim', note: 'Not enough cricket to read a trend' },
}

/** Confidence below this is the product saying "thin sample". */
const THIN_CONFIDENCE = 0.6

export function FormBoards() {
  const { slug, apiGender } = useGender()
  const { board: boardSlug = 'in-form' } = useParams<{ board: string }>()
  const board = BOARDS.find((b) => b.slug === boardSlug) ?? BOARDS[0]
  const f = useFilters()
  const { keep, set: update } = f

  const requestedCompetition = f.get('competition')
  // The scope switch owns which family is in play. A competition from the other
  // family is dropped rather than sent, so the figures on screen always match
  // the heading above them.
  const {
    competition,
    competitionType,
    options: competitionOptions,
  } = useScopedCompetition(requestedCompetition)
  const offset = f.int('offset', 0)

  const [data, setData] = useState<FormLeaderboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)


  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .formLeaderboard(apiGender, {
        ...board.query,
        competition: competition || undefined,
        competition_type: competitionType,
        limit: LIMIT,
        offset,
      })
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // `board` is a stable module-level object - `find` returns the same
    // identity for a given slug - so depending on it is both correct and what
    // the effect actually reads.
  }, [apiGender, board, competition, competitionType, offset])

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Discover"
        title={board.label}
        blurb="Form measures change against a player's own recent baseline - not standard. For who is playing the best cricket outright, see the Performance Index."
        actions={
          <ActionLink to={`/${slug}/performance-index`} weight="secondary">Performance Index</ActionLink>
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="inline-flex flex-wrap rounded-xl border border-border-subtle bg-surface p-0.5 shadow-card">
          {BOARDS.map((b) => (
            <Link
              key={b.slug}
              to={`/${slug}/form/${b.slug}${competition ? `?competition=${competition}` : ''}`}
              className={
                'rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors ' +
                (b.slug === board.slug ? 'bg-elevated text-ink' : 'text-muted hover:text-ink')
              }
            >
              {b.label}
            </Link>
          ))}
        </div>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Scope</span>
          <select
            value={competition}
            onChange={(e) => update({ competition: e.target.value })}
            className={fieldClass}
          >
            {competitionOptions.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <ErrorMessage message={error} />}

      <Panel
        title={board.label}
        blurb={board.blurb}
        aside={
          data && (
            <span className="tnum text-xs text-muted">
              {data.total.toLocaleString()} qualifying
            </span>
          )
        }
        bodyClassName=""
      >
        <div className="scroll-x">
          <table className={`${tableClass} min-w-[760px]`}>
            <thead>
              <tr className={theadRowClass}>
                <th className={thClass}>#</th>
                <th className={thClass}>Player</th>
                <th className={thClass}>Standard</th>
                <th className={thNumClass}>Level</th>
                <th className={thNumClass} title="0-100. Percentile of the evidence-weighted move within this scope. Bounded, and ordered the same way this board is.">
                  Form score
                </th>
                <th className={thNumClass}>Change</th>
                <th className={thClass}>Trend</th>
                <th className={thNumClass}>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {loading && !data ? (
                <tr>
                  <td colSpan={8} className="p-4">
                    <SkeletonRows rows={8} />
                  </td>
                </tr>
              ) : (
                data?.items.map((r, i) => {
                  const thin = r.confidence < THIN_CONFIDENCE
                  const belowPar = (r.recent_mean ?? 0) < 1
                  // The API words this so it is never a percentage over 100: a
                  // ratio against a player's own baseline has no ceiling, and
                  // past a doubling it is stated as a multiple instead.
                  const delta = r.delta_display ?? change(r.delta_percent)
                  const trend = TREND_GLYPH[r.trend]
                  const evidence = `${r.recent_matches} recent vs ${r.baseline_matches} earlier matches`

                  return (
                    <tr key={r.player_identifier} className={trClass}>
                      <td className={`${tdNumClass} text-dim`}>{offset + i + 1}</td>
                      <td className={tdClass}>
                        <PlayerName
                          name={r.player_name}
                          country={r.country}
                          countryCode={r.country_code}
                          to={`/${slug}/players/${r.player_identifier}`}
                          nameClassName="font-medium"
                        />
                      </td>
                      {/* The absolute standard, drawn against par. This is the
                          column that distinguishes "improved to excellent" from
                          "improved to still below average" - the percentage
                          beside it cannot. */}
                      <td className="px-3 py-2.5">
                        <ParMeter value={r.recent_mean} className="w-24" label={r.player_name} />
                      </td>
                      <td
                        className={`${tdNumClass} ${belowPar ? 'text-negative-ink' : 'text-ink'}`}
                        title={
                          r.recent_mean === null
                            ? undefined
                            : `${r.recent_mean.toFixed(2)}x an average appearance${
                                belowPar ? ' - still below par' : ''
                              }`
                        }
                      >
                        {r.recent_mean !== null ? `${r.recent_mean.toFixed(2)}x` : '-'}
                      </td>
                      {/* The headline figure. Bounded 0-100 and percentiled on
                          the same quantity this board sorts by, so it cannot
                          disagree with the row order the way the raw percentage
                          beside it did. */}
                      <td className={`${tdNumClass} font-semibold text-ink`}>
                        {r.form_score === null ? (
                          '-'
                        ) : thin ? (
                          <Uncertain reason={`Confidence ${Math.round(r.confidence * 100)}% - ${evidence}`}>
                            {score(r.form_score)}
                          </Uncertain>
                        ) : (
                          score(r.form_score)
                        )}
                      </td>
                      <td
                        className={`tnum px-3 py-2.5 text-right ${
                          board.tone === 'positive' ? 'text-positive-ink' : 'text-negative-ink'
                        }`}
                      >
                        {thin ? (
                          <Uncertain reason={`Confidence ${Math.round(r.confidence * 100)}% - ${evidence}`}>
                            {delta}
                          </Uncertain>
                        ) : (
                          delta
                        )}
                      </td>
                      <td className={`${tdClass} ${trend.tone}`} title={trend.note}>
                        {trend.glyph}
                        <span className="sr-only">{trend.note}</span>
                      </td>
                      <td className={tdNumClass} title={r.explanation}>
                        {r.recent_matches}/{r.baseline_matches}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {data && data.items.length === 0 && !loading && (
          <div className="p-4">
            <EmptyState
              title="Nobody meets the evidence threshold here"
              hint="A verdict needs a recent window and an earlier baseline to compare it against. Try widening the scope."
            />
          </div>
        )}

        {data && data.total > LIMIT && (
          <div className="px-4">
            <Pagination
              total={data.total}
              limit={LIMIT}
              offset={offset}
              onChange={(o) => keep({ offset: String(o) })}
            />
          </div>
        )}
      </Panel>

      <Provenance>
        Each player is compared with their own preceding twelve months in this scope, never with
        other players - that is what makes "in form" mean <em>changed</em> rather than{' '}
        <em>good</em>. The <strong className="font-semibold text-muted">form score</strong> is a
        percentile, out of 100, of the par units gained against that baseline, weighted by how much
        cricket the verdict rests on. The change is shown beside it, as a multiple past a doubling.
        Every performance is scaled by the strength of the side it came against. Internationals and
        franchise cricket are never blended. A figure with a dotted rule rests on a thin sample.
      </Provenance>
    </div>
  )
}
