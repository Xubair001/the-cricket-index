import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Compare } from './pages/Compare'
import { Explorer } from './pages/Explorer'
import { Home } from './pages/Home'
import { PerformanceIndex } from './pages/PerformanceIndex'
import { Fixtures } from './pages/Fixtures'
import { IccRankings } from './pages/IccRankings'
import { MatchDetail } from './pages/MatchDetail'
import { Matches } from './pages/Matches'
import { PlayerDetail } from './pages/PlayerDetail'
import { Players } from './pages/Players'
import { Rankings } from './pages/Rankings'
import { TeamDetail } from './pages/TeamDetail'
import { Teams } from './pages/Teams'
import { GENDER_STORAGE_KEY } from './components/Layout'

function RootRedirect() {
  const stored = localStorage.getItem(GENDER_STORAGE_KEY)
  return <Navigate to={`/${stored === 'women' ? 'women' : 'men'}`} replace />
}

/**
 * There is no theme provider: §23 specifies a single dark palette, the tokens in
 * `index.css` are built on it, and every page now reads from those tokens. The
 * provider that used to pin the theme and apply a `.dark` class existed only to
 * keep un-migrated pages rendering their dark variants, and no `dark:` variant
 * survives in the app.
 */
function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/:gender" element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="rankings" element={<Rankings />} />
          <Route path="performance-index" element={<PerformanceIndex />} />
          <Route path="analytics" element={<Navigate to="batting" replace />} />
          <Route path="analytics/:explorer" element={<Explorer />} />
          <Route path="icc-rankings" element={<IccRankings />} />
          <Route path="compare" element={<Compare />} />
          <Route path="fixtures" element={<Fixtures />} />
          <Route path="teams" element={<Teams />} />
          <Route path="teams/:teamId" element={<TeamDetail />} />
          <Route path="players" element={<Players />} />
          <Route path="players/:identifier" element={<PlayerDetail />} />
          <Route path="matches" element={<Matches />} />
          <Route path="matches/:matchId" element={<MatchDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
