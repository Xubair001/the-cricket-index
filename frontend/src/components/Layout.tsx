import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'
import { useGender, type GenderSlug } from '../gender/useGender'

const NAV_LINKS = [
  { to: '', label: 'Dashboard' },
  { to: 'rankings', label: 'Rankings' },
  { to: 'teams', label: 'Teams' },
  { to: 'players', label: 'Players' },
  { to: 'matches', label: 'Matches' },
]

const GENDER_STORAGE_KEY = 'cricket-dashboard-gender'

function linkClass({ isActive }: { isActive: boolean }) {
  return [
    'rounded-md px-3 py-2 text-sm font-medium transition-colors',
    isActive
      ? 'bg-emerald-600 text-white'
      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white',
  ].join(' ')
}

export function Layout() {
  const { theme, toggleTheme } = useTheme()
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
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3">
          <NavLink to={`/${slug}`} className="flex items-center gap-2 text-lg font-bold text-slate-900 dark:text-white">
            <span className="text-2xl">🏏</span>
            The Cricket Index
          </NavLink>

          <div className="flex rounded-md bg-slate-100 p-0.5 dark:bg-slate-800">
            <button
              onClick={() => switchGender('men')}
              className={`rounded-[5px] px-3 py-1 text-sm font-medium transition-colors ${
                slug === 'men'
                  ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              Men's
            </button>
            <button
              onClick={() => switchGender('women')}
              className={`rounded-[5px] px-3 py-1 text-sm font-medium transition-colors ${
                slug === 'women'
                  ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              Women's
            </button>
          </div>

          <nav className="flex flex-1 gap-1 overflow-x-auto">
            {NAV_LINKS.map((link) => (
              <NavLink key={link.to} to={`/${slug}/${link.to}`} className={linkClass} end>
                {link.label}
              </NavLink>
            ))}
          </nav>
          <button
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-300 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {theme === 'dark' ? '☀️' : '🌙'}
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl px-4 py-8 text-center text-xs text-slate-400 dark:text-slate-600">
        {/* Deliberately not "international cricket" any more -- the dataset now
            also carries franchise cricket (PSL), and naming the competitions
            here would just be a second place to update per league. The
            dashboard's per-competition breakdown is the accurate answer. */}
        Data from Cricsheet.org (ODC-BY 1.0) &middot; {slug === 'men' ? "Men's" : "Women's"} cricket
      </footer>
    </div>
  )
}

export { GENDER_STORAGE_KEY }
