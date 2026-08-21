import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AppliedPeriod, PeriodOption } from '../api/types'
import { fieldClass, fieldLabelClass } from './ui'

/**
 * The "when" control (Section 11, Principle 3).
 *
 * Principle 3 says career, last 12/6/3 months, last 30 days and last 20/10/5
 * matches are first-class *everywhere* rather than a toggle bolted onto a career
 * page. The analytics layer has supported all of it from the start - what was
 * missing was any way for a reader to ask. This is that control, and it is
 * shared rather than reimplemented per page so the vocabulary cannot drift.
 *
 * Three things it does deliberately:
 *
 * - **The options come from the API**, not from a list here. `periods.PRESETS`
 *   is the single definition of what a window can be, and a client-side copy is
 *   exactly how the five hardcoded competition dropdowns went out of step with
 *   the competitions table.
 * - **A custom range is a separate control**, not an option in the list. It
 *   needs two date inputs, and it is the only way to ask for a calendar year:
 *   a "season" here is the source's own label and a format's cricket can span
 *   two of them, so `2024` and `2024/25` are different seasons and neither is
 *   the year.
 * - **The window is one URL parameter.** `custom:2024-01-01:2024-12-31` keeps
 *   the whole window in one shareable value rather than spreading it across
 *   `from` and `to` that can arrive half-set.
 */

const CUSTOM = 'custom'

/** Splits `custom:<from>:<to>` back into its two dates for the inputs. */
function customBounds(spec: string): { from: string; to: string } {
  const parts = spec.split(':')
  return parts.length === 3 ? { from: parts[1], to: parts[2] } : { from: '', to: '' }
}

export function PeriodSelect({
  value,
  onChange,
  label = 'Period',
}: {
  /** The current spec, or '' for career. */
  value: string
  onChange: (spec: string) => void
  label?: string
}) {
  const [options, setOptions] = useState<PeriodOption[]>([])
  const isCustom = value.startsWith(`${CUSTOM}:`)
  const bounds = isCustom ? customBounds(value) : { from: '', to: '' }
  // Held locally while being typed: a half-entered range is not a window, so
  // nothing is sent until both dates are present and in order.
  const [from, setFrom] = useState(bounds.from)
  const [to, setTo] = useState(bounds.to)
  const [showCustom, setShowCustom] = useState(isCustom)

  useEffect(() => {
    api
      .periods()
      .then(setOptions)
      .catch(() => setOptions([]))
  }, [])

  // Follow the URL when it changes underneath us (a shared link, a back
  // navigation), without clobbering what is being typed.
  useEffect(() => {
    if (!isCustom) return
    const next = customBounds(value)
    setFrom(next.from)
    setTo(next.to)
    setShowCustom(true)
  }, [value, isCustom])

  function chooseCustom(nextFrom: string, nextTo: string) {
    setFrom(nextFrom)
    setTo(nextTo)
    // Only a complete, ordered range is a window. Sending a half-set one would
    // 422, and clearing the board while somebody is still typing reads as an
    // error rather than as an incomplete entry.
    if (nextFrom && nextTo && nextFrom <= nextTo) {
      onChange(`${CUSTOM}:${nextFrom}:${nextTo}`)
    }
  }

  const selected = isCustom ? CUSTOM : value || 'career'

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1">
        <span className={fieldLabelClass}>{label}</span>
        <select
          value={selected}
          onChange={(e) => {
            const next = e.target.value
            if (next === CUSTOM) {
              setShowCustom(true)
              // Nothing is sent yet: the reader has chosen to enter a range, not
              // yet entered one.
              if (from && to) chooseCustom(from, to)
              return
            }
            setShowCustom(false)
            // 'career' is the default, so it is written as an absent parameter
            // rather than as `period=career` - a default board keeps a clean URL.
            onChange(next === 'career' ? '' : next)
          }}
          className={fieldClass}
        >
          {options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
          <option value={CUSTOM}>Custom range...</option>
        </select>
      </label>

      {showCustom && (
        <>
          <label className="flex flex-col gap-1">
            <span className={fieldLabelClass}>From</span>
            <input
              type="date"
              value={from}
              onChange={(e) => chooseCustom(e.target.value, to)}
              className={`${fieldClass} w-40`}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={fieldLabelClass}>To</span>
            <input
              type="date"
              value={to}
              onChange={(e) => chooseCustom(from, e.target.value)}
              className={`${fieldClass} w-40`}
            />
          </label>
        </>
      )}
    </div>
  )
}

/**
 * What window the figures above actually came from.
 *
 * §30 requires a figure to be traceable to how it was produced, and the window
 * is half of that: "1,556 runs" means nothing without knowing over what. Two
 * cases need saying rather than inferring, and the API supplies the wording:
 *
 * - A **relative** window resolves to real dates, and it counts back from the
 *   newest match in the scope rather than from today - so the reader can see
 *   which twelve months they are looking at.
 * - A **count-bounded** window is each player's OWN last N, so a retired
 *   player's final ten sit beside a current player's most recent ten. A board
 *   headed "last 10 matches" otherwise reads as "recent form".
 *
 * Absent entirely for a career board, where there is no window to explain.
 */
export function AppliedPeriodNote({ period }: { period: AppliedPeriod | null }) {
  if (!period || period.kind === 'career') return null
  const range =
    period.start && period.end ? `${period.start} to ${period.end}` : null
  // A custom window's label IS its range, so appending it repeats the line.
  // Only a relative window ("Last 12 months") needs the dates spelled out.
  const showRange = range !== null && range !== period.label
  return (
    <p className="u-note">
      <span className="font-medium text-ink">{period.label}</span>
      {showRange && <> · {range}</>}
      {period.note && <> · {period.note}</>}
    </p>
  )
}

export default PeriodSelect
