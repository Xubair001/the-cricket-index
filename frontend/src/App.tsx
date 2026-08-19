import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ScopeProvider } from './scope/ScopeProvider'
import { Compare } from './pages/Compare'
import { Explorer } from './pages/Explorer'
import { VenueAnalytics } from './pages/VenueAnalytics'
import { OppositionAnalytics } from './pages/OppositionAnalytics'
import { Availability } from './pages/Availability'
import { BestXI } from './pages/BestXI'
import { FormBoards } from './pages/FormBoards'
import { Home } from './pages/Home'
import { PerformanceIndex } from './pages/PerformanceIndex'
import { Fixtures } from './pages/Fixtures'
import { IccRankings } from './pages/IccRankings'
import { MatchDetail } from './pages/MatchDetail'
import { MatchIntelligence } from './pages/MatchIntelligence'
import { Matches } from './pages/Matches'
import { News } from './pages/News'
import { NewsArticle } from './pages/NewsArticle'
import { PlayerDetail } from './pages/PlayerDetail'
import { Players } from './pages/Players'
import { Rankings } from './pages/Rankings'
import { Scout } from './pages/Scout'
import { SquadAnalysis } from './pages/SquadAnalysis'
import { TeamDetail } from './pages/TeamDetail'
import { Teams } from './pages/Teams'
import { Underrated } from './pages/Underrated'
import { Tournaments } from './pages/Tournaments'
import { TournamentDetail } from './pages/TournamentDetail'
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
      <ScopeProvider>
      <Routes>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/:gender" element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="form" element={<Navigate to="in-form" replace />} />
          <Route path="form/:board" element={<FormBoards />} />
          <Route path="best-xi" element={<BestXI />} />
          <Route path="rankings" element={<Rankings />} />
          <Route path="performance-index" element={<PerformanceIndex />} />
          <Route path="analytics" element={<Navigate to="batting" replace />} />
          <Route path="analytics/venues" element={<VenueAnalytics />} />
          <Route path="analytics/opposition" element={<OppositionAnalytics />} />
          <Route path="analytics/:explorer" element={<Explorer />} />
          <Route path="icc-rankings" element={<IccRankings />} />
          <Route path="underrated" element={<Underrated />} />
          <Route path="compare" element={<Compare />} />
          <Route path="fixtures" element={<Fixtures />} />
          <Route path="tournaments" element={<Tournaments />} />
          <Route path="tournaments/:tournament" element={<TournamentDetail />} />
          <Route path="news" element={<News />} />
          <Route path="news/:articleId" element={<NewsArticle />} />
          <Route path="availability" element={<Availability />} />
          <Route path="scout" element={<Scout />} />
          <Route path="teams" element={<Teams />} />
          {/* Before "teams/:teamId", or 'squad' is read as a team id. */}
          <Route path="teams/squad" element={<SquadAnalysis />} />
          <Route path="teams/:teamId" element={<TeamDetail />} />
          <Route path="players" element={<Players />} />
          <Route path="players/:identifier" element={<PlayerDetail />} />
          <Route path="matches" element={<Matches />} />
          <Route path="matches/:matchId" element={<MatchDetail />} />
          <Route path="matches/:matchId/intelligence" element={<MatchIntelligence />} />
        </Route>
      </Routes>
      </ScopeProvider>
    </BrowserRouter>
  )
}

export default App
