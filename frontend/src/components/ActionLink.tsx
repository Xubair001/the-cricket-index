import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowExternal, ArrowLeft, ArrowRight } from './Icon'

/**
 * A navigational action, as a button rather than a sentence with an arrow after
 * it.
 *
 * The pattern this replaces was a blue text link followed by a bare arrow -
 * "Compare with another player →". Three problems with it:
 *
 * - **It does not read as pressable.** Underlined-blue-plus-glyph is the 1998
 *   convention for "this is a link inside prose", and these are not inside
 *   prose: they are the action a reader takes next. A control that does
 *   something should look like a control.
 * - **The arrow floats.** A text glyph sits on the body baseline at the body
 *   weight, so it never aligns with the label it follows, and at small sizes it
 *   drifts visibly off-centre.
 * - **Nothing marks the hit area.** A four-word link is a four-word target; a
 *   button has padding, which is what makes it usable on a touch screen.
 *
 * Three weights, and the distinction is real rather than decorative:
 *
 *   primary    the one thing this page wants you to do next
 *   secondary  a real action, but one of several
 *   quiet      "see all of these" beside a section heading, where a filled
 *              button would outweigh the heading itself
 *
 * `back` and `external` swap the mark. External also gets `target=_blank` and
 * the rel guard, since that is always the intent when leaving the site.
 */

type Weight = 'primary' | 'secondary' | 'quiet'

const WEIGHTS: Record<Weight, string> = {
  primary:
    'bg-analytic text-white shadow-card hover:opacity-90 focus-visible:outline-analytic',
  secondary:
    'border border-border-default bg-surface text-ink shadow-card hover:border-border-strong hover:bg-elevated focus-visible:outline-analytic',
  quiet:
    'border border-transparent text-muted hover:border-border-default hover:bg-elevated hover:text-ink focus-visible:outline-analytic',
}

const BASE =
  'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium ' +
  'transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'

export function ActionLink({
  to,
  href,
  children,
  weight = 'secondary',
  direction = 'forward',
  className = '',
  title,
}: {
  /** An in-app route. Use `href` instead for anything off-site. */
  to?: string
  href?: string
  children: ReactNode
  weight?: Weight
  direction?: 'forward' | 'back' | 'external'
  className?: string
  title?: string
}) {
  const mark =
    direction === 'back' ? (
      <ArrowLeft />
    ) : direction === 'external' ? (
      <ArrowExternal />
    ) : (
      <ArrowRight />
    )
  const classes = `${BASE} ${WEIGHTS[weight]} ${className}`

  // The mark leads on a back action and trails on the others, which is the
  // direction of travel a reader already expects.
  const content =
    direction === 'back' ? (
      <>
        {mark}
        {children}
      </>
    ) : (
      <>
        {children}
        {mark}
      </>
    )

  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer external"
        className={classes}
        title={title}
      >
        {content}
      </a>
    )
  }
  return (
    <Link to={to ?? '.'} className={classes} title={title}>
      {content}
    </Link>
  )
}

export default ActionLink
