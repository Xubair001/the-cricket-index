import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ApiGender } from '../gender/useGender'
import type { PlayerSplits, SplitBucket } from '../api/types'
import { SkeletonRows } from './LoadingSpinner'
import {
  EmptyState,
  Panel,
  tableClass,
  tdClass,
  tdNumClass,
  tdNumStrongClass,
  thClass,
  thNumClass,
  theadRowClass,
  trClass,
  Uncertain,
} from './ui'
import { count, percent, rate } from '../format'
import { useFilters } from '../state/useFilters'

/**
 * Performance splits on a player's profile (Section 12).
 *
 * The analytics for this shipped with the deliveries backfill and then sat
 * behind an endpoint nothing called, which is why a profile could show a career
 * average and not the chasing average that makes it interesting.
 *
 * Two things the panel deliberately renders rather than hides:
 *
 * - **A split that does not apply says so.** Phases are defined per competition
 *   and a Test has none: a T20 powerplay is six overs, an ODI's is ten, and
 *   slicing the first six overs off a Test innings gives a number that looks
 *   like the T20 one and means something else. The API returns
 *   `applies: false` with the reason, and it is shown in place of the table.
 * - **The splits that cannot be computed at all are listed.** Home/away needs a
 *   venue-to-country mapping and pace-versus-spin needs a bowler-type source
 *   that does not exist. Leaving them out would make "no data for this player"
 *   and "this cut is not computable" look identical.
 *
 * Batting and bowling columns are both present because a split is one slice of
 * a player's cricket, not one discipline of it - but a column set with nothing
 * in it is dropped, so an opening batter's rows are not padded with six empty
 * bowling figures.
 */

const SPLIT_LABELS: Record<string, string> = {
  phase: 'By phase',
  situation: 'Batting first vs chasing',
  opposition: 'By opposition',
  venue: 'By venue',
  competition: 'By competition',
}

/** How many rows before the table is capped. Venue returns ~100 for a long
 *  career, which is a scroll rather than a read. */
const VISIBLE_ROWS = 12

export function PlayerSplitsPanel({
  identifier,
  gender,
  competitionKey,
  competitionLabel,
}: {
  identifier: string
  gender: ApiGender
  /** Which competition to slice within. Phases need one; see the note above. */
  competitionKey: string | null
  competitionLabel: string
}) {
  // In the URL, not component state: "look at their venue splits" is a link
  // somebody sends, and a back-navigation would otherwise drop the reader on
  // the default cut with nothing saying what changed.
  const f = useFilters()
  const split = f.get('split', 'situation')
  const expanded = f.flag('rows')
  const [data, setData] = useState<PlayerSplits | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .playerSplits(identifier, split, gender, {
        competition: competitionKey ?? undefined,
      })
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load splits')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [identifier, split, gender, competitionKey])

  const options = data?.available ?? Object.keys(SPLIT_LABELS)
  const buckets = data?.buckets ?? []
  const shown = expanded ? buckets : buckets.slice(0, VISIBLE_ROWS)

  // Drop a discipline with nothing in it rather than padding the row with
  // dashes: most players are not all-rounders.
  const anyBatting = buckets.some((b) => b.balls_faced > 0)
  const anyBowling = buckets.some((b) => b.balls_bowled > 0)

  return (
    <Panel
      title="Performance splits"
      blurb={`Within ${competitionLabel}. Phase and situation come from the stored ball-by-ball record; opposition, venue and competition come from the match.`}
      bodyClassName="overflow-x-auto"
    >
      <div className="mb-3 flex flex-wrap gap-1.5">
        {options.map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => f.set({ split: key, rows: null })}
            aria-pressed={split === key}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
              split === key
                ? 'border-border-strong bg-elevated text-ink'
                : 'border-border-default bg-surface text-muted hover:border-border-strong hover:text-ink'
            }`}
          >
            {SPLIT_LABELS[key] ?? key}
          </button>
        ))}
      </div>

      {loading && !data ? (
        <SkeletonRows rows={5} />
      ) : error ? (
        <EmptyState title="Could not load this split" hint={error} />
      ) : data && !data.applies ? (
        // Not an empty table. The reason IS the answer here.
        <EmptyState
          title={`${data.label} does not describe this format`}
          hint={data.not_applicable_because ?? undefined}
        />
      ) : buckets.length === 0 ? (
        <EmptyState
          title="No cricket in this split"
          hint="This player has no recorded deliveries in the scope selected above."
        />
      ) : (
        <>
          <table className={`${tableClass} min-w-[46rem]`}>
            <thead>
              <tr className={theadRowClass}>
                <th className={thClass}>{data?.label ?? 'Split'}</th>
                <th className={thNumClass} title="Innings in this split">
                  Inn
                </th>
                {anyBatting && (
                  <>
                    <th className={thNumClass}>Runs</th>
                    <th className={thNumClass} title="Runs per dismissal, not per innings">
                      Avg
                    </th>
                    <th className={thNumClass}>SR</th>
                    <th className={thNumClass} title="Share of balls faced that produced no run">
                      Dot %
                    </th>
                    <th className={thNumClass} title="Share of balls faced hit for four or six">
                      Bdry %
                    </th>
                  </>
                )}
                {anyBowling && (
                  <>
                    <th className={thNumClass}>Wkts</th>
                    <th className={thNumClass}>Econ</th>
                    <th className={thNumClass}>Bowl avg</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {shown.map((b) => (
                <SplitRow key={b.key} b={b} batting={anyBatting} bowling={anyBowling} />
              ))}
            </tbody>
          </table>

          {buckets.length > VISIBLE_ROWS && (
            <button
              type="button"
              onClick={() => f.keep({ rows: expanded ? null : 'true' })}
              className="mt-2 text-xs text-analytic-ink hover:underline"
            >
              {expanded
                ? `Show the top ${VISIBLE_ROWS}`
                : `Show all ${buckets.length} rows`}
            </button>
          )}
        </>
      )}

      {data && Object.keys(data.unavailable).length > 0 && (
        <div className="mt-4 space-y-1.5 border-t border-border-subtle pt-3">
          <h3 className="u-eyebrow">Splits this data cannot compute</h3>
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

function SplitRow({
  b,
  batting,
  bowling,
}: {
  b: SplitBucket
  batting: boolean
  bowling: boolean
}) {
  // A rate off two innings is not a record. The totals stay plain - the runs were
  // scored - and only the RATES carry the dotted rule, which is this product's
  // established mark for "trust this less" and is legible without colour.
  const marked = (value: number | null, ok: boolean, why: string) =>
    ok ? rate(value) : <Uncertain reason={why}>{rate(value)}</Uncertain>

  // Each rate names the denominator it actually rests on, because "too few
  // innings" is the wrong explanation for an average: that divides by
  // dismissals, and four innings can carry a sound strike rate beside a
  // meaningless average.
  const thin = `Only ${b.innings} ${b.innings === 1 ? 'innings' : 'innings'} here`
  const bat = (value: number | null) =>
    marked(value, b.batting_reliable, `${thin} - too little batting for a rate`)
  const battingAverage = (value: number | null) =>
    marked(
      value,
      b.average_reliable,
      `Divides by ${b.dismissals} ${b.dismissals === 1 ? 'dismissal' : 'dismissals'} - too few for an average`
    )
  const bowl = (value: number | null) =>
    marked(value, b.bowling_reliable, `${thin} - too little bowling for a rate`)
  const bowlingAverage = (value: number | null) =>
    marked(
      value,
      b.bowling_average_reliable,
      `Divides by ${b.wickets} ${b.wickets === 1 ? 'wicket' : 'wickets'} - too few for an average`
    )
  return (
    <tr className={trClass}>
      <td className={tdClass}>{b.label}</td>
      <td className={tdNumClass}>{count(b.innings)}</td>
      {batting && (
        <>
          <td className={tdNumStrongClass}>{count(b.runs)}</td>
          <td className={tdNumClass}>{battingAverage(b.average)}</td>
          <td className={tdNumClass}>{bat(b.strike_rate)}</td>
          <td className={tdNumClass}>{percent(b.dot_pct)}</td>
          <td className={tdNumClass}>{percent(b.boundary_pct)}</td>
        </>
      )}
      {bowling && (
        <>
          <td className={tdNumStrongClass}>{count(b.wickets)}</td>
          <td className={tdNumClass}>{bowl(b.economy)}</td>
          <td className={tdNumClass}>{bowlingAverage(b.bowling_average)}</td>
        </>
      )}
    </tr>
  )
}

export default PlayerSplitsPanel
