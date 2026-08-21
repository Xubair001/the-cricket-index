import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useFilters } from '../state/useFilters'
import type { ExplorerKind, ExplorerPage, ExplorerRow, TeamSummary, VenueOption } from '../api/types'
import { ErrorMessage } from '../components/LoadingSpinner'
import { ExplorerScatter } from '../components/ExplorerScatter'
import { competitionLabel } from '../competitions'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'
import { useScopedCompetition } from '../scope/scope'
import { rate } from '../format'
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
 * The analytics explorers (§21) - the power-user surface.
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

const ROLES = [
  { value: '', label: 'All eligible' },
  { value: 'batter', label: 'Batters' },
  { value: 'allrounder', label: 'All-rounders' },
  { value: 'bowler', label: 'Bowlers' },
]

// Roles are neutral chips. They classify, they don't judge - green/red/amber
// stay reserved for above/below baseline and low confidence.
const ROLE_LABEL: Record<string, string> = {
  batter: 'Bat',
  bowler: 'Bowl',
  allrounder: 'All',
  unknown: '-',
}

const field = 'rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink'
const fieldLabel = 'font-mono text-[10px] uppercase tracking-[0.1em] text-muted'

function cell(row: ExplorerRow, col: Column): string {
  const value = row[col.key]
  if (value === null || value === undefined) return '-'
  if (col.kind === 'int') return Number(value).toLocaleString()
  return rate(Number(value))
}

export function Explorer() {
  const { slug, apiGender } = useGender()
  const { explorer = 'batting' } = useParams<{ explorer: ExplorerKind }>()
  const kind = (EXPLORERS.some((e) => e.key === explorer) ? explorer : 'batting') as ExplorerKind
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
  const opposition = f.get('opposition')
  const dateFrom = f.get('from')
  const dateTo = f.get('to')
  const sortBy = f.get('sort')
  const minInnings = f.get('min_innings')
  const minBalls = f.get('min_balls')
  const role = f.get('role')
  const venue = f.get('venue')
  const offset = f.int('offset', 0)

  const [teams, setTeams] = useState<TeamSummary[]>([])
  const [venues, setVenues] = useState<VenueOption[]>([])
  const [data, setData] = useState<ExplorerPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)


  useEffect(() => {
    api
      .teams(apiGender, undefined, { limit: 500 })
      .then((res) => setTeams(res.items))
      .catch(() => setTeams([]))
    api
      .venues(apiGender)
      .then(setVenues)
      .catch(() => setVenues([]))
  }, [apiGender])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .explorer(kind, apiGender, {
        competition: competition || undefined,
        competition_type: competitionType,
        opposition_team_id: opposition ? Number(opposition) : undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        min_innings: minInnings ? Number(minInnings) : undefined,
        min_balls: minBalls ? Number(minBalls) : undefined,
        role: role || undefined,
        venue: venue || undefined,
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
  }, [kind, apiGender, competition, competitionType, opposition, dateFrom, dateTo, minInnings, minBalls, role, venue, sortBy, offset])

  const columns = COLUMNS[kind]
  const active = EXPLORERS.find((e) => e.key === kind)!
  const currentSort = data?.sort_by ?? sortBy

  return (
    <div className="space-y-5">
      <div>
        <h1 className="u-display text-title text-ink">Analytics Explorer</h1>
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
            {competitionOptions.map((c) => (
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
        {/* Ground, not raw venue string: Cricsheet spells one ground several
            ways, so this list is normalised and each entry carries a ground's
            whole history. */}
        <label className="flex flex-col gap-1">
          <span className={fieldLabel}>Ground</span>
          <select value={venue} onChange={(e) => update({ venue: e.target.value })} className={field}>
            <option value="">Any ground</option>
            {venues.map((v) => (
              <option key={v.venue} value={v.venue}>
                {v.venue} ({v.matches})
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
            placeholder={data ? String(data.applied_min_innings) : ''}
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
            placeholder={data ? String(data.applied_min_balls) : ''}
            value={minBalls}
            onChange={(e) => update({ min_balls: e.target.value })}
            className={`${field} w-24 placeholder:text-dim`}
          />
        </label>
      </div>

      {error && <ErrorMessage message={error} />}

      {/* The qualification in force is stated rather than left implicit - a
          leaderboard that silently excludes people looks like it covers
          everyone (§21). */}
      {data && (
        <p className="text-xs text-muted">
          {/* The count BEFORE the floor is the important half. A batting board
              for one ground against one side used to report 0 players where 148
              had played, and nothing on the page distinguished that from a
              ground with no cricket at it. */}
          <span className="tnum font-medium text-ink">{data.total.toLocaleString()}</span> of{' '}
          <span className="tnum">{data.total_before_volume_floor.toLocaleString()}</span>{' '}
          {data.total_before_volume_floor === 1 ? 'player' : 'players'}
          shown · needs <span className="tnum">{data.applied_min_innings}</span>{' '}
          {data.applied_min_innings === 1 ? 'match' : 'matches'} and{' '}
          <span className="tnum">{data.applied_min_balls}</span> balls
          {!minInnings && !minBalls && ' (scaled to this slice)'}
        </p>
      )}

      {/* The chart sits ABOVE the table, because it answers a different
          question and answering it first is the point: the table ranks, the
          scatter shows the shape of the field. A reader who only ever sees a
          sorted column cannot tell an accumulator from an aggressor. */}
      {data && data.items.length >= 4 && (
        <ExplorerScatter
          kind={kind}
          gender={apiGender}
          query={{
            competition: competition || undefined,
            competition_type: competition ? undefined : competitionType ?? undefined,
            opposition_team_id: opposition ? Number(opposition) : undefined,
            date_from: dateFrom || undefined,
            date_to: dateTo || undefined,
            min_innings: minInnings ? Number(minInnings) : undefined,
            min_balls: minBalls ? Number(minBalls) : undefined,
            role: role || undefined,
            venue: venue || undefined,
          }}
          scopeLabel={
            competition
              ? `${competitionLabel(competition)} cricket`
              : competitionType === 'domestic_league'
                ? 'franchise cricket'
                : 'international cricket'
          }
        />
      )}

      <div className="scroll-x rounded-xl border border-border-subtle bg-surface shadow-card">
        <table className={`${tableClass} min-w-[820px]`}>
          <thead>
            <tr className={theadRowClass}>
              <th className="px-4 py-2.5">#</th>
              <th className={thClass}>Player</th>
              <th className={thClass}>Role</th>
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
                    className={trClass}
                  >
                    <td className="tnum px-4 py-2.5 text-dim">{offset + i + 1}</td>
                    <td className={tdClass}>
                      <PlayerName
                        name={row.player_name}
                        country={row.country}
                        countryCode={row.country_code}
                        to={
                          row.player_identifier
                            ? `/${slug}/players/${row.player_identifier}`
                            : undefined
                        }
                        className={row.player_identifier ? '' : 'text-muted'}
                        nameClassName="font-medium"
                      />
                    </td>
                    <td className={tdClass}>
                      <span
                        className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default"
                        title="Inferred from balls faced versus balls bowled - no source states a playing role"
                      >
                        {ROLE_LABEL[row.role] ?? row.role}
                      </span>
                    </td>
                    {columns.map((c) => (
                      <td key={c.key} className={tdNumClass}>
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
              onChange={(o) => keep({ offset: String(o) })}
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
            opposition strength - an average here matches what a scorecard source publishes. The
            opposition adjustment applies to this project's own impact measures, on the all-round
            explorer and the form boards, which are labelled as derived.
          </>
        )}{' '}
        Role is <em>inferred</em> from where a player spends their deliveries, never sourced - so a
        specialist bowler cannot appear on a batting board and a specialist batter cannot appear on
        a bowling one, while all-rounders appear on both. A volume floor alone could not do that:
        Kohli has bowled 989 balls and Tendulkar 2,812, enough to clear any sane minimum.
        Wicketkeeper and opener remain unavailable at any threshold. The ground filter matches on
        the normalised ground rather than the raw string - Cricsheet files 593 spellings for 396
        grounds, so filtering the raw column would return part of a ground's history while
        appearing to return all of it.
      </p>
    </div>
  )
}
