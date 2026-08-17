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

/**
 * The national side a player turns out for, for the flag beside their name.
 *
 * Resolved on the server from the player's own appearances, so it means the
 * same thing as the flag beside a team. Both are null for a franchise-only
 * player; `country_code` alone is null for the West Indies, a real side with
 * no ISO code, which renders as the neutral mark with the name on hover.
 */
export interface PlayerCountry {
  country: string | null
  country_code: string | null
}

export interface IccRankingRow {
  position: number
  player_name: string
  country: string | null
  // Derived from ICC's own country string, not from our appearance data.
  country_code: string | null
  points: number | null
  career_best: string | null
  player_identifier: string | null
}

export interface IccRankingTable {
  rank_type: string
  rank_date: string
  fetched_at: string | null
  total: number
  limit: number
  offset: number
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
  total: number
  limit: number
  offset: number
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

export interface ComparisonSide extends PlayerCountry {
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
  // ISO 3166-1 alpha-2, or a GB subdivision tag. null for franchises, the
  // invitational XIs and the West Indies — see backend/app/flags.py.
  country_code: string | null
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

export interface BattingRankingRow extends PlayerCountry {
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

export interface BowlingRankingRow extends PlayerCountry {
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
  country_code: string | null
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

export interface PlayerSummary extends PlayerCountry {
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

export interface PlayerDetail extends PlayerCountry {
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

export interface MatchPerformer extends PlayerCountry {
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

export interface SquadMember extends PlayerCountry {
  player_identifier: string
  player_name: string
  matches: number
  runs: number
  balls_faced: number
  dismissals: number
  wickets: number
  balls_bowled: number
  runs_conceded: number
  batting_average: number | null
  strike_rate: number | null
  bowling_average: number | null
  economy: number | null
  // INFERRED from deliveries in this window, for this team. Never sourced.
  role: string
  bowling_share: number | null
  role_confident: boolean
  last_played: string | null
}

export interface SquadAnalysis {
  team_id: number
  team_name: string
  country_code: string | null
  gender: ApiGender
  team_type: string
  window_matches: number
  matches_in_window: number
  first_match: string | null
  last_match: string | null
  members: SquadMember[]
  role_counts: Record<string, number>
  runs_by_role: Record<string, number>
  wickets_by_role: Record<string, number>
  top_run_share: number | null
  top_wicket_share: number | null
  reliance_top_n: number
  unavailable: string[]
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

// --- Analytics: form -------------------------------------------------------

export type FormState =
  | 'in_form'
  | 'improving'
  | 'stable'
  | 'declining'
  | 'out_of_form'
  | 'insufficient_data'

export interface FormTimelineEntry {
  match_id: string
  match_date: string | null
  competition_key: string
  runs_scored: number
  balls_faced: number
  wickets_taken: number
  balls_bowled: number
  runs_conceded: number
  impact: number
  impact_normalized: number
}

export interface FormVerdict {
  state: FormState
  label: string
  recent_mean: number | null
  baseline_mean: number | null
  recent_matches: number
  baseline_matches: number
  delta_ratio: number | null
  delta_absolute: number | null
  delta_percent: number | null
  trend: 'rising' | 'flat' | 'falling' | 'unknown'
  confidence: number
  explanation: string
  recent_window: string
  baseline_window: string
  timeline: FormTimelineEntry[]
}

export interface PeriodOption {
  key: string
  label: string
  kind: string
}

export interface ParFigures {
  competition_key: string
  gender: ApiGender
  scoring_rate: number
  economy: number
  runs_per_wicket: number
  mean_impact: number
  balls: number
}

export interface FormLeaderRow extends PlayerCountry {
  player_identifier: string
  player_name: string
  scorecard_name: string | null
  state: FormState
  label: string
  delta_percent: number | null
  trend: 'rising' | 'flat' | 'falling' | 'unknown'
  confidence: number
  recent_matches: number
  baseline_matches: number
  // Absolute standard in par units, where 1.0 is an average appearance.
  // A large delta with a recent_mean below 1.0 means "improved, but still
  // below par" — the percentage alone cannot say that.
  recent_mean: number | null
  baseline_mean: number | null
  explanation: string
}

export interface FormLeaderboard {
  total: number
  limit: number
  offset: number
  scope: string
  items: FormLeaderRow[]
}

export interface DirectoryPlayer extends PlayerCountry {
  identifier: string
  name: string | null
  scorecard_name: string | null
  image_url: string | null
  nationality: string | null
  date_of_birth: string | null
  matches: number
  balls_faced: number
  balls_bowled: number
  runs: number
  batting_average: number | null
  strike_rate: number | null
  wickets: number
  bowling_average: number | null
  economy: number | null
  status: PlayerStatus | null
  form_state: FormState | null
  form_label: string | null
  form_delta: number | null
  form_confidence: number | null
}

export interface PlayerDirectory {
  total: number
  limit: number
  offset: number
  scope: string
  items: DirectoryPlayer[]
}

// --- Analytics explorers (§21) --------------------------------------------

export type ExplorerKind = 'batting' | 'bowling' | 'allround'

/** Row shape varies by explorer, so the numeric columns are indexed. */
export interface ExplorerRow extends PlayerCountry {
  player_name: string
  player_identifier: string | null
  matches: number
  // INFERRED from balls faced vs balls bowled — never a sourced fact.
  role: PlayerRole
  [metric: string]: string | number | null
}

export type PlayerRole = 'batter' | 'bowler' | 'allrounder' | 'unknown'

export interface ExplorerFilters {
  gender: string
  competition_key: string | null
  competition_type: string | null
  team_id: number | null
  opposition_team_id: number | null
  date_from: string | null
  date_to: string | null
  min_innings: number
  min_balls: number
  role: PlayerRole | null
  // Which inferred roles this explorer admits at all — a specialist bowler is
  // absent from a batting board by design, not by accident.
  roles_shown: PlayerRole[] | null
}

export interface ExplorerPage {
  explorer: ExplorerKind
  total: number
  limit: number
  offset: number
  sort_by: string
  filters: ExplorerFilters
  sorts: string[]
  items: ExplorerRow[]
}

// --- Performance Index (§14) ----------------------------------------------

export interface IndexComponent {
  key: string
  label: string
  /** What §14 asks for. */
  specified_weight: number
  /** After renormalising over the components that are actually live. */
  applied_weight: number
  active: boolean
  basis: string | null
  /** Non-null exactly when the component is inactive. */
  unavailable_because: string | null
}

export interface IndexRow extends PlayerCountry {
  player_identifier: string
  player_name: string
  /** The percentile pool the score was taken against. Inferred, not sourced. */
  role: PlayerRole
  matches: number
  index: number
  scores: Record<string, number>
  raw: Record<string, number>
}

export interface PerformanceIndexPage {
  scope: string
  gender: ApiGender
  total: number
  limit: number
  offset: number
  window_matches: number
  min_matches: number
  components: IndexComponent[]
  items: IndexRow[]
}

/** A canonical ground. `raw_spellings` shows how fragmented it was in source. */
export interface VenueOption {
  venue: string
  city: string | null
  matches: number
  raw_spellings: number
}

export interface VenueFormatStats {
  competition_key: string
  competition_name: string
  matches: number
  /** Runs OFF THE BAT — extras are not attributed to a batter, so this runs
   *  about 5% under a true team total. Named for what it actually is. */
  runs_off_bat_per_match: number | null
  runs_per_wicket: number | null
  balls_per_wicket: number | null
  boundary_rate: number | null
  /** Ratios against this competition's own par: 1.0 = typical for the format. */
  scoring_index: number | null
  wicket_index: number | null
  bat_first_wins: number
  bat_first_losses: number
  bat_first_win_pct: number | null
  toss_win_pct: number | null
  chose_to_bat_pct: number | null
  decided_matches: number
  /** False when too few matches for the rates to describe the ground. */
  reliable: boolean
}

export interface VenueProfile {
  venue: string
  city: string | null
  matches: number
  first_match: string | null
  last_match: string | null
  raw_spellings: string[]
  formats: VenueFormatStats[]
}

export interface TeamStrengthEra {
  era: string
  /** Multiplier: >1 = harder to play against than an average side. */
  difficulty: number
  matches: number
  /** False when too little cricket in this era for the figure to mean much. */
  reliable: boolean
}

/** A fitted difficulty rating. NOT official, and NOT a match prediction. */
export interface TeamStrengthRow {
  team_id: number
  name: string
  country_code: string | null
  matches: number
  difficulty: number
  /** Null when the latest era is too thin to state — withheld, not guessed. */
  current_difficulty: number | null
  eras: TeamStrengthEra[]
}

export interface TeamStrengthTable {
  gender: ApiGender
  competition_type: string
  total: number
  /** Correlation with ICC's published ratings — a check, never an input. */
  validated_against_icc: string
  items: TeamStrengthRow[]
}
