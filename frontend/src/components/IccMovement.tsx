import { useEffect, useState } from 'react'
import { ArrowRight } from './Icon'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { IccMovementReport, IccMover } from '../api/types'
import { Flag } from './Flag'
import { SkeletonRows } from './LoadingSpinner'
import { EmptyState, Panel } from './ui'
import { useGender } from '../gender/useGender'

/**
 * Movement in an ICC ranking since the previous published list (Section 8).
 *
 * Not a ranking history, and the panel says so. `icc_player_rankings` is keyed
 * on `rank_date` so a history is storable, but only a handful of dated lists
 * exist yet - the daily sync began recently and the ICC republishes about
 * weekly. Drawing a trend over that would present weeks as a career, so this
 * shows movement and reports the snapshot count.
 *
 * Two display rules worth keeping:
 *
 * - **Up is positive even though position 1 is the top.** The API signs
 *   `places_gained` so a rise is positive; the arrow and the colour follow the
 *   sign, so the board cannot be read backwards.
 * - **New entries are their own list.** A player absent from the previous list
 *   has no published position, so they are not movers. Folding them in would
 *   attribute a rise the ICC never published.
 */
export function IccMovementPanel({ rankType }: { rankType: string }) {
  const { slug } = useGender()
  const [data, setData] = useState<IccMovementReport | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api
      .iccMovement(rankType)
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch(() => {
        if (!cancelled) setData(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [rankType])

  if (loading && !data) {
    return (
      <Panel title="Movement since the last published list">
        <SkeletonRows rows={5} />
      </Panel>
    )
  }
  if (!data) return null

  const nothing =
    data.risers.length === 0 && data.fallers.length === 0 && data.new_entries.length === 0

  return (
    <Panel
      title="Movement since the last published list"
      blurb={
        data.previous_date
          ? `The list published ${data.current_date} against ${data.previous_date}. ICC's own positions, unmodified - this project never adjusts a published rating.`
          : 'Only one published list is held for this ranking so far.'
      }
    >
      {nothing ? (
        <EmptyState
          title="No positions changed"
          hint={
            data.compared > 0
              ? `${data.compared} players held the same place across both lists. The ICC republishes roughly weekly, so two nearby snapshots are often identical.`
              : undefined
          }
        />
      ) : (
        <div className="grid gap-5 sm:grid-cols-2">
          <MoverList title="Climbed" rows={data.risers} slug={slug} />
          <MoverList title="Fell" rows={data.fallers} slug={slug} />
        </div>
      )}

      {data.new_entries.length > 0 && (
        <div className="mt-4 border-t border-border-subtle pt-3">
          <h3 className="u-eyebrow mb-2">New to the list</h3>
          <div className="flex flex-wrap gap-2">
            {data.new_entries.map((e) => (
              <span
                key={`${e.player_name}-${e.position}`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface px-2.5 py-1 text-xs text-ink"
              >
                <Flag code={e.country_code} name={e.country ?? ''} />
                {e.player_identifier ? (
                  <Link
                    to={`/${slug}/players/${e.player_identifier}`}
                    className="hover:text-analytic-ink"
                  >
                    {e.player_name}
                  </Link>
                ) : (
                  // ~12% of ICC rows do not resolve to a player here, and an
                  // ambiguous name resolves to nothing rather than a guess.
                  // They still display; they are just not links.
                  e.player_name
                )}
                <span className="tnum text-dim">#{e.position}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {data.notes.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-border-subtle pt-3">
          {data.notes.map((n) => (
            <p key={n} className="text-xs leading-relaxed text-dim">
              {n}
            </p>
          ))}
        </div>
      )}
    </Panel>
  )
}

function MoverList({
  title,
  rows,
  slug,
}: {
  title: string
  rows: IccMover[]
  slug: string
}) {
  if (rows.length === 0) {
    return (
      <div>
        <h3 className="u-eyebrow mb-2">{title}</h3>
        <p className="text-xs text-dim">Nobody.</p>
      </div>
    )
  }
  return (
    <div>
      <h3 className="u-eyebrow mb-2">{title}</h3>
      <ul className="divide-y divide-border-subtle">
        {rows.map((m) => {
          const up = m.places_gained > 0
          return (
            <li
              key={`${m.player_name}-${m.position}`}
              className="flex items-center gap-2 py-1.5 text-sm"
            >
              <span
                className={`w-3 shrink-0 text-center ${up ? 'text-positive-ink' : 'text-negative-ink'}`}
                aria-hidden
              >
                {up ? '\u25b2' : '\u25bc'}
              </span>
              <Flag code={m.country_code} name={m.country ?? ''} />
              <span className="min-w-0 flex-1 truncate text-ink">
                {m.player_identifier ? (
                  <Link
                    to={`/${slug}/players/${m.player_identifier}`}
                    className="hover:text-analytic-ink"
                  >
                    {m.player_name}
                  </Link>
                ) : (
                  m.player_name
                )}
              </span>
              <span className="tnum shrink-0 text-xs text-muted">
                {m.previous_position} <ArrowRight className="mx-0.5" /> {m.position}
              </span>
              <span
                className={`tnum w-10 shrink-0 text-right text-xs font-semibold ${
                  up ? 'text-positive-ink' : 'text-negative-ink'
                }`}
              >
                {up ? '+' : ''}
                {m.places_gained}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default IccMovementPanel
