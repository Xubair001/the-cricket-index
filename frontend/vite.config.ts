import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The backend's dev port. Overridable because more than one API can be up at
// once on this machine - a second checkout, or a reviewer running the API on a
// spare port to compare against the one already serving 8001 - and a hardcoded
// target silently proxies to whichever process got there first.
//
//   VITE_API_TARGET=http://127.0.0.1:8009 npm run dev -- --port 5174
//
// Dev-server only. A production build talks to whatever origin serves it.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8001'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
