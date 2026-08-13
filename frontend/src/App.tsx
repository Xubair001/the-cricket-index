import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Compare } from './pages/Compare'
import { Dashboard } from './pages/Dashboard'
import { Fixtures } from './pages/Fixtures'
import { IccRankings } from './pages/IccRankings'
import { MatchDetail } from './pages/MatchDetail'
import { Matches } from './pages/Matches'
import { PlayerDetail } from './pages/PlayerDetail'
import { Players } from './pages/Players'
import { Rankings } from './pages/Rankings'
import { TeamDetail } from './pages/TeamDetail'
import { Teams } from './pages/Teams'
import { ThemeProvider } from './theme/ThemeContext'
import { GENDER_STORAGE_KEY } from './components/Layout'

function RootRedirect() {
  const stored = localStorage.getItem(GENDER_STORAGE_KEY)
  return <Navigate to={`/${stored === 'women' ? 'women' : 'men'}`} replace />
}

function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<RootRedirect />} />
          <Route path="/:gender" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="rankings" element={<Rankings />} />
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
    </ThemeProvider>
  )
}

export default App
