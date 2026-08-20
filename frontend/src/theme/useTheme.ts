import { useCallback, useSyncExternalStore } from 'react'

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
 * `prefers-color-scheme` block in that file decide - the attribute is the
 * override, not the mechanism.
 *
 * State lives in a module-level store rather than in each hook call. With
 * per-instance `useState`, the toggle would update its own copy and nothing
 * else: the charts, which read resolved colours out of the stylesheet when the
 * theme changes, would keep the palette they were mounted with until something
 * unrelated re-rendered them.
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

/* ── Store ─────────────────────────────────────────────────── */

const listeners = new Set<() => void>()
let preference: ThemePreference = readStoredPreference()
let systemIsDark = window.matchMedia('(prefers-color-scheme: dark)').matches

function emit() {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

// A `system` preference has to react to the OS changing under it, so the
// query is watched for the lifetime of the page rather than per component.
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
  systemIsDark = e.matches
  emit()
})

// Another tab of the same product changing the theme should not leave this one
// on the old palette.
window.addEventListener('storage', (e) => {
  if (e.key !== THEME_STORAGE_KEY) return
  const next = isPreference(e.newValue) ? e.newValue : 'system'
  if (next === preference) return
  preference = next
  applyPreference(next)
  emit()
})

/**
 * The snapshot is cached rather than rebuilt per call: `useSyncExternalStore`
 * compares snapshots by identity, and returning a fresh object each time is an
 * infinite render loop.
 */
let snapshot = { preference, systemIsDark, resolved: resolve(preference, systemIsDark) }

function resolve(pref: ThemePreference, dark: boolean): 'light' | 'dark' {
  return pref === 'system' ? (dark ? 'dark' : 'light') : pref
}

function refreshSnapshot() {
  snapshot = { preference, systemIsDark, resolved: resolve(preference, systemIsDark) }
}

listeners.add(refreshSnapshot)

function getSnapshot() {
  return snapshot
}

function set(next: ThemePreference) {
  if (next === preference) return
  // Colours animate only around a deliberate change. The class is added for
  // the duration of the swap and removed after, so nothing transitions on page
  // load - where it would read as the page failing to settle.
  const root = document.documentElement
  root.classList.add('theme-transition')
  window.setTimeout(() => root.classList.remove('theme-transition'), 220)

  preference = next
  applyPreference(next)
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next)
  } catch {
    // Preference just doesn't persist. The UI is already correct.
  }
  emit()
}

/* ── Hook ──────────────────────────────────────────────────── */

export function useTheme() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  const setPreference = useCallback((next: ThemePreference) => set(next), [])
  return { ...state, setPreference }
}
