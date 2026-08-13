import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ExplorerKind, ExplorerPage, ExplorerRow, TeamSummary } from '../api/types'
import { ErrorMessage } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'
import { rate } from '../format'

/**
 * The analytics explorers (§21) — the power-user surface.
 *
 * One page serves all three explorers because §21 specifies a *shared* filter
 * model: a scout who narrows to "T20Is against Australia since 2024" expects
 * that to mean the same thing whichever metric set they switch to. Three
 * separate pages is how those three views quietly stop agreeing.
 *
 * Every filter, sort and page is applied server-side. Filter state lives in the
 * URL so a narrowed view is a link a scout can send to a colleague (§27).
 */

const LIMIT = 25

const EXPLORERS: { key: ExplorerKind; label: string; blurb: string }[] = [
  {
    key: 'batting',
    label: 'Batting',
    blurb: 'Runs, average, strike rate and how often the ball goes to the fence.',
  },
  {
    key: 'bowling',
    label: 'Bowling',
    blurb: 'Wickets, average, economy and balls per wicket.',
  },
  {
    key: 'allround',
    label: 'All-round',
    blurb:
      'Contribution in par units, where 1.0 is an average appearance. Runs and wickets do not add up, so this is the one view expressed in impact rather than conventional figures.',
  },
]

// Column layout per explorer. `sort` names the server-side sort key; a column
// without one is descriptive and not sortable.
type Column = { key: string; label: string; sort?: string; kind?: 'rate' | 'int' }

const COLUMNS: Record<ExplorerKind, Column[]> = {
  batting: [
    { key: 'matches', label: 'Mat', sort: 'matches', kind: 'int' },
    { key: 'runs', label: 'Runs', sort: 'runs', kind: 'int' },
    { key: 'average', label: 'Avg', sort: 'average', kind: 'rate' },
    { key: 'strike_rate', label: 'SR', sort: 'strike_rate', kind: 'rate' },
    { key: 'boundary_pct', label: 'Bnd %', sort: 'boundary_pct', kind: 'rate' },
    { key: 'balls_faced', label: 'Balls', sort: 'balls_faced', kind: 'int' },
  ],
  bowling: [
    { key: 'matches', label: 'Mat', sort: 'matches', kind: 'int' },
    { key: 'wickets', label: 'Wkts', sort: 'wickets', kind: 'int' },
    { key: 'average', label: 'Avg', sort: 'average', kind: 'rate' },
    { key: 'economy', label: 'Econ', sort: 'economy', kind: 'rate' },
    { key: 'strike_rate', label: 'SR', sort: 'strike_rate', kind: 'rate' },
    { key: 'balls_bowled', label: 'Balls', sort: 'balls_bowled', kind: 'int' },
  ],
  allround: [
    { key: 'matches', label: 'Mat', sort: 'matches', kind: 'int' },
    { key: 'combined_contribution', label: 'Combined', sort: 'combined_contribution', kind: 'rate' },
    { key: 'batting_contribution', label: 'Batting', sort: 'batting_contribution', kind: 'rate' },
    { key: 'bowling_contribution', label: 'Bowling', sort: 'bowling_contribution', kind: 'rate' },
    { key: 'balance', label: 'Balance', sort: 'balance', kind: 'rate' },
    { key: 'runs', label: 'Runs', kind: 'int' },
    { key: 'wickets', label: 'Wkts', kind: 'int' },
  ],
}

const COMPETITIONS = [
  { value: '', label: 'All Internationals' },
  { value: 'tests', label: 'Tests' },
  { value: 'odis', label: 'ODIs' },
  { value: 't20is', label: 'T20Is' },
  { value: 'psl', label: 'PSL' },
]

const ROLES = [
  { value: '', label: 'All eligible' },
  { value: 'batter', label: 'Batters' },
  { value: 'allrounder', label: 'All-rounders' },
  { value: 'bowler', label: 'Bowlers' },
]

// Roles are neutral chips. They classify, they don't judge — green/red/amber
// stay reserved for above/below baseline and low confidence.
const ROLE_LABEL: Record<string, string> = {
  batter: 'Bat',
  bowler: 'Bowl',
  allrounder: 'All',
  unknown: '—',
}

const field = 'rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink'
const fieldLabel = 'font-mono text-[10px] uppercase tracking-[0.1em] text-muted'

function cell(row: ExplorerRow, col: Column): string {
  const value = row[col.key]
  if (value === null || value === undefined) return '—'
  if (col.kind === 'int') return Number(value).toLocaleString()
  return rate(Number(value))
}

export function Explorer() {
  const { slug, apiGender } = useGender()
  const { explorer = 'batting' } = useParams<{ explorer: ExplorerKind }>()
  const kind = (EXPLORERS.some((e) => e.key === explorer) ? explorer : 'batting') as ExplorerKind
  const [params, setParams] = useSearchParams()

  const competition = params.get('competition') ?? ''
  const opposition = params.get('opposition') ?? ''
  const dateFrom = params.get('from') ?? ''
  const dateTo = params.get('to') ?? ''
  const sortBy = params.get('sort') ?? ''
  const minInnings = params.get('min_innings') ?? ''
  const minBalls = params.get('min_balls') ?? ''
  const role = params.get('role') ?? ''
  const offset = Number(params.get('offset') ?? 0)

  const [teams, setTeams] = useState<TeamSummary[]>([])
  const [data, setData] = useState<ExplorerPage | null>(null)
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
    api
      .teams(apiGender, undefined, { limit: 500 })
      .then((res) => setTeams(res.items))
      .catch(() => setTeams([]))
  }, [apiGender])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .explorer(kind, apiGender, {
        competition: competition || undefined,
        opposition_team_id: opposition ? Number(opposition) : undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        min_innings: minInnings ? Number(minInnings) : undefined,
        min_balls: minBalls ? Number(minBalls) : undefined,
        role: role || undefined,
        sort_by: sortBy || undefined,
        limit: LIMIT,
        offset,
      })
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && (setError(String(e)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [kind, apiGender, competition, opposition, dateFrom, dateTo, minInnings, minBalls, role, sortBy, offset])

  const columns = COLUMNS[kind]
  const active = EXPLORERS.find((e) => e.key === kind)!
  const currentSort = data?.sort_by ?? sortBy

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Analytics Explorer</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">{active.blurb}</p>
      </div>

      <div className="inline-flex rounded-lg border border-border-default bg-surface p-0.5">
        {EXPLORERS.map((e) => (
          <Link
            key={e.key}
            to={`/${slug}/analytics/${e.key}`}
            className={
              'rounded-md px-4 py-1.5 text-sm font-medium transition-colors ' +
              (e.key === kind ? 'bg-elevated text-ink' : 'text-muted hover:text-ink')
            }
          >
            {e.label}
          </Link>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Competition</span>
          <select
            value={competition}
            onChange={(e) => update({ competition: e.target.value })}
            className={field}
          >
            {COMPETITIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Opposition</span>
          <select
            value={opposition}
            onChange={(e) => update({ opposition: e.target.value })}
            className={field}
          >
            <option value="">Any opposition</option>
            {teams.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>From</span>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => update({ from: e.target.value })}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>To</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => update({ to: e.target.value })}
            className={field}
          />
        </label>
        {kind !== 'allround' && (
          <label className="flex flex-col gap-1">
            <span className={fieldLabel}>Role</span>
            <select value={role} onChange={(e) => update({ role: e.target.value })} className={field}>
              {ROLES.filter(
                (r) => !r.value || (data?.filters.roles_shown ?? []).includes(r.value as never)
              ).map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Min matches</span>
          <input
            type="number"
            min={1}
            placeholder={String(data?.filters.min_innings ?? '')}
            value={minInnings}
            onChange={(e) => update({ min_innings: e.target.value })}
            className={`${field} w-24 placeholder:text-dim`}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Min balls</span>
          <input
            type="number"
            min={0}
            placeholder={String(data?.filters.min_balls ?? '')}
            value={minBalls}
            onChange={(e) => update({ min_balls: e.target.value })}
            className={`${field} w-24 placeholder:text-dim`}
          />
        </label>
      </div>

      {error && <ErrorMessage message={error} />}

      {/* The qualification in force is stated rather than left implicit — a
          leaderboard that silently excludes people looks like it covers
          everyone (§21). */}
      {data && (
        <p className="text-xs text-muted">
          {data.total.toLocaleString()} players qualify ·{' '}
          <span className="tnum">{data.filters.min_innings}</span> matches and{' '}
          <span className="tnum">{data.filters.min_balls}</span> balls minimum
          {data.filters.min_balls > 0 && ' — rate columns are meaningless below a volume floor'}
        </p>
      )}

      <div className="scroll-x rounded-lg border border-border-default bg-surface">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="border-b border-border-default bg-elevated text-left font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
              <th className="px-4 py-2.5">#</th>
              <th className="px-3 py-2.5">Player</th>
              <th className="px-3 py-2.5">Role</th>
              {columns.map((c) => (
                <th key={c.key} className="px-3 py-2.5 text-right">
                  {c.sort ? (
                    <button
                      type="button"
                      onClick={() => update({ sort: c.sort! })}
                      className={`transition-colors hover:text-ink ${
                        currentSort === c.sort ? 'text-ink' : ''
                      }`}
                      title={`Sort by ${c.label}`}
                    >
                      {c.label}
                      {currentSort === c.sort && ' ▾'}
                    </button>
                  ) : (
                    c.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && !data
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={columns.length + 3} className="px-4 py-2">
                      <div className="h-5 animate-pulse rounded bg-elevated" />
                    </td>
                  </tr>
                ))
              : data?.items.map((row, i) => (
                  <tr
                    key={row.player_identifier ?? row.player_name}
                    className="border-b border-border-subtle last:border-0 hover:bg-elevated"
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{offset + i + 1}</td>
                    <td className="px-3 py-2.5">
                      {row.player_identifier ? (
                        <Link
                          to={`/${slug}/players/${row.player_identifier}`}
                          className="font-medium text-ink hover:text-analytic"
                        >
                          {row.player_name}
                        </Link>
                      ) : (
                        <span className="text-muted">{row.player_name}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
                        title="Inferred from balls faced versus balls bowled — no source states a playing role"
                      >
                        {ROLE_LABEL[row.role] ?? row.role}
                      </span>
                    </td>
                    {columns.map((c) => (
                      <td key={c.key} className="tnum px-3 py-2.5 text-right text-muted">
                        {cell(row, c)}
                      </td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>

        {data && data.items.length === 0 && !loading && (
          <p className="px-4 py-6 text-sm text-muted">
            No players clear these thresholds. Try lowering the minimum matches or balls, or
            widening the date range.
          </p>
        )}

        {data && (
          <div className="px-4">
            <Pagination
              total={data.total}
              limit={LIMIT}
              offset={offset}
              onChange={(o) => update({ offset: String(o) }, true)}
            />
          </div>
        )}
      </div>

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        {kind === 'allround' ? (
          <>
            Contribution is in par units per match, where 1.0 is an average appearance in that
            competition, and it <em>is</em> adjusted for the strength of the opposition. Balance
            runs from 0 (a pure bowler) through 0.5 (an even all-rounder) to 1 (a pure batter).
          </>
        ) : (
          <>
            These are conventional figures and are deliberately <em>not</em> adjusted for
            opposition strength — an average here matches what a scorecard source publishes. The
            opposition adjustment applies to this project's own impact measures, on the all-round
            explorer and the form boards, which are labelled as derived.
          </>
        )}{' '}
        Role is <em>inferred</em> from where a player spends their deliveries, never sourced — so a
        specialist bowler cannot appear on a batting board and a specialist batter cannot appear on
        a bowling one, while all-rounders appear on both. A volume floor alone could not do that:
        Kohli has bowled 989 balls and Tendulkar 2,812, enough to clear any sane minimum.
        Wicketkeeper and opener remain unavailable at any threshold, and a venue filter is absent
        rather than inert because venue strings are not yet normalised.
      </p>
    </div>
  )
}
