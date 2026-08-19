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
  form_delta: number | null
  form_state: string | null
  recent_mean: number | null
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
  /** Already a percentage against the player's own baseline, not a ratio. */
  form_delta: number | null
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
