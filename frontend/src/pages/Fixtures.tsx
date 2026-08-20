import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { FixtureRow, FixtureWindow, PaginatedFixtures } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'

const LIMIT = 25

const WINDOWS: { value: FixtureWindow; label: string }[] = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'live', label: 'Live' },
  { value: 'results', label: 'Results' },
]

/** ISO date -> "Wed 12 Aug 2026". */
function formatDate(iso: string | null): string {
  if (!iso) return '-'
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  })
}

function TeamCell({ name, short, teamId, slug }: {
  name: string | null; short: string | null; teamId: number | null; slug: string
}) {
  const label = name || short || 'TBC'
  // Only sides we actually hold data for become links; ICC lists many associate
  // teams this dataset has never covered, and a dead link is worse than text.
  return teamId ? (
    <Link to={`/${slug}/teams/${teamId}`} className="font-medium text-ink hover:text-analytic-ink">
      {label}
    </Link>
  ) : (
    <span className="font-medium text-muted" title="Not a side this dataset covers">
      {label}
    </span>
  )
}

function FixtureCard({ fixture, slug }: { fixture: FixtureRow; slug: string }) {
  const f = fixture
  return (
    <div className="border-b border-border-subtle px-4 py-3 last:border-0">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted ring-1 ring-inset ring-border-default">
            {f.match_type ?? '-'}
          </span>
          {/* "In progress" is analytical information, not a judgement, so it
              takes the neutral analytic colour. Red stays reserved for below
              baseline / declining - a live match is neither. */}
          {f.is_live && (
            <span className="inline-flex items-center gap-1 rounded-full bg-analytic-dim px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-analytic-ink ring-1 ring-inset ring-analytic/30">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-analytic" aria-hidden />
              Live
            </span>
          )}
          <TeamCell name={f.team_a_name} short={f.team_a_short} teamId={f.team_a_id} slug={slug} />
          <span className="text-dim">v</span>
          <TeamCell name={f.team_b_name} short={f.team_b_short} teamId={f.team_b_id} slug={slug} />
        </div>
        <span className="tnum text-xs text-dim">{formatDate(f.start_date)}</span>
      </div>
      <p className="mt-1 text-xs text-muted">
        {f.series_name ?? f.tour_name ?? ''}
        {f.venue && ` · ${f.venue}`}
      </p>
      {/* Result when there is one, otherwise ICC's own status string ("Match
          begins at 12:30 IST") -- never a made-up prediction.

          The two are not weighted the same. A result is the answer to the
          question the row was opened for, so it takes ink. A pre-match status
          is scheduling chatter; given the same weight it out-shouted the team
          names on every upcoming fixture, which is the one thing an upcoming
          row is actually about. */}
      {f.match_result ? (
        <p className="mt-1 text-sm text-ink">{f.match_result}</p>
      ) : f.match_status ? (
        <p className="mt-1 text-sm text-muted">{f.match_status}</p>
      ) : null}
    </div>
  )
}

export function Fixtures() {
  const { slug, apiGender } = useGender()
  const [window_, setWindow] = useState<FixtureWindow>('upcoming')
  const [matchType, setMatchType] = useState('')
  const [types, setTypes] = useState<string[]>([])
  const [data, setData] = useState<PaginatedFixtures | null>(null)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.fixtureMatchTypes(apiGender).then((r) => setTypes(r.match_types)).catch(() => setTypes([]))
  }, [apiGender])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .fixtures({
        gender: apiGender,
        window: window_,
        match_type: matchType || undefined,
        limit: LIMIT,
        offset,
      })
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [apiGender, window_, matchType, offset])

  return (
    <div className="space-y-5">
      <div>
        <h1 className="u-display text-title text-ink">Fixtures</h1>
        <p className="mt-1 text-sm text-muted">
          Schedule and results from the ICC feed, refreshed daily.
          {data?.last_synced && (
            <span className="tnum">
              {' '}
              Last synced {data.last_synced.slice(0, 16).replace('T', ' ')} UTC.
            </span>
          )}
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="inline-flex rounded-lg border border-border-default bg-surface p-0.5">
          {WINDOWS.map((w) => (
            <button
              key={w.value}
              type="button"
              onClick={() => {
                setWindow(w.value)
                setOffset(0)
              }}
              className={
                'rounded-md px-3 py-1.5 text-sm font-medium transition-colors ' +
                (window_ === w.value ? 'bg-elevated text-ink' : 'text-muted hover:text-ink')
              }
            >
              {w.label}
            </button>
          ))}
        </div>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">Format</span>
          <select
            value={matchType}
            onChange={(e) => {
              setMatchType(e.target.value)
              setOffset(0)
            }}
            className="rounded-md border border-border-default bg-surface px-2.5 py-1.5 text-sm text-ink"
          >
            <option value="">All formats</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <ErrorMessage message={error} />}
      {loading && <LoadingSpinner />}

      {data && !loading && (
        <>
          {data.items.length === 0 ? (
            <p className="rounded-xl border border-border-subtle bg-surface shadow-card px-4 py-6 text-sm text-muted">
              {window_ === 'live'
                ? 'No matches in progress right now.'
                : `No ${window_} fixtures for this selection.`}
            </p>
          ) : (
            <div className="rounded-xl border border-border-subtle bg-surface shadow-card">
              {data.items.map((f) => (
                <FixtureCard key={f.icc_match_id} fixture={f} slug={slug} />
              ))}
            </div>
          )}
          <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
        </>
      )}

      <p className="max-w-3xl text-xs leading-relaxed text-dim">
        The ICC feed carries internationals and youth internationals only - no franchise cricket, so
        a PSL window will not appear here. Sides this dataset has never covered are shown but not
        linked. Results are date-bounded rather than filtered on a flag, because a cancelled future
        fixture is marked as concluded and would otherwise sort to the top as a match that never
        happened.
      </p>
    </div>
  )
}
