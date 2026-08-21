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
  /** Positional against `PlayerComparison.sides`. */
  values: (number | null)[]
  /** Per player: whether they have enough cricket for this figure to be
   *  comparable. An unqualified player keeps their value - it is a fact about
   *  them - but cannot win the row. Applied per player rather than to the set,
   *  so one thin sample does not blank the row for everybody. */
  qualified: boolean[]
  /** Index into `values`. Null on a tie or where fewer than two players
   *  qualify - never a guess. */
  best_index: number | null
  lower_is_better: boolean
  format: 'int' | 'float' | 'none'
  /** What the qualification is measured on, and its minimum, so the UI can say
   *  WHY a figure is greyed rather than just greying it. */
  gate_field: string | null
  gate_min: number | null
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

export interface PlayerComparison {
  scope: string
  scope_label: string
  gender: ApiGender
  /** 2 to 5 players. Everything positional - `values` on a metric, `values` in
   *  a season row - indexes into this. Replaced an `a`/`b` pair, which had
   *  nowhere to put a third player. */
  sides: ComparisonSide[]
  metrics: ComparisonMetric[]
  season_runs: { season: string; values: number[] }[]
  season_wickets: { season: string; values: number[] }[]
}

export interface TeamRef {
  team_id: number
  name: string
  // ISO 3166-1 alpha-2, or a GB subdivision tag. null for franchises, the
  // invitational XIs and the West Indies - see backend/app/flags.py.
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
  // Which feed produced these figures, and therefore what can be asked of them.
  // 'cricsheet' is ball-by-ball derived, so splits, partnerships and spells all
  // work. 'icc' is ICC's own computed scorecard: the totals are real, but there
  // are no deliveries, so those views are genuinely unavailable rather than
  // empty. Shown in the UI rather than hidden.
  source: string
  has_ball_by_ball: boolean
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
  /** Raw ratio in percent, against the player's own baseline. UNBOUNDED - can
   *  exceed 100. Kept for traceability; show `form_score` instead. */
  delta_percent: number | null
  /** 0-100. Percentile of the evidence-weighted move within this scope, so it
   *  is bounded and orders players the same way the boards do. */
  form_score: number | null
  /** The change in words, never a percentage over 100. */
  delta_display: string | null
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
  /** 'career' | 'last_matches' | 'last_days'. The UI groups on this, because a
   *  count-bounded window means something different from a date-bounded one. */
  kind: string
}

/** The window a response actually used, as reported back by the API. */
export interface AppliedPeriod {
  /** The spec that reproduces this window, for a shareable URL. */
  spec: string | null
  label: string
  kind: string
  /** Resolved bounds, present only for a date-bounded window. */
  start: string | null
  end: string | null
  /** The newest match in this scope, which a relative window counts back from. */
  anchor: string | null
  /** Present where the window needs a caveat stated rather than inferred. */
  note: string | null
}

/** A paginated board that reports which window produced it. */
export interface PeriodPaginated<T> extends Paginated<T> {
  period: AppliedPeriod
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
  /** Unbounded raw ratio. Show `form_score`. */
  delta_percent: number | null
  form_score: number | null
  delta_display: string | null
  trend: 'rising' | 'flat' | 'falling' | 'unknown'
  confidence: number
  recent_matches: number
  baseline_matches: number
  // Absolute standard in par units, where 1.0 is an average appearance.
  // A large delta with a recent_mean below 1.0 means "improved, but still
  // below par" - the percentage alone cannot say that.
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
  /** Unbounded raw ratio. Show `form_score`. */
  form_delta: number | null
  form_score: number | null
  form_display: string | null
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
  // INFERRED from balls faced vs balls bowled - never a sourced fact.
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
  // Which inferred roles this explorer admits at all - a specialist bowler is
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
  /** How many players matched every filter BEFORE the volume floors, and the
   *  floors actually applied. Both are returned because their being different is
   *  the whole story on a narrowed slice: without the first, a reader cannot
   *  tell "no cricket here" from "the floor removed all of it". */
  total_before_volume_floor: number
  applied_min_balls: number
  applied_min_innings: number
  /** The window these figures cover, resolved by the API. */
  period: AppliedPeriod | null
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
  /** Runs OFF THE BAT - extras are not attributed to a batter, so this runs
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
  /** Null when the latest era is too thin to state - withheld, not guessed. */
  current_difficulty: number | null
  eras: TeamStrengthEra[]
}

export interface TeamStrengthTable {
  gender: ApiGender
  competition_type: string
  total: number
  /** Correlation with ICC's published ratings - a check, never an input. */
  validated_against_icc: string
  items: TeamStrengthRow[]
}

// --- Match intelligence (§22) ----------------------------------------------

export interface PartnershipRow {
  wicket: number
  batter_a: string
  batter_b: string
  runs: number
  balls: number
  run_rate: number | null
  /** Ended the innings rather than being broken by a wicket. */
  unbroken: boolean
  ended_by: string | null
  start_over: number
  end_over: number
}

export interface SpellRow {
  bowler: string
  overs: number
  balls: number
  runs_conceded: number
  wickets: number
  economy: number | null
  start_over: number
  end_over: number
}

export interface OverPointRow {
  over: number
  runs: number
  wickets: number
  cumulative_runs: number
  cumulative_wickets: number
}

export interface InningsIntelligence {
  innings: number
  batting_team: string | null
  runs: number
  wickets: number
  balls: number
  run_rate: number | null
  partnerships: PartnershipRow[]
  spells: SpellRow[]
  overs: OverPointRow[]
}

export interface MatchIntelligence {
  match_id: string
  innings: InningsIntelligence[]
  /** What §22 defers, with the reason - a missing feature, not a missing figure. */
  deferred: Record<string, string>
}

// --- Best XI / XV (§18) ----------------------------------------------------

export interface SelectionPick extends PlayerCountry {
  player_identifier: string
  player_name: string
  /** INFERRED from balls faced vs bowled and dismissal credits, never sourced. */
  role: string
  slot: string
  is_wicketkeeper: boolean
  /** 'squad' (ICC named them a keeper), 'stumping' (they took one), or null. */
  keeper_source: string | null
  opens: boolean
  matches: number
  index: number | null
  /** Unbounded raw ratio. Show `form_score`. */
  form_delta: number | null
  form_score: number | null
  form_display: string | null
  form_state: string | null
  recent_mean: number | null
  /** This player's record at the requested ground, where one was requested and
   *  they have played there. `venue_matches` is the sample the adjustment rests
   *  on and is always shown beside it: two matches is not a venue record. */
  venue_matches: number | null
  venue_mean: number | null
  venue_score: number | null
  selection_score: number
  reason: string
  /** Sourced from ICC squads where present, else null. Never inferred. */
  batting_style: string | null
  /**
   * NOMINAL: the feed records a style for anyone who bowls at all, so a batter
   * can carry one. Only meaningful on a bowling slot.
   */
  bowling_family: string | null
}

export interface SelectedSide {
  scope: string
  gender: ApiGender
  size: number
  team_id: number | null
  team_name: string | null
  picks: SelectionPick[]
  /** The role shape the side was filled to. */
  shape: Record<string, number>
  /** What could not be considered at all, with the reason. */
  unavailable: Record<string, string>
  /** What the selector could not guarantee about this particular side. */
  notes: string[]
  /** Which pool the side was picked from: 'all_time' or 'current'. */
  pool: string
  pool_size: number
  pool_considered: number
  /** The scope's most recent match, and the cutoff derived from it. Null for all-time. */
  reference_date: string | null
  cutoff_date: string | null
  /** The weights actually applied, so the blend is checkable on the page. */
  weights: Record<string, number>
  /** Which of Section 18's objectives this side answers. The same heading means
   *  a different side depending on it, so it is always reported. */
  objective: string
  objective_label: string
  objective_detail: string
  /** The ground the side was tilted towards, and how many candidates have any
   *  record there - a venue term over 12 of 327 candidates is a different claim
   *  from one over most of them. */
  venue: string | null
  venue_candidates_with_record: number
  eligibility_floor: number
  /** The best players left out, with the constraint that left them out. */
  tradeoffs: SelectionTradeOff[]
  /** Candidates whose age is unknown, where the objective depends on age. */
  unknown_age: number
}

export interface SelectionTradeOff {
  player_identifier: string
  player_name: string
  role: string
  selection_score: number
  index: number | null
  matches: number
  country: string | null
  country_code: string | null
  /** The constraint that kept them out, in the selector's own terms. */
  reason: string
  /** Who holds the place they would have taken, and that player's score. */
  displaced: string | null
  displaced_score: number | null
}

// --- Player availability (§16) ---------------------------------------------

export interface CommitmentRow {
  icc_match_id: string
  team_name: string | null
  opponent: string | null
  start_date: string | null
  end_date: string | null
  match_type: string | null
  series_name: string | null
  role: string | null
  batting_style: string | null
  bowling_style: string | null
  is_captain: boolean
  status: string | null
}

export interface PlayerAvailabilityRow {
  player_identifier: string | null
  player_name: string
  committed: boolean
  /** Sourced from the squad feed - role, hand and bowling type. */
  role: string | null
  batting_style: string | null
  bowling_style: string | null
  commitments: CommitmentRow[]
}

export interface ScoutCandidate {
  player_identifier: string
  player_name: string
  country: string | null
  country_code: string | null
  matches: number
  role: string | null
  /** True when the role came from a squad list, false when inferred from balls. */
  role_sourced: boolean
  batting_style: string | null
  bowling_style: string | null
  bowling_family: string | null
  age: number | null
  index: number | null
  /** Already a percentage against the player's own baseline, not a ratio.
   *  UNBOUNDED - show `form_score` instead. */
  form_delta: number | null
  form_score: number | null
  form_display: string | null
  form_state: string | null
  recent_mean: number | null
  committed_in_window: boolean | null
  score: number
  reason: string
}

export interface ScoutResult {
  scope: string
  gender: ApiGender
  candidates_considered: number
  /** How many of those carry any sourced attribute - the ceiling on a hand or style filter. */
  with_sourced_attributes: number
  unknown_age: number
  /** Constraints honoured, keyed by name. */
  applied: Record<string, string>
  /** Constraints that could NOT be honoured, with the reason. */
  ignored: Record<string, string>
  candidates: ScoutCandidate[]
}

export interface AvailabilityWindow {
  date_from: string
  date_to: string
  fixtures_in_window: number
  /** How much of the window is actually known - absence means nothing below this. */
  fixtures_with_squads: number
  players: PlayerAvailabilityRow[]
  caveats: Record<string, string>
}

/* ── News ──────────────────────────────────────────────────────
 * A fourth source family beside Cricsheet, computed rankings and ICC's
 * published figures. Nothing here feeds a derived figure: an article is
 * editorial copy, and the separation is the same one the backend keeps. */

export interface NewsImage {
  url: string
  /** A list-sized rendition. Null when the CDN is unknown - fall back to `url`. */
  thumb_url: string | null
  width: number | null
  height: number | null
  alt_text: string | null
  caption: string | null
  credit: string | null
  role?: string
  image_type?: string | null
}

/**
 * What we are entitled to show, which is not the same as what we hold.
 *
 * 'full'          body is servable
 * 'extract'       a capped snippet plus a link out
 * 'metadata_only' headline, standfirst and hero image; there is no body
 */
export type NewsContentPolicy = 'full' | 'extract' | 'metadata_only'

export interface NewsArticleSummary {
  article_id: number
  title: string
  standfirst: string | null
  /** The publisher's canonical URL. Always link out to this - we do not re-host. */
  url: string
  published_at: string | null
  updated_at: string | null
  section: string | null
  word_count: number
  source: string
  publisher: string
  content_policy: NewsContentPolicy
  /** Credit line the UI must render. The Guardian's licence requires it. */
  attribution: string | null
  /** True when the body shown is capped, so a short read is never mistaken for a whole one. */
  body_truncated: boolean
  /** Non-null means this body republishes another article already held. */
  syndication_of_article_id: number | null
  image: NewsImage | null
}

export interface PaginatedNews {
  total: number
  limit: number
  offset: number
  items: NewsArticleSummary[]
}

export interface NewsTag {
  kind: string
  value: string
  slug: string
}

/**
 * A resolved link to a player, team or competition.
 *
 * `confidence` is displayed rather than hidden. 'tag_dob' is a publisher tag
 * whose date of birth matched a player we hold; 'body_name_men_default' is a
 * team name matched with the gender defaulted because nothing in the text
 * established one.
 */
export interface NewsEntity {
  type: 'player' | 'team' | 'competition'
  mention: string
  confidence: string
  player_identifier: string | null
  player_name: string | null
  team_id: number | null
  team_name: string | null
  competition_id: number | null
  competition_name: string | null
}

export interface NewsArticleMetadata {
  meta_title: string | null
  meta_description: string | null
  schema_type: string | null
  open_graph: Record<string, unknown>
  twitter: Record<string, unknown>
}

export interface NewsSyndication {
  article_id: number
  source: string
  url: string
}

export interface NewsArticleDetail extends NewsArticleSummary {
  body_text: string | null
  body_html: string | null
  authors: string[]
  tags: NewsTag[]
  entities: NewsEntity[]
  images: NewsImage[]
  metadata: NewsArticleMetadata | null
  syndications: NewsSyndication[]
}

export interface NewsSourceInfo {
  key: string
  name: string
  home_url: string | null
  strategy: string
  content_policy: NewsContentPolicy
  attribution: string | null
  /** Why this source is read the way it is, or why it is switched off. */
  policy_note: string | null
  enabled: boolean
  last_synced_at: string | null
  articles: number
}

export interface NewsSourceHealth {
  source: string
  articles: number
  latest: string | null
  with_hero: number
  linked_players: number
}

export interface NewsDegradedFeed {
  source: string
  feed: string
  failures: number
  last_status: number | null
  last_fetched_at: string | null
}

export interface NewsHealth {
  /** Ingestion ledger by status: stored, unchanged, invalid, failed, skipped. */
  ledger: Record<string, number>
  sources: NewsSourceHealth[]
  degraded_feeds: NewsDegradedFeed[]
  syndicated: number
  entity_links: Record<string, number>
}

/**
 * One competition, as the API describes it.
 *
 * `type` is 'international' | 'domestic_league' and is the query value itself,
 * not a label, so a client passes it straight back as `competition_type`.
 */
export interface CompetitionInfo {
  key: string
  display_name: string
  type: string
  matches: number
  /** Which genders hold this competition. The PSL is `['male']`. */
  genders: string[]
}

/* ── Tournaments ───────────────────────────────────────────────
 * Named multi-team events (World Cups, Champions Trophy, Asia Cup) as opposed
 * to bilateral tours, which are the great majority of `event_name` values and
 * are deliberately not listed here. */

export interface TournamentEdition {
  season: string | null
  matches: number
  sides: number
  first_date: string | null
  last_date: string | null
  winner_team_id: number | null
  winner_name: string | null
  runner_up_name: string | null
  /** False when this dataset does not hold the deciding match. Distinguishes
   *  "we do not have the final" from "nobody won it". */
  has_final: boolean
  /** The final was tied and settled on a super over or boundary count, so the
   *  champion comes from the eliminator rather than from a winner. */
  decided_by_tiebreak: boolean
  venues: string[]
}

export interface TournamentSummary {
  name: string
  slug: string
  gender: string
  competition_key: string
  competition_name: string
  competition_type: string
  is_icc: boolean
  is_flagship: boolean
  matches: number
  sides: number
  editions: number
  first_date: string | null
  last_date: string | null
  latest_season: string | null
  latest_winner: string | null
}

export interface TournamentLeader {
  player_identifier: string
  player_name: string
  matches: number
  runs?: number | null
  average?: number | null
  wickets?: number | null
}

export interface TournamentTitles {
  team: string
  titles: number
}

export interface TournamentDetail extends TournamentSummary {
  editions_detail: TournamentEdition[]
  top_run_scorers: TournamentLeader[]
  top_wicket_takers: TournamentLeader[]
  most_titles: TournamentTitles[]
  /** Raw Cricsheet spellings merged into this tournament, so a reader who
   *  disagrees with an alias can see exactly what was folded together. */
  source_names: string[]
  notes: string[]
}

/* ── ICC ranking movement (Section 8) ─────────────────────────── */

export interface IccMover {
  rank_type: string
  player_name: string
  player_identifier: string | null
  country: string | null
  country_code: string | null
  position: number
  previous_position: number
  /** Signed so POSITIVE means improvement, despite position 1 being the top. */
  places_gained: number
  points: number | null
  previous_points: number | null
  points_gained: number | null
}

export interface IccNewEntry {
  rank_type: string
  player_name: string
  player_identifier: string | null
  country: string | null
  country_code: string | null
  position: number
  points: number | null
}

export interface IccMovementReport {
  rank_type: string
  current_date: string | null
  previous_date: string | null
  /** How many dated lists are held for this ranking. A handful, because the
   *  daily sync began recently - which is why this is movement, not a trend. */
  snapshots: number
  compared: number
  risers: IccMover[]
  fallers: IccMover[]
  new_entries: IccNewEntry[]
  dropped_out: number
  notes: string[]
}

/* ── Ground character (Section 20) ────────────────────────────── */

export interface GroundCharacter {
  venue: string
  city: string | null
  matches: number
  /** 1.0 = typical scoring for this format. Above means a batting ground. */
  scoring_index: number | null
  /** 1.0 = typical balls per wicket. Above means wickets are harder to take. */
  wicket_index: number | null
  bat_first_win_pct: number | null
  decided_matches: number
  /** False below the match count at which these rates describe a ground rather
   *  than a handful of games. Marked, never withheld. */
  reliable: boolean
}

/* ── Team strength profile (Section 19) ───────────────────────── */

export interface StrengthDimension {
  key: string
  label: string
  value: number | null
  unit: string
  /** Percentile against the CORE sides of this scope, not the average side.
   *  Null where no peer figure could be built - never 50, which would read as
   *  "exactly typical" for a side nobody could measure. */
  score: number | null
  peer_value: number | null
  peer_sides: number
  basis: string
  /** False where the window holds too few matches for the figure to describe
   *  the side. Marked rather than withheld. */
  reliable: boolean
}

export interface TeamStrengthProfile {
  team_id: number
  team_name: string
  gender: ApiGender
  team_type: string
  competition_key: string | null
  window_matches: number
  matches_in_window: number
  squad_size: number
  first_match: string | null
  last_match: string | null
  dimensions: StrengthDimension[]
  notes: string[]
  unavailable: Record<string, string>
}

/* ── Performance splits (Section 12) ──────────────────────────── */

export interface SplitBucket {
  key: string
  label: string
  innings: number
  runs: number
  balls_faced: number
  dismissals: number
  fours: number
  sixes: number
  dots: number
  average: number | null
  strike_rate: number | null
  dot_pct: number | null
  boundary_pct: number | null
  wickets: number
  balls_bowled: number
  runs_conceded: number
  economy: number | null
  bowling_average: number | null
  bowling_dot_pct: number | null
  /** False where this bucket rests on too little cricket for THAT SIDE's rates
   *  to mean anything. Per discipline: a batter who bowled two overs at a ground
   *  must not have their batting average flagged on the bowling sample. The runs
   *  were still scored, so the row stays - it is the rates that carry a warning. */
  batting_reliable: boolean
  bowling_reliable: boolean
  /** Narrower: an average divides by dismissals, not by innings or balls. */
  average_reliable: boolean
  bowling_average_reliable: boolean
}

export interface PlayerSplits {
  player_identifier: string
  split: string
  label: string
  gender: string
  competition_key: string | null
  /** False when the split does not describe this format at all - phases in a
   *  Test, for instance. Reported rather than computed anyway. */
  applies: boolean
  not_applicable_because: string | null
  available: string[]
  /** Splits Section 12 names that no current source supports, with the reason
   *  each cannot be computed. Rendered, not hidden. */
  unavailable: Record<string, string>
  buckets: SplitBucket[]
}

/* ── Tournament edition (one World Cup, one year) ─────────────── */

export interface EditionStandingsRow {
  team_id: number
  team_name: string
  country_code: string | null
  /** Group letter where the edition had groups, else null. */
  group: string | null
  played: number
  won: number
  lost: number
  /** A tie and an abandoned match both score a point and only one of them means
   *  the sides finished level, so they are separate columns. */
  tied: number
  no_result: number
  points: number
  win_pct: number | null
  runs_for: number
  balls_faced: number
  runs_against: number
  balls_bowled: number
  /** Charges a side bowled out its FULL overs quota rather than the overs it
   *  used, which is the actual rule. Null where the format has no quota. */
  net_run_rate: number | null
}

export interface EditionFixture {
  match_id: string
  match_date: string | null
  stage: string | null
  group: string | null
  venue: string | null
  city: string | null
  team1_id: number | null
  team1_name: string | null
  team1_code: string | null
  team2_id: number | null
  team2_name: string | null
  team2_code: string | null
  winner_team_id: number | null
  winner_name: string | null
  /** Set only for a tie settled on a super over or boundary count. Cricsheet
   *  records that in `eliminator` and leaves `winner` null. */
  eliminator_name: string | null
  outcome_result: string | null
  win_by_runs: number | null
  win_by_wickets: number | null
  /** The result as a scorecard states it, assembled server-side. */
  result_text: string
  /** Preferred display form where the name resolves to a player here, the raw
   *  Cricsheet value otherwise. */
  player_of_match: string | null
  player_of_match_scorecard: string | null
  player_of_match_identifier: string | null
  /** Team totals from the ball record, so extras are included and a super over
   *  is excluded. Null where the match has no deliveries stored. */
  team1_score: string | null
  team2_score: string | null
}

export interface EditionLeader {
  player_identifier: string
  player_name: string
  country_code: string | null
  matches: number
  runs: number | null
  balls_faced: number | null
  average: number | null
  strike_rate: number | null
  fifties: number | null
  hundreds: number | null
  highest: number | null
  wickets: number | null
  balls_bowled: number | null
  runs_conceded: number | null
  economy: number | null
  bowling_average: number | null
  best_innings: number | null
  /** Player-of-the-match awards in this edition. The nearest thing this data
   *  holds to a player of the tournament, and not that award. */
  awards: number | null
}

export interface TournamentEditionDetail {
  tournament_name: string
  tournament_slug: string
  season: string | null
  gender: string
  competition_key: string
  competition_name: string
  matches: number
  sides: number
  first_date: string | null
  last_date: string | null
  champion_team_id: number | null
  champion_name: string | null
  runner_up_name: string | null
  has_final: boolean
  decided_by_tiebreak: boolean
  final_match_id: string | null
  venues: string[]
  groups: string[]
  standings: EditionStandingsRow[]
  fixtures: EditionFixture[]
  top_run_scorers: EditionLeader[]
  top_wicket_takers: EditionLeader[]
  most_awards: EditionLeader[]
  standings_caveats: string[]
  notes: string[]
}

/* ── Underrated players (Section 15) ───────────────────────────
 * Where this project's Performance Index and ICC's published position
 * disagree. Not a correction of ICC's rating - the two are built from
 * different evidence for different purposes. */

export interface UnderratedPlayer extends PlayerCountry {
  player_identifier: string
  player_name: string
  /** ICC's own published position, unmodified. */
  icc_position: number
  icc_points: number | null
  /** Both sides re-ranked 1..N within the comparable set. The gap comes from
   *  these: raw positions span two populations of different sizes. */
  icc_rank_in_set: number
  index_rank_in_set: number
  gap: number
  index: number
  matches: number
}

export interface UnderratedTable {
  rank_type: string
  gender: string
  competition_key: string
  role: string
  rank_date: string | null
  icc_listed: number
  icc_linked: number
  comparable: number
  /** The gap required for this board: a quarter of the comparable set. */
  min_gap: number
  items: UnderratedPlayer[]
  notes: string[]
}

/* ── Team weakness (Section 19) ────────────────────────────────
 * What has declined for a side against its OWN recent past. Named phases, not
 * a total, and never a league position. */

export interface WeaknessFacet {
  key: string
  label: string
  /** 'batting' or 'bowling'. Decides which direction of change is worse. */
  side: string
  recent: number | null
  baseline: number | null
  peer_median: number | null
  recent_deliveries: number
  baseline_deliveries: number
  /** Signed so NEGATIVE is always worse, whether the figure is a run rate or
   *  an economy conceded. */
  /** UNBOUNDED: a run rate can more than double on a thin sample, and 3 of
   *  2,340 measured figures exceed 100%. Show `delta_display`. */
  delta_percent: number | null
  /** The same change in words, never a percentage above 100. */
  delta_display: string | null
  versus_peers_percent: number | null
  verdict: 'declined' | 'improved' | 'steady' | 'unmeasured'
  note: string
}

export interface TeamWeakness {
  team_id: number
  team_name: string
  competition_key: string | null
  recent_matches: number
  baseline_matches: number
  facets: WeaknessFacet[]
  /** Only facets that declined. Empty is a real answer, not a failure. */
  weaknesses: string[]
  unavailable: Record<string, string>
  notes: string[]
}
