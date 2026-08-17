import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useGender, type GenderSlug } from '../gender/useGender'
import { ThemeToggle } from './ThemeToggle'

/**
 * The application shell.
 *
 * Navigation follows the scope's information architecture (§5) rather than the
 * flat list of pages that happen to exist. Sections that are not built yet stay
 * visible but are marked and unclickable, with the reason attached: the IA is
 * the product's shape, and hiding the parts that are gated on data would make
 * the roadmap invisible while quietly implying the product is complete. A dead
 * link that 404s would be worse than either.
 *
 * The chrome is a left rail rather than the row of eight hover-menus it
 * replaced. Eight dropdowns over ~30 destinations meant the whole IA was
 * invisible until you hovered the right word, every section was two gestures
 * away, and none of it was reachable on a touch screen. A rail shows the
 * structure at rest. Groups collapse so the list stays a screenful, and the
 * group holding the current page opens itself.
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
      { label: 'In Form', to: 'form/in-form' },
      { label: 'Rising Players', to: 'form/rising' },
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
      // Unblocked by inferring role from each player's share of deliveries in
      // the window rather than waiting for a sourced role, which no available
      // feed carries. The page labels every role as inferred and states what
      // still cannot be derived (wicketkeeper, batting position, handedness).
      { label: 'Squad Analysis', to: 'teams/squad' },
    ],
  },
  {
    label: 'Rankings',
    items: [
      { label: 'Performance Rankings', to: 'rankings' },
      // Shipped, so the 'Phase 2 — see the scope document' stub that used to
      // sit at the end of this group is gone. Leaving both meant the group
      // listed Performance Index twice, once as a link and once as blocked.
      { label: 'Performance Index', to: 'performance-index' },
      { label: 'ICC Rankings', to: 'icc-rankings' },
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
      { label: 'Batting Explorer', to: 'analytics/batting' },
      { label: 'Bowling Explorer', to: 'analytics/bowling' },
      { label: 'All-Round Explorer', to: 'analytics/allround' },
      { label: 'Venue Analytics', to: 'analytics/venues' },
      { label: 'Opposition Analytics', to: 'analytics/opposition' },
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

/**
 * Which group holds the current path, so it can open itself on arrival.
 *
 * Longest match wins: 'analytics' and 'analytics/batting' both prefix-match a
 * batting-explorer URL, and picking the first would open whichever group
 * happened to be declared earlier rather than the more specific one.
 */
function activeGroupLabel(pathname: string, slug: string): string | null {
  let best: { label: string; length: number } | null = null
  for (const group of NAV) {
    for (const item of group.items) {
      if (!item.to) continue
      const full = `/${slug}/${item.to}`
      if (pathname === full || pathname.startsWith(`${full}/`)) {
        if (!best || item.to.length > best.length) {
          best = { label: group.label, length: item.to.length }
        }
      }
    }
  }
  return best?.label ?? null
}

function NavSection({
  group,
  slug,
  open,
  onToggle,
}: {
  group: NavGroup
  slug: string
  open: boolean
  onToggle: () => void
}) {
  const built = group.items.filter((i) => i.to).length

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-elevated"
      >
        <svg
          viewBox="0 0 12 12"
          aria-hidden
          className={`h-2.5 w-2.5 shrink-0 text-dim transition-transform ${open ? 'rotate-90' : ''}`}
        >
          <path d="M4 2.5 8 6l-4 3.5z" fill="currentColor" />
        </svg>
        <span className="u-eyebrow flex-1">{group.label}</span>
        {/* How much of this section actually exists. Without it a collapsed
            group looks complete, which is the impression the blocked items are
            there to prevent. */}
        <span className="tnum font-mono text-[9px] text-dim">
          {built}/{group.items.length}
        </span>
      </button>

      {open && (
        <ul className="mb-1 ml-3.5 mt-0.5 space-y-px border-l border-border-subtle pl-2">
          {group.items.map((item) => (
            <li key={`${group.label}-${item.label}`}>
              {item.to ? (
                <NavLink
                  to={`/${slug}/${item.to}`}
                  end
                  className={({ isActive }) =>
                    `block rounded-md px-2.5 py-1.5 text-[13px] transition-colors ${
                      isActive
                        ? 'bg-analytic-dim font-medium text-analytic-ink'
                        : 'text-muted hover:bg-elevated hover:text-ink'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ) : (
                <span
                  aria-disabled="true"
                  title={item.blocked}
                  className="flex cursor-not-allowed items-baseline justify-between gap-2 rounded-md px-2.5 py-1.5 text-[13px] text-dim"
                >
                  <span className="truncate">{item.label}</span>
                  <span className="shrink-0 rounded bg-warning-dim px-1 py-px font-mono text-[9px] uppercase tracking-[0.08em] text-warning-ink">
                    soon
                  </span>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Brand({ slug }: { slug: string }) {
  return (
    <NavLink to={`/${slug}`} className="flex items-center gap-2.5">
      {/* The mark is the par datum the product is built on: two bars either
          side of the 1.00 line, the same device as the meters on the form
          boards. The line sits off-centre deliberately — centred with equal
          bars it read as a plus sign rather than as a scale. */}
      <span aria-hidden className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-ink">
        <svg viewBox="0 0 20 20" className="h-4 w-4">
          <rect x="2.4" y="4.6" width="4" height="3" rx="1.5" fill="var(--color-surface)" opacity="0.5" />
          <rect x="9.4" y="12.4" width="8.2" height="3" rx="1.5" fill="var(--color-surface)" opacity="0.92" />
          <rect x="7.4" y="2.4" width="1.5" height="15.2" rx="0.75" fill="var(--color-surface)" />
        </svg>
      </span>
      <span className="min-w-0">
        <span className="u-display block truncate text-[15px] leading-tight text-ink">
          The Cricket Index
        </span>
        <span className="block font-mono text-[9px] uppercase tracking-[0.14em] text-dim">
          Derived from ball-by-ball
        </span>
      </span>
    </NavLink>
  )
}

export function Layout() {
  const { slug } = useGender()
  const location = useLocation()
  const navigate = useNavigate()

  // Falls back to the first group rather than to nothing. The dashboard itself
  // matches no nav item, so an unqualified null left the whole rail collapsed
  // on the one page every session starts from — eight closed rows and no sign
  // of what the product contains.
  const [openGroup, setOpenGroup] = useState<string | null>(
    () => activeGroupLabel(location.pathname, slug) ?? NAV[0].label
  )
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Arriving on a page from anywhere -- a link on the dashboard, a shared URL,
  // the back button -- opens the section that page lives in, so the rail always
  // shows where you are rather than where you last clicked.
  useEffect(() => {
    const active = activeGroupLabel(location.pathname, slug)
    if (active) setOpenGroup(active)
  }, [location.pathname, slug])

  // The mobile drawer covers the page, so it must not survive navigation.
  useEffect(() => setDrawerOpen(false), [location.pathname])

  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawerOpen(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawerOpen])

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

  const rail = (
    <div className="flex h-full flex-col">
      <div className="border-b border-border-subtle px-4 py-4">
        <Brand slug={slug} />
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Sections">
        <div className="space-y-0.5">
          {NAV.map((group) => (
            <NavSection
              key={group.label}
              group={group}
              slug={slug}
              open={openGroup === group.label}
              onToggle={() =>
                setOpenGroup((current) => (current === group.label ? null : group.label))
              }
            />
          ))}
        </div>
      </nav>

      <div className="border-t border-border-subtle px-4 py-3">
        {/* Deliberately not "international cricket" any more -- the dataset now
            also carries franchise cricket (PSL), and naming the competitions
            here would just be a second place to update per league. */}
        <p className="text-[11px] leading-relaxed text-dim">
          Data from{' '}
          <a
            href="https://cricsheet.org"
            className="text-muted underline decoration-border-strong underline-offset-2 hover:text-ink"
          >
            Cricsheet.org
          </a>{' '}
          under ODC-BY 1.0. Derived figures are computed here, not published ratings.
        </p>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-ground">
      {/* Skip link: the rail is ~30 focusable items deep, so a keyboard user
          would otherwise tab through the whole IA to reach the page. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:text-ink focus:shadow-menu"
      >
        Skip to content
      </a>

      {/* Rail -- persistent from lg up. */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] border-r border-border-subtle bg-surface lg:block">
        {rail}
      </aside>

      {/* Rail -- drawer below lg. */}
      {drawerOpen && (
        <>
          <button
            aria-label="Close navigation"
            onClick={() => setDrawerOpen(false)}
            className="fixed inset-0 z-30 bg-ink/40 backdrop-blur-[2px] lg:hidden"
          />
          <aside className="fixed inset-y-0 left-0 z-40 w-[268px] border-r border-border-subtle bg-surface shadow-menu lg:hidden">
            {rail}
          </aside>
        </>
      )}

      <div className="lg:pl-[248px]">
        <header className="sticky top-0 z-20 border-b border-border-subtle bg-ground/85 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5 sm:px-6">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-label="Open navigation"
              className="-ml-1 rounded-lg p-2 text-muted transition-colors hover:bg-elevated hover:text-ink lg:hidden"
            >
              <svg viewBox="0 0 16 16" aria-hidden className="h-4 w-4">
                <path
                  d="M2 4h12M2 8h12M2 12h12"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>

            <div className="flex flex-1 items-center gap-2 lg:hidden">
              <Brand slug={slug} />
            </div>
            <div className="hidden flex-1 lg:block" />

            {/* Gender is a hard split in the schema, not a filter -- men's and
                women's cricket share no identity below the API layer -- so the
                control sits in the chrome rather than on each page. */}
            <div
              role="radiogroup"
              aria-label="Cricket"
              className="flex rounded-lg border border-border-default bg-surface p-0.5"
            >
              {(['men', 'women'] as const).map((g) => (
                <button
                  key={g}
                  role="radio"
                  aria-checked={slug === g}
                  onClick={() => switchGender(g)}
                  className={`rounded-md px-2.5 py-1 text-[13px] font-medium transition-colors ${
                    slug === g
                      ? 'bg-elevated text-ink shadow-card ring-1 ring-border-default'
                      : 'text-dim hover:text-ink'
                  }`}
                >
                  {g === 'men' ? "Men's" : "Women's"}
                </button>
              ))}
            </div>

            <ThemeToggle />
          </div>
        </header>

        <main id="main" className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export { GENDER_STORAGE_KEY }
