import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useGender, type GenderSlug } from '../gender/useGender'

/**
 * The application shell.
 *
 * Navigation follows the scope's information architecture (§5) rather than the
 * flat list of pages that happen to exist. Sections that are not built yet stay
 * visible but are marked and unclickable, with the reason attached: the IA is
 * the product's shape, and hiding the parts that are gated on data would make
 * the roadmap invisible while quietly implying the product is complete. A dead
 * link that 404s would be worse than either.
 */

const GENDER_STORAGE_KEY = 'cricket-dashboard-gender'

type NavItem = {
  label: string
  to?: string
  /** Why this isn't available yet. Present means the item is not navigable. */
  blocked?: string
}

type NavGroup = { label: string; items: NavItem[] }

const NAV: NavGroup[] = [
  {
    label: 'Discover',
    items: [
      { label: 'Players', to: 'players' },
      { label: 'Teams', to: 'teams' },
      { label: 'In Form', blocked: 'Needs the form engine wired to a leaderboard' },
      { label: 'Rising Players', blocked: 'Needs the form engine wired to a leaderboard' },
      { label: 'Best XI', blocked: 'Needs player role and wicketkeeper data' },
    ],
  },
  {
    label: 'Players',
    items: [
      { label: 'Player Directory', to: 'players' },
      { label: 'Compare Players', to: 'compare' },
    ],
  },
  {
    label: 'Teams',
    items: [
      { label: 'Team Directory', to: 'teams' },
      { label: 'Squad Analysis', blocked: 'Needs player role data' },
    ],
  },
  {
    label: 'Rankings',
    items: [
      { label: 'Performance Rankings', to: 'rankings' },
      { label: 'ICC Rankings', to: 'icc-rankings' },
      { label: 'Performance Index', blocked: 'Phase 2 — see the scope document' },
    ],
  },
  {
    label: 'Fixtures',
    items: [
      { label: 'Fixture Calendar', to: 'fixtures' },
      { label: 'Player Availability', blocked: 'Needs squad lists; no franchise fixtures in the feed' },
    ],
  },
  {
    label: 'Analytics',
    items: [
      { label: 'Batting Explorer', blocked: 'Next up' },
      { label: 'Bowling Explorer', blocked: 'Next up' },
      { label: 'Venue Analytics', blocked: 'Needs venue normalisation' },
      { label: 'Opposition Analytics', blocked: 'Next up' },
    ],
  },
  {
    label: 'Matches',
    items: [
      { label: 'Results', to: 'matches' },
      { label: 'Match Analysis', blocked: 'Needs ball-by-ball data' },
    ],
  },
  {
    label: 'Scout',
    items: [
      { label: 'Find a Player', blocked: 'Needs role, handedness and availability data' },
      { label: 'Build a XI', blocked: 'Needs role and wicketkeeper data' },
      { label: 'Compare Candidates', to: 'compare' },
    ],
  },
]

function NavGroupMenu({ group, slug }: { group: NavGroup; slug: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const location = useLocation()

  // Close on outside click and on navigation, so the menu never persists over
  // the page the user just moved to.
  useEffect(() => setOpen(false), [location.pathname])
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const groupIsActive = group.items.some(
    (i) => i.to && location.pathname === `/${slug}/${i.to}`
  )

  return (
    <div
      ref={ref}
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        aria-expanded={open}
        aria-haspopup="menu"
        className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
          groupIsActive ? 'bg-elevated text-ink' : 'text-muted hover:bg-elevated hover:text-ink'
        }`}
      >
        {group.label}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full z-20 min-w-[248px] rounded-lg border border-border-default bg-elevated py-1.5 shadow-xl shadow-black/40"
        >
          {group.items.map((item) =>
            item.to ? (
              <NavLink
                key={item.label}
                to={`/${slug}/${item.to}`}
                role="menuitem"
                className={({ isActive }) =>
                  `block px-3.5 py-2 text-sm transition-colors ${
                    isActive ? 'text-analytic' : 'text-ink hover:bg-surface'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ) : (
              <div
                key={item.label}
                role="menuitem"
                aria-disabled="true"
                title={item.blocked}
                className="cursor-not-allowed px-3.5 py-2 text-sm text-dim"
              >
                <span className="flex items-baseline justify-between gap-3">
                  {item.label}
                  <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-warning">
                    soon
                  </span>
                </span>
              </div>
            )
          )}
        </div>
      )}
    </div>
  )
}

export function Layout() {
  const { slug } = useGender()
  const location = useLocation()
  const navigate = useNavigate()

  function switchGender(next: GenderSlug) {
    localStorage.setItem(GENDER_STORAGE_KEY, next)
    // A detail page's ID (team_id, match_id) is meaningless in the other
    // gender's context, so only carry over the section (teams/players/...),
    // not a specific record -- switching genders on a detail page lands you
    // on that section's list instead of a broken/foreign detail page.
    const parts = location.pathname.split('/').filter(Boolean) // [gender, section?, id?]
    const section = parts[1] ?? ''
    navigate(`/${next}/${section}`)
  }

  return (
    <div className="min-h-screen bg-ground">
      <header className="sticky top-0 z-10 border-b border-border-default bg-ground/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <NavLink
            to={`/${slug}`}
            className="flex items-baseline gap-2 text-base font-semibold tracking-tight text-ink"
          >
            The Cricket Index
            <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-analytic">
              Intelligence
            </span>
          </NavLink>

          <div className="flex rounded-md border border-border-default bg-surface p-0.5">
            {(['men', 'women'] as const).map((g) => (
              <button
                key={g}
                onClick={() => switchGender(g)}
                aria-pressed={slug === g}
                className={`rounded-[5px] px-3 py-1 text-sm font-medium transition-colors ${
                  slug === g ? 'bg-elevated text-ink' : 'text-muted hover:text-ink'
                }`}
              >
                {g === 'men' ? "Men's" : "Women's"}
              </button>
            ))}
          </div>

          <nav className="flex flex-1 flex-wrap items-center gap-0.5">
            {NAV.map((group) => (
              <NavGroupMenu key={group.label} group={group} slug={slug} />
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-7xl px-4 py-8 text-center text-xs text-dim">
        {/* Deliberately not "international cricket" any more -- the dataset now
            also carries franchise cricket (PSL), and naming the competitions
            here would just be a second place to update per league. */}
        Data from Cricsheet.org (ODC-BY 1.0) &middot;{' '}
        {slug === 'men' ? "Men's" : "Women's"} cricket &middot; Derived figures are computed here,
        not published ratings
      </footer>
    </div>
  )
}

export { GENDER_STORAGE_KEY }
