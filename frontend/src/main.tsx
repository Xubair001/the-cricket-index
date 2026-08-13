import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// §23 names Inter / Geist / IBM Plex Sans, and the stack in index.css asked for
// them — but nothing shipped them, so every machine without Inter installed
// (which is most, including this one) silently rendered system-ui instead.
// Self-hosted rather than pulled from a CDN: no third-party request on load,
// and the product keeps its typography offline.
import '@fontsource-variable/inter'
// The `wdth` stylesheet rather than the default one: Archivo's width axis is
// the whole reason it is the display face here, and the default build ships
// weight only, so `font-stretch: 112%` would silently do nothing.
import '@fontsource-variable/archivo/wdth.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import './index.css'
import App from './App.tsx'
import { applyPreference, readStoredPreference } from './theme/useTheme'

// The inline script in index.html already did this before first paint; this
// re-applies it from the same source of truth so the two can't drift, and
// covers the case where the bundle is mounted into a page without it.
applyPreference(readStoredPreference())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
