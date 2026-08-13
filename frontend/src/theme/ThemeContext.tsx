import { createContext, useContext, useEffect, type ReactNode } from 'react'

type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

/**
 * The product is dark, full stop.
 *
 * §23 specifies a single dark palette and the design tokens in `index.css` are
 * built on it, so a light mode no longer has a palette to render. The provider
 * is kept — charts still ask for the current theme to pick series colours — but
 * it is pinned, and the `.dark` class stays applied so the pages not yet moved
 * onto the new tokens keep rendering their dark variants rather than putting
 * white cards on a near-black ground.
 *
 * Retire this module once every page reads from the tokens directly.
 */
const THEME: Theme = 'dark'

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.classList.add('dark')
  }, [])

  return (
    <ThemeContext.Provider value={{ theme: THEME, toggleTheme: () => {} }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
