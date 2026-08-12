import type {
  ApiGender,
  BattingRankingRow,
  BowlingRankingRow,
  DashboardStats,
  HeadToHead,
  MatchDetail,
  MatchSummary,
  Paginated,
  PlayerDetail,
  PlayerSummary,
  TeamDetail,
  TeamSummary,
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

  teams: (gender: ApiGender) => getJson<TeamSummary[]>('/api/teams', { gender }),

  teamDetail: (teamId: number) => getJson<TeamDetail>(`/api/teams/${teamId}`),

  headToHead: (teamAId: number, teamBId: number) =>
    getJson<HeadToHead>(`/api/teams/${teamAId}/head-to-head/${teamBId}`),

  players: (gender: ApiGender, params: { search?: string; limit?: number; offset?: number }) =>
    getJson<Paginated<PlayerSummary>>('/api/players', { gender, ...params }),

  playerDetail: (identifier: string) =>
    getJson<PlayerDetail>(`/api/players/${encodeURIComponent(identifier)}`),

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
}
