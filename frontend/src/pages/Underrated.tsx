import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { UnderratedTable } from '../api/types'
import { useGender } from '../gender/useGender'
import { useFilters } from '../state/useFilters'
import { ErrorMessage, SkeletonRows } from '../components/LoadingSpinner'
import { PlayerName } from '../components/PlayerName'
import { count, rate } from '../format'
import {
  EmptyState,
  PageHeader,
  Panel,
  Provenance,
  fieldClass,
  fieldLabelClass,
  tableClass,
  tdClass,
  tdNumClass,
  tdNumStrongClass,
  thClass,
  thNumClass,
  theadRowClass,
  trClass,
} from '../components/ui'

/**
 * Underrated players (Section 15).
 *
 * The scope calls the gap between two of its three rankings a product in its
 * own right. It is equally explicit about the line this page must not cross:
 * "the platform must never imply its rating replaces or corrects the ICC's."
 *
 * So the page is worded as a disagreement between two ratings, never as an ICC
 * error, and the ICC position is shown unmodified beside our own. Three things
 * carry that:
 *
 * - Both ranks are re-ranked inside the set of players who appear in BOTH, and
 *   the page says so. Comparing ICC's 100 against an Index that rates
 *   thousands would be comparing two populations, not two opinions.
 * - Coverage sits ABOVE the table, because a gap cannot be weighed without
 *   knowing how much of ICC's list it was measured over.
 * - The associate skew is stated. Without it, a board of Dutch and Irish names
 *   reads as a finding about the ICC rather than as a difference in what the
 *   two ratings measure.
 */

/** ICC's rank types, grouped so the control reads as cricket rather than as keys. */
const DISCIPLINES = [
  { value: 'batting', label: 'Batting' },
  { value: 'bowling', label: 'Bowling' },
  { value: 'allrounder', label: 'All-rounders' },
]

const FORMATS_MEN = [
  { value: 'test', label: 'Tests' },
  { value: 'odi', label: 'ODIs' },
  { value: 't20', label: 'T20Is' },
]

// ICC publishes no women's Test ranking, so the control must not offer one.
const FORMATS_WOMEN = [
  { value: 'odiw', label: 'ODIs' },
  { value: 't20w', label: 'T20Is' },
]

export function Underrated() {
  const { slug, apiGender } = useGender()
  const formats = apiGender === 'female' ? FORMATS_WOMEN : FORMATS_MEN

  const f = useFilters()
  // Validated against the CURRENT gender's list rather than taken raw, because
  // men's and women's rank types share no vocabulary: 'test' has no women's
  // equivalent, so a gender switch carrying it over would request a table the
  // ICC does not publish. An unknown value falls back rather than erroring.
  const requestedFormat = f.get('format')
  const format = formats.some((o) => o.value === requestedFormat)
    ? requestedFormat
    : formats[0].value
  const discipline = f.get('discipline', 'batting')
  const [data, setData] = useState<UnderratedTable | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // The fallback above already displays the right table; this clears the stale
  // value out of the URL so a shared link matches what is on screen.
  useEffect(() => {
    if (requestedFormat && requestedFormat !== format) f.set({ format: null })
  }, [requestedFormat, format, f])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .underrated(`${format}-${discipline}`, { limit: 25 })
      .then((res) => !cancelled && setData(res))
      .catch((e: Error) => !cancelled && (setError(e.message), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [format, discipline])

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={`${slug === 'men' ? "Men's" : "Women's"} cricket · two ratings compared`}
        title="Underrated Players"
        blurb="Where this project's Performance Index and the ICC's published position disagree most. Not a correction of the ICC's rating - the two are built from different evidence, and the disagreement is the point."
      />

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Format</span>
          <select
            value={format}
            onChange={(e) => f.set({ format: e.target.value })}
            className={fieldClass}
          >
            {formats.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={fieldLabelClass}>Discipline</span>
          <select
            value={discipline}
            onChange={(e) => f.set({ discipline: e.target.value })}
            className={fieldClass}
          >
            {DISCIPLINES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? (
        <ErrorMessage message={error} />
      ) : (
        <Panel
          title={
            data
              ? `${data.items.length} where the two ratings disagree by ${data.min_gap}+ places`
              : 'Loading'
          }
          blurb={
            data ? (
              <>
                Compared over <span className="font-semibold text-ink">{data.comparable}</span> of
                the {data.icc_listed} players the ICC ranks here, against their snapshot of{' '}
                {data.rank_date}. Both orderings are re-ranked within exactly that set, so the gap
                is between two opinions of one group rather than two differently-sized lists.
              </>
            ) : undefined
          }
          bodyClassName="overflow-x-auto"
        >
          {loading ? (
            <SkeletonRows rows={8} className="p-4" />
          ) : !data || data.items.length === 0 ? (
            <EmptyState
              title="The two ratings agree here"
              hint="Nobody in this discipline differs by enough places to be worth showing. That is a real result, not an empty page - the median disagreement across all disciplines is zero."
            />
          ) : (
            <table className={`${tableClass} min-w-[46rem]`}>
              <thead>
                <tr className={theadRowClass}>
                  <th className={thClass}>Player</th>
                  <th className={thNumClass}>ICC #</th>
                  <th className={thNumClass} title="ICC's order, compressed to the compared set">
                    ICC in set
                  </th>
                  <th className={thNumClass} title="Our order within the same set">
                    Ours
                  </th>
                  <th className={thNumClass}>Gap</th>
                  <th className={thNumClass}>Index</th>
                  <th className={thNumClass}>M</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.player_identifier} className={trClass}>
                    <td className={tdClass}>
                      <Link
                        to={`/${slug}/players/${p.player_identifier}`}
                        className="hover:text-analytic-ink"
                      >
                        <PlayerName
                          name={p.player_name}
                          country={p.country}
                          countryCode={p.country_code}
                        />
                      </Link>
                    </td>
                    {/* ICC's own number, unmodified and first, because it is
                        the figure a reader recognises and the one this page
                        must not appear to overwrite. */}
                    <td className={tdNumClass}>{count(p.icc_position)}</td>
                    <td className={tdNumClass}>{count(p.icc_rank_in_set)}</td>
                    <td className={tdNumStrongClass}>{count(p.index_rank_in_set)}</td>
                    <td className="tnum px-3 py-2.5 text-right font-semibold text-positive-ink">
                      +{p.gap}
                    </td>
                    <td className={tdNumClass}>{rate(p.index)}</td>
                    <td className={tdNumClass}>{count(p.matches)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      )}

      {data && data.notes.length > 0 && (
        <Panel title="How to read this">
          <ul className="space-y-2">
            {data.notes.map((n, i) => (
              <li key={i} className="text-sm leading-relaxed text-muted">
                {n}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Provenance>
        Two ratings, kept apart everywhere else in this product and compared only here. The{' '}
        <Link to={`/${slug}/icc-rankings`} className="text-analytic-ink hover:underline">
          ICC's rating
        </Link>{' '}
        is a points system over a rolling window of results, weighted by the opposition's own
        standing. The{' '}
        <Link to={`/${slug}/performance-index`} className="text-analytic-ink hover:underline">
          Performance Index
        </Link>{' '}
        is a percentile blend over ball-by-ball contribution across a player's last 15 matches.
        Neither is the other's approximation and neither is corrected here. A player the ICC does
        not list is excluded rather than treated as ranked last, because absence is not a position -
        it may mean 101st or it may mean the ICC does not rate them at all, and this dataset cannot
        tell those apart.
      </Provenance>
    </div>
  )
}
