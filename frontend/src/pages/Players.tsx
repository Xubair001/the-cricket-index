import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { PlayerSummary } from '../api/types'
import { ErrorMessage, LoadingSpinner } from '../components/LoadingSpinner'
import { Pagination } from '../components/Pagination'
import { useGender } from '../gender/useGender'

const LIMIT = 25

export function Players() {
  const { slug, apiGender } = useGender()
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [players, setPlayers] = useState<PlayerSummary[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
      setOffset(0)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    // Guards against a slower request for a previous search/offset resolving
    // after a newer one and overwriting it with stale results.
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .players(apiGender, { search: debouncedSearch || undefined, limit: LIMIT, offset })
      .then((res) => {
        if (cancelled) return
        setPlayers(res.items)
        setTotal(res.total)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [apiGender, debouncedSearch, offset])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Players</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {total.toLocaleString()} players with at least one international appearance
        </p>
      </div>

      <input
        type="text"
        placeholder="Search players by name..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-md rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
      />

      {error && <ErrorMessage message={error} />}
      {loading && players.length === 0 && <LoadingSpinner />}

      {!error && players.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <tbody>
              {players.map((p) => (
                <tr key={p.identifier} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800/50 dark:hover:bg-slate-800/40">
                  <td className="py-2.5 pl-5">
                    <Link
                      to={`/${slug}/players/${p.identifier}`}
                      className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                    >
                      {p.name}
                    </Link>
                  </td>
                  <td className="py-2.5 pr-5 text-right text-slate-500 dark:text-slate-400">
                    {p.matches} matches
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-5">
            <Pagination total={total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        </div>
      )}

      {!loading && !error && players.length === 0 && (
        <p className="text-sm text-slate-500 dark:text-slate-400">No players found.</p>
      )}
    </div>
  )
}
