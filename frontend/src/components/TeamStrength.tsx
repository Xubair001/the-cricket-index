import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { StrengthDimension, TeamStrengthProfile } from '../api/types'
import { SkeletonRows } from './LoadingSpinner'
import { EmptyState, Panel, Uncertain } from './ui'
import { rate, score } from '../format'
import { competitionLabel } from '../competitions'

/**
 * A side's depth profile (Section 19), beside the weakness analysis.
 *
 * The two answer different questions and the page needs both: weakness asks
 * what has declined against this side's own past, strength asks where the side
 * is deep and where it is thin against the teams that actually contest the
 * competition.
 *
 * Three rendering rules, all of them carrying a measured decision from the API:
 *
 * - **A missing score is drawn as missing.** The API returns null rather than
 *   50 where no peer figure could be built, because 50 reads as "exactly
 *   typical" for a side nobody could measure. So the bar is absent, not
 *   half-full.
 * - **Bench usage has no score at all, deliberately.** A high number can mean
 *   healthy rotation or an unsettled side and this data cannot tell them apart,
 *   so scoring it would assert something unknown. It shows the raw count.
 * - **The peer figure sits beside every score.** Section 30 wants a figure
 *   traceable to what produced it, and "72nd percentile" is only meaningful
 *   next to what the core sides actually did.
 */
export function TeamStrengthPanel({
  teamId,
  competition,
}: {
  teamId: number
  competition?: string
}) {
  const [data, setData] = useState<TeamStrengthProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .teamStrengthProfile(teamId, competition ? { competition } : {})
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load the profile')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [teamId, competition])

  if (loading && !data) {
    return (
      <Panel title="Strength profile">
        <SkeletonRows rows={6} />
      </Panel>
    )
  }
  if (error || !data) {
    return (
      <Panel title="Strength profile">
        <EmptyState title="No strength profile for this side" hint={error ?? undefined} />
      </Panel>
    )
  }

  return (
    <Panel
      title="Strength profile"
      blurb={`Depth over this side's last ${data.matches_in_window} matches in ${
        data.competition_key ? competitionLabel(data.competition_key) : 'all'
      } cricket, scored against the sides with the most cricket in the same scope - never against the average side, because most international teams play rarely and an average-based reference tells every established side it is exceptional.`}
    >
      <div className="space-y-3">
        {data.dimensions.map((d) => (
          <DimensionRow key={d.key} d={d} />
        ))}
      </div>

      {data.notes.length > 0 && (
        <div className="mt-4 space-y-1 border-t border-border-subtle pt-3">
          {data.notes.map((n) => (
            <p key={n} className="text-xs leading-relaxed text-muted">
              {n}
            </p>
          ))}
        </div>
      )}

      {Object.keys(data.unavailable).length > 0 && (
        <div className="mt-3 space-y-1.5 border-t border-border-subtle pt-3">
          <h3 className="u-eyebrow">What a depth profile cannot tell you</h3>
          {Object.entries(data.unavailable).map(([key, reason]) => (
            <p key={key} className="text-xs leading-relaxed text-dim">
              <span className="font-medium text-muted">{key.replace(/_/g, ' ')}</span> - {reason}
            </p>
          ))}
        </div>
      )}
    </Panel>
  )
}

function DimensionRow({ d }: { d: StrengthDimension }) {
  const figure = d.value === null ? '-' : `${rate(d.value)}`
  const peer = d.peer_value === null ? null : rate(d.peer_value)

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className="text-sm font-medium text-ink" title={d.basis}>
          {d.label}
        </span>
        <span className="tnum text-sm text-muted">
          {d.reliable ? (
            figure
          ) : (
            <Uncertain reason="Too few matches in this window for the figure to describe the side">
              {figure}
            </Uncertain>
          )}
          <span className="ml-1 text-xs text-dim">{d.unit}</span>
        </span>
      </div>

      {/* The bar encodes the percentile, not the raw figure - the raw figures
          are in different units and a shared axis would be meaningless. */}
      <div className="par-track mt-1.5 h-1.5 overflow-hidden rounded-full bg-sunken">
        {d.score !== null && (
          <div
            className={`h-full rounded-full ${
              d.score >= 60 ? 'bg-positive' : d.score >= 40 ? 'bg-analytic' : 'bg-negative'
            }`}
            style={{ width: `${Math.max(2, d.score)}%` }}
          />
        )}
      </div>

      <p className="mt-1 text-xs text-dim">
        {d.score === null ? (
          d.key === 'bench_depth' ? (
            // Not a gap. Scoring this would assert that more rotation is
            // better, which is not known.
            <>Not scored: rotation and an unsettled side look identical here.</>
          ) : (
            <>
              No score - {d.peer_sides} comparable side{d.peer_sides === 1 ? '' : 's'} in this
              scope, which is too few to place this figure against.
            </>
          )
        ) : (
          <>
            <span className="tnum font-medium text-muted">{score(d.score)}</span> of 100 against{' '}
            {d.peer_sides} core side{d.peer_sides === 1 ? '' : 's'}
            {peer !== null && (
              <>
                , whose median is <span className="tnum">{peer}</span>
              </>
            )}
            .
          </>
        )}
      </p>
    </div>
  )
}

export default TeamStrengthPanel
