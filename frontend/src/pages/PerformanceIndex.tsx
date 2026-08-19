import { Fragment, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { IndexRow, PerformanceIndexPage } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'
import { useScopedCompetition } from '../scope/scope'
import { PlayerName } from '../components/PlayerName'
import {
  tableClass,
  tdClass,
  tdNumClass,
  thClass,
  theadRowClass,
  trClass,
} from '../components/ui'

/**
 * The Performance Index (§14).
 *
 * §30 is the governing requirement here: "Rating 87" is incomplete until the
 * user can see the components that produced 87. So no score renders without its
 * decomposition one click away, and the page states up front which components
 * are missing and why - a rating that quietly omits a quarter of its intended
 * inputs looks more precise than it is.
 */

const LIMIT = 25

const ROLES = [
  { value: '', label: 'All disciplines' },
  { value: 'batter', label: 'Batters' },
  { value: 'allrounder', label: 'All-rounders' },
  { value: 'bowler', label: 'Bowlers' },
]

const ROLE_LABEL: Record<string, string> = {
  batter: 'Bat',
  bowler: 'Bowl',
  allrounder: 'All',
  unknown: '-',
}

const field = 'rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink'
const fieldLabel = 'font-mono text-[10px] uppercase tracking-[0.1em] text-muted'

/** A component's percentile, drawn as a proportion of the bar it can fill. */
function ComponentBar({ score, weight, label }: { score: number; weight: number; label: string }) {
  return (
    <div className="flex items-center gap-2" title={`${label}: ${score.toFixed(1)} of 100, weighted ${(weight * 100).toFixed(1)}%`}>
      <span className="w-44 shrink-0 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
        {label}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-elevated">
        <div className="h-full rounded-full bg-analytic" style={{ width: `${score}%` }} />
      </div>
      <span className="tnum w-10 text-right text-xs text-ink">{score.toFixed(0)}</span>
      <span className="tnum w-12 text-right font-mono text-[10px] text-dim">
        {(weight * 100).toFixed(0)}%
      </span>
    </div>
  )
}

function Decomposition({ row, page }: { row: IndexRow; page: PerformanceIndexPage }) {
  const live = page.components.filter((c) => c.active)
  return (
    <tr className="border-b border-border-subtle bg-ground/40">
      <td colSpan={6} className="px-4 py-4">
        <div className="max-w-2xl space-y-2">
          {live.map((c) => (
            <ComponentBar
              key={c.key}
              label={c.label}
              score={row.scores[c.key] ?? 0}
              weight={c.applied_weight}
            />
          ))}
          <p className="pt-1 text-xs leading-relaxed text-dim">
            Each figure is this player's percentile among {ROLE_LABEL[row.role]?.toLowerCase()}
            {'-'}discipline peers in this scope, over their last {row.matches} matches. Measured
            values:{' '}
            {live.map((c, i) => (
              <span key={c.key}>
                {i > 0 && ' · '}
                <span className="text-muted">{c.label.toLowerCase()}</span>{' '}
                <span className="tnum">{row.raw[c.key]}</span>
              </span>
            ))}
            .
          </p>
        </div>
      </td>
    </tr>
  )
}

export function PerformanceIndex() {
  const { slug, apiGender } = useGender()
  const [params, setParams] = useSearchParams()
  const requestedCompetition = params.get('competition') ?? ''
  // The scope switch owns which family is in play. A competition from the other
  // family is dropped rather than sent, so the figures on screen always match
  // the heading above them.
  const {
    competition,
    competitionType,
    options: competitionOptions,
  } = useScopedCompetition(requestedCompetition)
  const role = params.get('role') ?? ''
  const offset = Number(params.get('offset') ?? 0)

  const [data, setData] = useState<PerformanceIndexPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // In the URL, not local state: a decomposition is the evidence behind a
  // rating, so it has to be something a scout can send to a colleague (§27).
  const open = params.get('explain') ?? ''

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
      .performanceIndex(apiGender, {
        competition: competition || undefined,
        competition_type: competitionType,
        role: role || undefined,
        limit: LIMIT,
        offset,
      })
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [apiGender, competition, competitionType, role, offset])

  const inactive = data?.components.filter((c) => !c.active) ?? []
  const missingWeight = inactive.reduce((sum, c) => sum + c.specified_weight, 0)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="u-display text-title text-ink">Performance Index</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          This project's own rating of who is playing the best cricket right now - distinct from{' '}
          <Link to={`/${slug}/rankings`} className="text-analytic-ink hover:underline">
            computed leaderboards
          </Link>{' '}
          (career totals) and{' '}
          <Link to={`/${slug}/icc-rankings`} className="text-analytic-ink hover:underline">
            ICC ratings
          </Link>{' '}
          (official). Click any row to see the components behind its score.
        </p>
      </div>


      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Scope</span>
          <select
            value={competition}
            onChange={(e) => update({ competition: e.target.value })}
            className={field}
          >
            {competitionOptions.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Discipline</span>
          <select value={role} onChange={(e) => update({ role: e.target.value })} className={field}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* §14: the UI must state which components are active. Amber because this
          is a statement about coverage - exactly what the colour is reserved for. */}
      {inactive.length > 0 && (
        <div className="rounded-lg border border-warning/30 bg-warning-dim/40 px-4 py-3">
          <p className="text-sm text-warning-ink">
            Running on {data?.components.filter((c) => c.active).length} of 7 components -{' '}
            <span className="tnum">{Math.round(missingWeight * 100)}%</span> of the intended
            weighting cannot yet be computed.
          </p>
          <ul className="mt-1.5 space-y-0.5 text-xs text-muted">
            {inactive.map((c) => (
              <li key={c.key}>
                <span className="text-ink">{c.label}</span> ({Math.round(c.specified_weight * 100)}
                %) - {c.unavailable_because}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-dim">
            The remaining weights are renormalised rather than the missing ones being scored zero,
            which would mark every player down identically and make the figure look more precise
            than it is.
          </p>
        </div>
      )}

      {error && <ErrorMessage message={error} />}
      {loading && !data && <LoadingSpinner />}

      {data && (
        <div className="scroll-x rounded-xl border border-border-subtle bg-surface shadow-card">
          <table className={`${tableClass} min-w-[680px]`}>
            <thead>
              <tr className={theadRowClass}>
                <th className="px-4 py-2.5">#</th>
                <th className={thClass}>Player</th>
                <th className={thClass}>Role</th>
                <th className="px-3 py-2.5 text-right">Matches</th>
                <th className="px-3 py-2.5 text-right">Index</th>
                <th className="px-4 py-2.5 text-right">Workings</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row, i) => (
                // The key belongs on the fragment, which is what `map` returns -
                // on the inner <tr> React still treats the list as unkeyed.
                <Fragment key={row.player_identifier}>
                  <tr
                    className={trClass}
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{offset + i + 1}</td>
                    <td className={tdClass}>
                      <PlayerName
                        name={row.player_name}
                        country={row.country}
                        countryCode={row.country_code}
                        to={`/${slug}/players/${row.player_identifier}`}
                        nameClassName="font-medium"
                      />
                    </td>
                    <td className={tdClass}>
                      <span
                        className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
                        title="Percentiles are taken against peers of this discipline - inferred from balls faced versus balls bowled"
                      >
                        {ROLE_LABEL[row.role] ?? row.role}
                      </span>
                    </td>
                    <td className={tdNumClass}>{row.matches}</td>
                    <td className="tnum px-3 py-2.5 text-right text-base font-semibold text-ink">
                      {row.index.toFixed(1)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() =>
                          update(
                            { explain: open === row.player_identifier ? '' : row.player_identifier },
                            true
                          )
                        }
                        className="font-mono text-[10px] uppercase tracking-[0.1em] text-analytic-ink hover:underline"
                      >
                        {open === row.player_identifier ? 'Hide' : 'How?'}
                      </button>
                    </td>
                  </tr>
                  {open === row.player_identifier && <Decomposition row={row} page={data} />}
                </Fragment>
              ))}
            </tbody>
          </table>

          {data.items.length === 0 && (
            <p className="px-4 py-6 text-sm text-muted">
              No players qualify in this scope.
            </p>
          )}

          <div className="px-4">
            <Pagination
              total={data.total}
              limit={LIMIT}
              offset={offset}
              onChange={(o) => update({ offset: String(o) }, true)}
            />
          </div>
        </div>
      )}

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        Each component is scored as a percentile among peers of the same inferred discipline in this
        scope, over the last {data?.window_matches ?? 15} matches, with a minimum of{' '}
        {data?.min_matches ?? 8}. Disciplines are pooled separately because a bowler's mean impact
        in this dataset is 1.08 par units against a batter's 0.64 - pooled together, the Index would
        rank discipline rather than quality. An Index of 87 therefore means "better than 87% of
        qualified players of this discipline in this scope", and scores from different scopes are
        not comparable.
      </p>
    </div>
  )
}
