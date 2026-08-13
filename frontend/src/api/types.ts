export type Competition = 'tests' | 'odis' | 't20is' | 'psl'
export type ApiGender = 'male' | 'female'
export type TeamType = 'international' | 'franchise'

// 'retired' is only ever set from an external source (see PlayerStatus on the
// API side). A gap in appearances yields 'inactive', never 'retired'.
export type PlayerState = 'active' | 'retired' | 'inactive'

export interface PlayerStatus {
  state: PlayerState
  last_played: string | null
  retired_on: string | null
  deceased_on: string | null
  source: string | null
}

export interface IccRankEntry {
  rank_type: string
  rank_date: string
  position: number
  points: number | null
  career_best: string | null
}

export interface IccRankingRow {
  position: number
  player_name: string
  country: string | null
  points: number | null
  career_best: string | null
  player_identifier: string | null
}

export interface IccRankingTable {
  rank_type: string
  rank_date: string
  fetched_at: string | null
  rows: IccRankingRow[]
}

export interface IccTeamRankingRow {
  position: number
  team_name: string
  points: number | null
  team_id: number | null
}

export interface IccTeamRankingTable {
  rank_type: string
  rank_date: string
  fetched_at: string | null
  rows: IccTeamRankingRow[]
}

export interface ComparisonMetric {
  key: string
  label: string
  a: number | null
  b: number | null
  better: 'a' | 'b' | null
  lower_is_better: boolean
  format: 'int' | 'float' | 'none'
}

export interface ComparisonSide {
  identifier: string
  name: string
  scorecard_name: string | null
  status: PlayerStatus
  teams: TeamRef[]
  bio: PlayerBio
  totals: PlayerFormatStats | null
  by_competition: PlayerFormatStats[]
  icc_rankings: IccRankEntry[]
  career_span: (string | null)[]
}

export interface SeasonPoint {
  season: string
  a: number
  b: number
}

export interface PlayerComparison {
  scope: string
  scope_label: string
  gender: ApiGender
  a: ComparisonSide
  b: ComparisonSide
  metrics: ComparisonMetric[]
  season_runs: SeasonPoint[]
  season_wickets: SeasonPoint[]
}

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
  // `name` is the display form ("Joe Root"); `scorecard_name` is the
  // initials-and-surname form that appears on a scorecard ("JE Root").
  name: string
  scorecard_name: string | null
  gender: ApiGender
  matches: number
  status: PlayerStatus | null
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
  image_url: string | null
}

export interface PlayerDetail {
  identifier: string
  name: string
  scorecard_name: string | null
  gender: ApiGender
  teams: TeamRef[]
  bio: PlayerBio
  status: PlayerStatus
  icc_rankings: IccRankEntry[]
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

export type FixtureWindow = 'upcoming' | 'live' | 'results'

export interface FixtureRow {
  icc_match_id: string
  series_name: string | null
  tour_name: string | null
  match_type: string | null
  match_number: string | null
  gender: ApiGender | null
  match_status: string | null
  is_upcoming: boolean
  is_live: boolean
  start_date: string | null
  end_date: string | null
  start_time_gmt: string | null
  venue: string | null
  country: string | null
  team_a_name: string | null
  team_a_short: string | null
  team_a_id: number | null
  team_b_name: string | null
  team_b_short: string | null
  team_b_id: number | null
  match_result: string | null
  winning_team_name: string | null
  toss_won_by: string | null
  toss_elected_to: string | null
}

export interface PaginatedFixtures {
  total: number
  limit: number
  offset: number
  window: FixtureWindow
  last_synced: string | null
  items: FixtureRow[]
}
