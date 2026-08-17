import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { FormLeaderRow, FormLeaderboard } from '../api/types'
import { ErrorMessage, SkeletonRows } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { ParMeter } from '../components/ParMeter'
import { PlayerName } from '../components/PlayerName'
import { useGender } from '../gender/useGender'
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
  thClass,
  thNumClass,
  theadRowClass,
  trClass,
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

const COMPETITIONS = [
  { value: '', label: 'All Internationals' },
  { value: 'tests', label: 'Tests' },
  { value: 'odis', label: 'ODIs' },
  { value: 't20is', label: 'T20Is' },
  { value: 'psl', label: 'PSL' },
]

const TREND_GLYPH: Record<FormLeaderRow['trend'], { glyph: string; tone: string; note: string }> = {
  rising: { glyph: '↗', tone: 'text-positive-ink', note: 'Improving within the recent window' },
  flat: { glyph: '→', tone: 'text-dim', note: 'Level within the recent window' },
  falling: { glyph: '↘', tone: 'text-negative-ink', note: 'Declining within the recent window' },
  unknown: { glyph: '·', tone: 'text-dim', note: 'Not enough cricket to read a trend' },
}

/** Confidence below this is the product saying "thin sample". */
const THIN_CONFIDENCE = 0.6

export function FormBoards() {
  const { slug, apiGender } = useGender()
  const { board: boardSlug = 'in-form' } = useParams<{ board: string }>()
  const board = BOARDS.find((b) => b.slug === boardSlug) ?? BOARDS[0]
  const [params, setParams] = useSearchParams()

  const competition = params.get('competition') ?? ''
  const offset = Number(params.get('offset') ?? 0)

  const [data, setData] = useState<FormLeaderboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  function update(next: Record<string, string>, keepOffset = false) {
    const merged = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v)
      else merged.delete(k)
    }
    if (!keepOffset) merged.delete('offset')
    setParams(merged, { replace: true })
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .formLeaderboard(apiGender, {
        ...board.query,
        competition: competition || undefined,
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
  }, [apiGender, board, competition, offset])

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Discover"
        title={board.label}
        blurb="Form measures change against a player's own recent baseline - not standard. For who is playing the best cricket outright, see the Performance Index."
        actions={
          <Link
            to={`/${slug}/performance-index`}
            className="text-sm text-analytic-ink hover:underline"
          >
            Performance Index →
          </Link>
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
            {COMPETITIONS.map((c) => (
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
                <th className={thNumClass}>Change</th>
                <th className={thClass}>Trend</th>
                <th className={thNumClass}>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {loading && !data ? (
                <tr>
                  <td colSpan={7} className="p-4">
                    <SkeletonRows rows={8} />
                  </td>
                </tr>
              ) : (
                data?.items.map((r, i) => {
                  const thin = r.confidence < THIN_CONFIDENCE
                  const belowPar = (r.recent_mean ?? 0) < 1
                  const delta =
                    r.delta_percent !== null
                      ? `${r.delta_percent > 0 ? '+' : ''}${r.delta_percent.toFixed(0)}%`
                      : '-'
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
                      <td
                        className={`tnum px-3 py-2.5 text-right font-semibold ${
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
              onChange={(o) => update({ offset: String(o) }, true)}
            />
          </div>
        )}
      </Panel>

      <Provenance>
        Each player is compared with their own preceding twelve months in this scope, never with
        other players - that is what makes “in form” mean <em>changed</em> rather than{' '}
        <em>good</em>. Boards are ordered on par units gained rather than on the percentage,
        because a player improving from poor to below-average can post a bigger percentage than one
        playing the best cricket in the world. Every performance is weighted by the strength of the
        side it came against, fitted per era. Internationals and franchise cricket are never blended
        into one figure. The last column is the evidence the verdict rests on - recent matches
        against earlier ones - and a change marked with a dotted rule rests on a thin sample.
      </Provenance>
    </div>
  )
}
