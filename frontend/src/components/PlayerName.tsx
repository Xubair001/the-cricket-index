import { Link } from 'react-router-dom'
import { Flag } from './Flag'

/**
 * A player's name with the flag of the side they represent.
 *
 * The flag means exactly what it means beside a team name - the nation they
 * turn out for - because it is resolved from their own appearances rather than
 * from a citizenship field. Three cases it has to carry without lying:
 *
 * - **No national side.** Franchise-only players (1,247 in this dataset, mostly
 *   PSL) get the neutral mark, the same as a franchise team does. Nothing is
 *   inferred from where the league is played.
 * - **A side with no flag.** The West Indies is a real side with no ISO code,
 *   so it draws the neutral mark but still names itself on hover.
 * - **Switchers.** Someone who represented two nations shows the most recent,
 *   which is a sourced fact rather than a guess at allegiance.
 *
 * The mark occupies a fixed width in all three cases, so a column of names
 * stays aligned whether or not each player has a flag.
 */
export function PlayerName({
  name,
  country,
  countryCode,
  to,
  className = '',
  nameClassName = '',
}: {
  name: string
  country?: string | null
  countryCode?: string | null
  /** Renders as a link when given, plain text otherwise. */
  to?: string
  className?: string
  nameClassName?: string
}) {
  const body = (
    <>
      <Flag code={countryCode} name={country ?? undefined} />
      <span className={`truncate ${nameClassName}`}>{name}</span>
    </>
  )

  const shared = `inline-flex min-w-0 items-center gap-1.5 ${className}`

  if (to) {
    return (
      <Link to={to} className={`${shared} hover:text-analytic-ink`}>
        {body}
      </Link>
    )
  }
  return <span className={shared}>{body}</span>
}
