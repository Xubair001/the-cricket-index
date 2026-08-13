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
  if (!iso) return '—'
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
    <Link
      to={`/${slug}/teams/${teamId}`}
      className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
    >
      {label}
    </Link>
  ) : (
    <span className="font-medium text-slate-700 dark:text-slate-200">{label}</span>
  )
}

function FixtureCard({ fixture, slug }: { fixture: FixtureRow; slug: string }) {
  const f = fixture
  return (
    <div className="border-b border-slate-100 px-5 py-3 last:border-0 dark:border-slate-800/60">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {f.match_type ?? '—'}
          </span>
          {f.is_live && (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-500/15 dark:text-red-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" aria-hidden />
              LIVE
            </span>
          )}
          <TeamCell name={f.team_a_name} short={f.team_a_short} teamId={f.team_a_id} slug={slug} />
          <span className="text-slate-400">v</span>
          <TeamCell name={f.team_b_name} short={f.team_b_short} teamId={f.team_b_id} slug={slug} />
        </div>
        <span className="text-xs text-slate-400">{formatDate(f.start_date)}</span>
      </div>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        {f.series_name ?? f.tour_name ?? ''}
        {f.venue && ` · ${f.venue}`}
      </p>
      {/* Result when there is one, otherwise ICC's own status string ("Match
          begins at 12:30 IST") -- never a made-up prediction. */}
      <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
        {f.match_result || f.match_status || ''}
      </p>
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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Fixtures</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Schedule and results from the ICC feed, refreshed daily.
          {data?.last_synced && ` Last synced ${data.last_synced.slice(0, 16).replace('T', ' ')} UTC.`}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900">
          {WINDOWS.map((w) => (
            <button
              key={w.value}
              type="button"
              onClick={() => {
                setWindow(w.value)
                setOffset(0)
              }}
              className={
                'rounded-md px-3 py-1.5 text-sm font-medium transition ' +
                (window_ === w.value
                  ? 'bg-emerald-600 text-white'
                  : 'text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white')
              }
            >
              {w.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          Format
          <select
            value={matchType}
            onChange={(e) => {
              setMatchType(e.target.value)
              setOffset(0)
            }}
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
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
            <p className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
              {window_ === 'live'
                ? 'No matches in progress right now.'
                : `No ${window_} fixtures for this selection.`}
            </p>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
              {data.items.map((f) => (
                <FixtureCard key={f.icc_match_id} fixture={f} slug={slug} />
              ))}
            </div>
          )}
          <Pagination
            total={data.total}
            limit={LIMIT}
            offset={offset}
            onChange={setOffset}
          />
        </>
      )}
    </div>
  )
}
