import type {
  ApiGender,
  BattingRankingRow,
  BowlingRankingRow,
  DashboardStats,
  ExplorerKind,
  ExplorerPage,
  FormLeaderboard,
  FormVerdict,
  HeadToHead,
  IccRankingTable,
  IccTeamRankingTable,
  MatchDetail,
  MatchSummary,
  Paginated,
  PaginatedFixtures,
  ParFigures,
  PerformanceIndexPage,
  PeriodOption,
  PlayerComparison,
  PlayerDetail,
  PlayerDirectory,
  PlayerSummary,
  SquadAnalysis,
  TeamDetail,
  TeamStrengthTable,
  TeamSummary,
  TeamType,
  VenueOption,
  VenueProfile,
} from './types'

async function getJson<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value))
    }
  }
  const res = await fetch(url.pathname + '?' + url.searchParams.toString())
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  dashboard: (gender: ApiGender) => getJson<DashboardStats>('/api/dashboard', { gender }),

  battingRankings: (
    gender: ApiGender,
    params: { competition?: string; min_matches?: number; sort_by?: string; limit?: number; offset?: number }
  ) => getJson<Paginated<BattingRankingRow>>('/api/rankings/batting', { gender, ...params }),

  bowlingRankings: (
    gender: ApiGender,
    params: { competition?: string; min_matches?: number; sort_by?: string; limit?: number; offset?: number }
  ) => getJson<Paginated<BowlingRankingRow>>('/api/rankings/bowling', { gender, ...params }),

  // team_type is optional: the Teams page scopes to one kind at a time, but
  // the Matches filter deliberately omits it so you can filter by any side.
  // Paginated server-side. `limit` is explicit at every call site rather than
  // defaulted here, because the two uses want opposite things: a browsing page
  // wants a page, and the Matches team filter wants every side to populate its
  // select.
  teams: (gender: ApiGender, teamType?: TeamType, params: { limit?: number; offset?: number } = {}) =>
    getJson<Paginated<TeamSummary>>('/api/teams', { gender, team_type: teamType, ...params }),

  teamDetail: (teamId: number) => getJson<TeamDetail>(`/api/teams/${teamId}`),

  teamSquad: (teamId: number, params: { window_matches?: number } = {}) =>
    getJson<SquadAnalysis>(`/api/teams/${teamId}/squad`, params),

  headToHead: (teamAId: number, teamBId: number) =>
    getJson<HeadToHead>(`/api/teams/${teamAId}/head-to-head/${teamBId}`),

  players: (gender: ApiGender, params: { search?: string; limit?: number; offset?: number }) =>
    getJson<Paginated<PlayerSummary>>('/api/players', { gender, ...params }),

  playerDetail: (identifier: string) =>
    getJson<PlayerDetail>(`/api/players/${encodeURIComponent(identifier)}`),

  // Form is a separate call from the profile on purpose: it is the expensive
  // half, and it answers a different question (Rule 3 -- form is not career).
  playerForm: (
    identifier: string,
    params: {
      recent?: number
      baseline_days?: number
      competition?: string
      competition_type?: string
    } = {}
  ) => getJson<FormVerdict>(`/api/players/${encodeURIComponent(identifier)}/form`, params),

  // Ranks *change*, not standard -- deliberately beside the batting/bowling
  // rankings rather than replacing them.
  formLeaderboard: (
    gender: ApiGender,
    params: {
      state?: string
      trend?: string
      competition?: string
      competition_type?: string
      limit?: number
      offset?: number
    } = {}
  ) => getJson<FormLeaderboard>('/api/rankings/form', { gender, ...params }),

  // The discovery surface. Rate sorts apply a default qualification server-side
  // (300 balls bowled / 200 faced) so "best economy" isn't a batter who bowled
  // two balls; pass min_balls_* to raise or explicitly lower it.
  playerDirectory: (
    gender: ApiGender,
    params: {
      search?: string
      competition?: string
      competition_type?: string
      team_id?: number
      min_matches?: number
      min_balls_faced?: number
      min_balls_bowled?: number
      status?: string
      form_state?: string
      sort_by?: string
      limit?: number
      offset?: number
    } = {}
  ) => getJson<PlayerDirectory>('/api/players/directory', { gender, ...params }),

  periods: () => getJson<PeriodOption[]>('/api/analytics/periods'),

  parFigures: () => getJson<ParFigures[]>('/api/analytics/par'),

  matches: (
    gender: ApiGender,
    params: {
      competition?: string
      team_id?: number
      season?: string
      search?: string
      limit?: number
      offset?: number
    }
  ) => getJson<Paginated<MatchSummary>>('/api/matches', { gender, ...params }),

  matchDetail: (matchId: string) => getJson<MatchDetail>(`/api/matches/${encodeURIComponent(matchId)}`),

  comparePlayers: (
    a: string,
    b: string,
    params: { competition?: string; competition_type?: string } = {}
  ) => getJson<PlayerComparison>('/api/players/compare', { a, b, ...params }),

  // The explorers (§21). Every filter, sort and page is applied server-side -
  // the unfiltered population is ~5,400 players, and sorting a page of them in
  // the browser would give a different answer from the ranking endpoints.
  explorer: (
    explorer: ExplorerKind,
    gender: ApiGender,
    params: {
      competition?: string
      competition_type?: string
      team_id?: number
      opposition_team_id?: number
      date_from?: string
      date_to?: string
      min_innings?: number
      min_balls?: number
      role?: string
      venue?: string
      sort_by?: string
      limit?: number
      offset?: number
    } = {}
  ) => getJson<ExplorerPage>(`/api/analytics/${explorer}`, { gender, ...params }),

  // The Performance Index (§14). Always returns its own decomposition - a
  // score without its components is not usable by someone who has to defend
  // the decision it informs (§30).
  performanceIndex: (
    gender: ApiGender,
    params: { competition?: string; role?: string; limit?: number; offset?: number } = {}
  ) => getJson<PerformanceIndexPage>('/api/rankings/performance', { gender, ...params }),

  // Canonical grounds - Cricsheet files one ground under several
  // spellings, so this is the normalised list, not SELECT DISTINCT venue.
  venues: (gender?: ApiGender) =>
    getJson<VenueOption[]>('/api/analytics/venues', { gender }),

  // One ground's character (§20). The name is canonical, and may carry a
  // parenthesised city for the handful that exist in several places.
  venueProfile: (venue: string, gender: ApiGender, competition?: string) =>
    getJson<VenueProfile>(`/api/analytics/venues/${encodeURIComponent(venue)}`, {
      gender,
      competition,
    }),

  // Fitted opposition difficulty - the model that scales every adjusted
  // figure elsewhere. Exposed so a reader can check the adjustment (§30).
  teamStrength: (gender: ApiGender, competitionType?: string) =>
    getJson<TeamStrengthTable>('/api/analytics/opposition', {
      gender,
      competition_type: competitionType,
    }),

  iccRankTypes: () => getJson<{ players: string[]; teams: string[] }>('/api/icc/rank-types'),

  iccPlayerRanking: (rankType: string, params: { limit?: number; offset?: number } = {}) =>
    getJson<IccRankingTable>(`/api/icc/players/${encodeURIComponent(rankType)}`, params),

  iccTeamRanking: (rankType: string, params: { limit?: number; offset?: number } = {}) =>
    getJson<IccTeamRankingTable>(`/api/icc/teams/${encodeURIComponent(rankType)}`, params),

  fixtures: (params: {
    gender?: string
    window?: string
    match_type?: string
    limit?: number
    offset?: number
  }) => getJson<PaginatedFixtures>('/api/fixtures', params),

  fixtureMatchTypes: (gender?: string) =>
    getJson<{ match_types: string[] }>('/api/fixtures/match-types', { gender }),
}
