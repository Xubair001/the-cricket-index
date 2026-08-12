export type Competition = 'tests' | 'odis' | 't20is' | 'psl'
export type ApiGender = 'male' | 'female'
export type TeamType = 'international' | 'franchise'

export interface TeamRef {
  team_id: number
  name: string
}

export interface CompetitionCount {
  competition_key: string
  display_name: string
  count: number
}

export interface SeasonCount {
  season: string
  count: number
}

export interface BattingRankingRow {
  player_name: string
  player_identifier: string | null
  matches: number
  runs: number
  dismissals: number
  balls_faced: number
  fours: number
  sixes: number
  average: number | null
  strike_rate: number | null
}

export interface BowlingRankingRow {
  player_name: string
  player_identifier: string | null
  matches: number
  wickets: number
  runs_conceded: number
  balls_bowled: number
  average: number | null
  economy: number | null
}

export interface DashboardStats {
  gender: ApiGender
  total_matches: number
  total_players: number
  total_teams: number
  by_competition: CompetitionCount[]
  matches_by_season: SeasonCount[]
  top_run_scorers: BattingRankingRow[]
  top_wicket_takers: BowlingRankingRow[]
}

export interface TeamSummary {
  team_id: number
  name: string
  gender: ApiGender
  team_type: string
  matches: number
  wins: number
  losses: number
  ties_or_no_result: number
  win_pct: number | null
}

export interface TeamDetail extends TeamSummary {
  top_run_scorers: BattingRankingRow[]
  top_wicket_takers: BowlingRankingRow[]
  recent_matches: MatchSummary[]
}

export interface HeadToHead {
  team_a: TeamRef
  team_b: TeamRef
  matches: number
  team_a_wins: number
  team_b_wins: number
  ties_or_no_result: number
}

export interface PlayerSummary {
  identifier: string
  name: string
  gender: ApiGender
  matches: number
}

export interface PlayerFormatStats {
  competition_key: string
  display_name: string
  matches: number
  runs: number
  dismissals: number
  balls_faced: number
  fours: number
  sixes: number
  batting_average: number | null
  strike_rate: number | null
  wickets: number
  runs_conceded: number
  balls_bowled: number
  bowling_average: number | null
  economy: number | null
}

export interface PlayerBio {
  date_of_birth: string | null
  birth_place: string | null
  nationality: string | null
  bio_source: string | null
}

export interface PlayerDetail {
  identifier: string
  name: string
  gender: ApiGender
  teams: TeamRef[]
  bio: PlayerBio
  by_competition: PlayerFormatStats[]
  recent_matches: MatchSummary[]
}

export interface MatchSummary {
  match_id: string
  competition_key: string
  competition_name: string
  gender: ApiGender
  match_type: string | null
  season_label: string | null
  venue: string | null
  city: string | null
  match_date_start: string | null
  team1: TeamRef | null
  team2: TeamRef | null
  winner: TeamRef | null
  outcome_result: string | null
  win_by_runs: number | null
  win_by_wickets: number | null
}

export interface MatchPerformer {
  player_name: string
  player_identifier: string | null
  team_id: number
  runs_scored: number
  balls_faced: number
  fours: number
  sixes: number
  dismissals: number
  wickets_taken: number
  balls_bowled: number
  runs_conceded: number
}

export interface MatchDetail extends MatchSummary {
  toss_winner: TeamRef | null
  toss_decision: string | null
  player_of_match: string | null
  event_name: string | null
  performers: MatchPerformer[]
}

export interface Paginated<T> {
  total: number
  limit: number
  offset: number
  items: T[]
}
