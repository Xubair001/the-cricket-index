import type {
  ApiGender,
  BattingRankingRow,
  BowlingRankingRow,
  DashboardStats,
  HeadToHead,
  IccRankingTable,
  IccTeamRankingTable,
  MatchDetail,
  PaginatedFixtures,
  PlayerComparison,
  MatchSummary,
  Paginated,
  PlayerDetail,
  PlayerSummary,
  TeamDetail,
  TeamSummary,
  TeamType,
  FormVerdict,
  PeriodOption,
  ParFigures,
  FormLeaderboard,
  PlayerDirectory,
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
  teams: (gender: ApiGender, teamType?: TeamType) =>
    getJson<TeamSummary[]>('/api/teams', { gender, team_type: teamType }),

  teamDetail: (teamId: number) => getJson<TeamDetail>(`/api/teams/${teamId}`),

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

  iccRankTypes: () => getJson<{ players: string[]; teams: string[] }>('/api/icc/rank-types'),

  iccPlayerRanking: (rankType: string) =>
    getJson<IccRankingTable>(`/api/icc/players/${encodeURIComponent(rankType)}`),

  iccTeamRanking: (rankType: string) =>
    getJson<IccTeamRankingTable>(`/api/icc/teams/${encodeURIComponent(rankType)}`),

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
