import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// §23 names Inter / Geist / IBM Plex Sans, and the stack in index.css asked for
// them — but nothing shipped them, so every machine without Inter installed
// (which is most, including this one) silently rendered system-ui instead.
// Self-hosted rather than pulled from a CDN: no third-party request on load,
// and the product keeps its typography offline.
import '@fontsource-variable/inter'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
