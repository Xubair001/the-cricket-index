import { useCallback, useEffect, useState } from 'react'

/**
 * Theme preference.
 *
 * Three states rather than two. A boolean toggle forces a choice the moment
 * someone touches it and then ignores their OS for good; `system` is the
 * default and stays live, so a machine that switches to dark in the evening
 * takes the product with it. Choosing light or dark explicitly pins it.
 *
 * The resolved theme is written to `<html data-theme>`, which `index.css`
 * keys both palettes off. `system` writes no attribute at all and lets the
 * `prefers-color-scheme` block in that file decide — the attribute is the
 * override, not the mechanism.
 */
export type ThemePreference = 'system' | 'light' | 'dark'

export const THEME_STORAGE_KEY = 'cricket-dashboard-theme'

function isPreference(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark'
}

export function readStoredPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return isPreference(stored) ? stored : 'system'
  } catch {
    // Safari in private mode throws on localStorage access rather than
    // returning null. A theme preference is not worth a blank page.
    return 'system'
  }
}

/**
 * Applies a preference to the document.
 *
 * Exported because `main.tsx` runs it before React mounts: applying it in an
 * effect means the first paint uses the default palette and then swaps, which
 * is the white flash every themed app is judged on.
 */
export function applyPreference(preference: ThemePreference) {
  const root = document.documentElement
  if (preference === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', preference)
}

export function useTheme() {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference)

  // Tracked so the toggle can label the `system` option with what it currently
  // resolves to, rather than leaving the reader to guess.
  const [systemIsDark, setSystemIsDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches
  )

  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setSystemIsDark(e.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const setPreference = useCallback((next: ThemePreference) => {
    // Colours animate only around a deliberate change. The class is added for
    // the duration of the swap and removed after, so nothing transitions on
    // page load — where it would read as the page failing to settle.
    const root = document.documentElement
    root.classList.add('theme-transition')
    window.setTimeout(() => root.classList.remove('theme-transition'), 220)

    applyPreference(next)
    setPreferenceState(next)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // Preference just doesn't persist. The UI is already correct.
    }
  }, [])

  const resolved: 'light' | 'dark' =
    preference === 'system' ? (systemIsDark ? 'dark' : 'light') : preference

  return { preference, setPreference, resolved, systemIsDark }
}
