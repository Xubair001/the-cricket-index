from pydantic import BaseModel, ConfigDict

Gender = str  # 'male' | 'female' -- kept as str (not Literal) for forward-compat with API responses


class TeamRef(BaseModel):
    team_id: int
    name: str
    # ISO 3166-1 alpha-2, or a GB subdivision tag. None for franchises,
    # invitational sides and the West Indies -- see app/flags.py.
    country_code: str | None = None


class CompetitionRef(BaseModel):
    competition_id: int
    key: str
    display_name: str
    type: str
    gender: Gender


class CompetitionCount(BaseModel):
    competition_key: str
    display_name: str
    count: int


class SeasonCount(BaseModel):
    season: str
    count: int


class PlayerCountry(BaseModel):
    """The national side a player turns out for, for the flag beside their name.

    Resolved from their appearances (`queries._player_country_map`), so it means
    the same thing as the flag beside a team and carries no claim the data does
    not support. Both fields are null for a franchise-only player, and
    `country_code` alone is null for the West Indies — a real side with no ISO
    code, which renders as the neutral mark with the name on hover.
    """

    country: str | None = None
    country_code: str | None = None


class BattingRankingRow(PlayerCountry):
    player_name: str
    player_identifier: str | None
    matches: int
    runs: int
    dismissals: int
    balls_faced: int
    fours: int
    sixes: int
    average: float | None
    strike_rate: float | None


class BowlingRankingRow(PlayerCountry):
    player_name: str
    player_identifier: str | None
    matches: int
    wickets: int
    runs_conceded: int
    balls_bowled: int
    average: float | None
    economy: float | None


class DashboardStats(BaseModel):
    gender: Gender
    total_matches: int
    total_players: int
    total_teams: int
    by_competition: list[CompetitionCount]
    matches_by_season: list[SeasonCount]
    top_run_scorers: list[BattingRankingRow]
    top_wicket_takers: list[BowlingRankingRow]


class TeamSummary(BaseModel):
    team_id: int
    name: str
    country_code: str | None = None
    gender: Gender
    team_type: str
    matches: int
    wins: int
    losses: int
    ties_or_no_result: int
    win_pct: float | None


class TeamDetail(TeamSummary):
    top_run_scorers: list[BattingRankingRow]
    top_wicket_takers: list[BowlingRankingRow]
    recent_matches: list["MatchSummary"]


class HeadToHead(BaseModel):
    team_a: TeamRef
    team_b: TeamRef
    matches: int
    team_a_wins: int
    team_b_wins: int
    ties_or_no_result: int


class PlayerStatus(BaseModel):
    """Playing status, separating what's sourced from what's observed.

    `state` is 'retired' ONLY when an external source says so -- Wikidata's
    work-period-end, or a date of death. Absent that, the app will not call
    anyone retired: a player with no recent appearances may equally be injured,
    dropped, or between contracts, and this dataset cannot tell those apart.
    Those are reported as 'inactive' with the last date actually observed.
    """

    state: str                     # 'active' | 'retired' | 'inactive'
    last_played: str | None        # date of most recent appearance in this dataset
    retired_on: str | None         # sourced retirement date, else null
    deceased_on: str | None        # sourced date of death, else null
    source: str | None             # provenance for a 'retired' state, else null


class PlayerSummary(PlayerCountry):
    identifier: str
    # `name` is the display form (Wikidata label where known, e.g. "Joe Root").
    # `scorecard_name` is Cricsheet's initials-and-surname form ("JE Root"),
    # kept because it's what appears on an actual scorecard.
    name: str
    scorecard_name: str | None = None
    gender: Gender
    matches: int
    status: PlayerStatus | None = None


class PlayerFormatStats(BaseModel):
    competition_key: str
    display_name: str
    matches: int
    runs: int
    dismissals: int
    balls_faced: int
    fours: int
    sixes: int
    batting_average: float | None
    strike_rate: float | None
    wickets: int
    runs_conceded: int
    balls_bowled: int
    bowling_average: float | None
    economy: float | None


class PlayerBio(BaseModel):
    date_of_birth: str | None
    birth_place: str | None
    nationality: str | None
    bio_source: str | None  # null => not available, not a guess
    image_url: str | None = None  # Wikimedia Commons; null => no photo, not a placeholder


class IccRankEntry(BaseModel):
    """A player's current ICC standing in one ranking table."""

    rank_type: str
    rank_date: str
    position: int
    points: int | None
    career_best: str | None


class PlayerDetail(PlayerCountry):
    identifier: str
    name: str
    scorecard_name: str | None = None
    gender: Gender
    teams: list[TeamRef]
    bio: PlayerBio
    status: PlayerStatus
    icc_rankings: list[IccRankEntry]
    by_competition: list[PlayerFormatStats]
    recent_matches: list["MatchSummary"]


class IccRankingRow(BaseModel):
    position: int
    player_name: str            # as ICC spells it, which may differ from ours
    country: str | None
    # Derived from ICC's own `country` string, not from our appearance data:
    # this table is ICC's claim about their own list, and resolving the flag
    # any other way would mix a derived figure into a published one. Most
    # entries are not linked to one of our players at all.
    country_code: str | None = None
    points: int | None
    career_best: str | None
    player_identifier: str | None   # null => not confidently matched, no link


class IccRankingTable(BaseModel):
    rank_type: str
    rank_date: str
    fetched_at: str | None
    total: int = 0
    limit: int = 0
    offset: int = 0
    rows: list[IccRankingRow]


class IccTeamRankingRow(BaseModel):
    position: int
    team_name: str
    points: int | None
    team_id: int | None


class IccTeamRankingTable(BaseModel):
    rank_type: str
    rank_date: str
    fetched_at: str | None
    total: int = 0
    limit: int = 0
    offset: int = 0
    rows: list[IccTeamRankingRow]


class ComparisonSide(PlayerCountry):
    identifier: str
    name: str
    scorecard_name: str | None = None
    status: PlayerStatus
    teams: list[TeamRef]
    bio: PlayerBio
    totals: PlayerFormatStats | None      # within the compared scope
    by_competition: list[PlayerFormatStats]
    icc_rankings: list[IccRankEntry]
    career_span: list[str | None]         # [first year, last year] observed


class ComparisonMetric(BaseModel):
    """One head-to-head row. `better` names the winning side, never a guess."""

    key: str
    label: str
    a: float | None
    b: float | None
    better: str | None                     # 'a' | 'b' | None (tie/insufficient)
    lower_is_better: bool
    format: str                            # 'int' | 'float' | 'none'


class PlayerComparison(BaseModel):
    scope: str                             # competition key, or a competition type
    scope_label: str
    gender: Gender
    a: ComparisonSide
    b: ComparisonSide
    metrics: list[ComparisonMetric]
    season_runs: list[dict]                # [{season, a, b}] for the trend chart
    season_wickets: list[dict]


class FixtureRow(BaseModel):
    """A calendar entry from ICC's schedule, not a `matches` record.

    Team names are ICC's own strings; team_a_id/team_b_id are populated only
    where the name matched one of our international teams, so an associate side
    ICC lists but Cricsheet has never covered simply isn't a link.
    """

    icc_match_id: str
    series_name: str | None
    tour_name: str | None
    match_type: str | None
    match_number: str | None
    gender: Gender | None
    match_status: str | None
    is_upcoming: bool
    is_live: bool
    start_date: str | None
    end_date: str | None
    start_time_gmt: str | None
    venue: str | None
    country: str | None
    team_a_name: str | None
    team_a_short: str | None
    team_a_id: int | None
    team_b_name: str | None
    team_b_short: str | None
    team_b_id: int | None
    match_result: str | None
    winning_team_name: str | None
    toss_won_by: str | None
    toss_elected_to: str | None


class PaginatedFixtures(BaseModel):
    total: int
    limit: int
    offset: int
    window: str
    last_synced: str | None
    items: list[FixtureRow]


class MatchSummary(BaseModel):
    match_id: str
    competition_key: str
    competition_name: str
    gender: Gender
    match_type: str | None
    season_label: str | None
    venue: str | None
    city: str | None
    match_date_start: str | None
    team1: TeamRef | None
    team2: TeamRef | None
    winner: TeamRef | None
    outcome_result: str | None
    win_by_runs: int | None
    win_by_wickets: int | None


class MatchPerformer(PlayerCountry):
    player_name: str
    player_identifier: str | None
    team_id: int
    runs_scored: int
    balls_faced: int
    fours: int
    sixes: int
    dismissals: int
    wickets_taken: int
    balls_bowled: int
    runs_conceded: int


class MatchDetail(MatchSummary):
    toss_winner: TeamRef | None
    toss_decision: str | None
    player_of_match: str | None
    event_name: str | None
    performers: list[MatchPerformer]


class IndexComponent(BaseModel):
    """One component of a Performance Index score, always decomposed (§30)."""

    key: str
    label: str
    specified_weight: float          # what §14 asks for
    applied_weight: float            # after renormalising over live components
    active: bool
    basis: str | None
    unavailable_because: str | None  # non-null exactly when inactive


class IndexRow(PlayerCountry):
    player_identifier: str
    player_name: str
    # The percentile pool this score was taken against. Inferred, not sourced.
    role: str
    matches: int
    index: float
    # Component key -> 0..100 percentile within (scope x role).
    scores: dict[str, float]
    # Component key -> the measured figure the percentile came from.
    raw: dict[str, float]


class PerformanceIndexPage(BaseModel):
    scope: str
    gender: Gender
    total: int
    limit: int
    offset: int
    window_matches: int
    min_matches: int
    components: list[IndexComponent]
    items: list[IndexRow]


class VenueOption(BaseModel):
    """A canonical ground. `raw_spellings` shows how fragmented it was."""

    venue: str
    city: str | None
    matches: int
    raw_spellings: int


class ExplorerRow(BaseModel):
    """One explorer row. Fields vary by explorer, so this stays open."""

    model_config = ConfigDict(extra="allow")

    player_name: str
    player_identifier: str | None
    matches: int


class ExplorerPage(BaseModel):
    explorer: str
    total: int
    limit: int
    offset: int
    sort_by: str
    # Echoed back so the caller can see exactly what qualification was applied,
    # rather than wondering why an expected player is absent (§21).
    filters: dict
    sorts: list[str]
    items: list[ExplorerRow]


class PaginatedTeams(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TeamSummary]


class PaginatedMatches(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MatchSummary]


class PaginatedPlayers(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PlayerSummary]


# ---------------------------------------------------------------------------
# Analytics: form
# ---------------------------------------------------------------------------


class FormTimelineEntry(BaseModel):
    match_id: str
    match_date: str | None
    competition_key: str
    runs_scored: int
    balls_faced: int
    wickets_taken: int
    balls_bowled: int
    runs_conceded: int
    impact: float
    impact_normalized: float


class FormVerdict(BaseModel):
    """A form classification with everything needed to justify it.

    The verdict is never returned alone. Rule 5 applies here as much as to a
    recommendation: the means it compares, the sample sizes behind them, the
    windows they cover and a confidence figure all travel with the label, so the
    UI can show why a player is called "in form" and how much to trust it.
    """

    state: str
    label: str
    recent_mean: float | None
    baseline_mean: float | None
    recent_matches: int
    baseline_matches: int
    delta_ratio: float | None
    delta_absolute: float | None
    delta_percent: float | None
    trend: str
    confidence: float
    explanation: str
    recent_window: str
    baseline_window: str
    timeline: list[FormTimelineEntry]


class PeriodOption(BaseModel):
    key: str
    label: str
    kind: str


class ParFigures(BaseModel):
    """What a par performance looks like in one competition, as measured."""

    competition_key: str
    gender: str
    scoring_rate: float
    economy: float
    runs_per_wicket: float
    mean_impact: float
    balls: int


class FormLeaderRow(PlayerCountry):
    player_identifier: str
    player_name: str
    scorecard_name: str | None
    state: str
    label: str
    delta_percent: float | None
    trend: str
    confidence: float
    recent_matches: int
    baseline_matches: int
    # Absolute standard in par units (1.0 = an average appearance in this
    # competition). Carried alongside the percentage because the two answer
    # different questions: a player can post a large delta and still be below
    # par, having improved from very poor.
    recent_mean: float | None = None
    baseline_mean: float | None = None
    explanation: str


class FormLeaderboard(BaseModel):
    total: int
    limit: int
    offset: int
    scope: str
    items: list[FormLeaderRow]


class DirectoryPlayer(PlayerCountry):
    identifier: str
    name: str | None
    scorecard_name: str | None
    image_url: str | None
    nationality: str | None
    date_of_birth: str | None
    matches: int
    balls_faced: int
    balls_bowled: int
    runs: int
    batting_average: float | None
    strike_rate: float | None
    wickets: int
    bowling_average: float | None
    economy: float | None
    status: PlayerStatus | None
    form_state: str | None
    form_label: str | None
    form_delta: float | None
    form_confidence: float | None


class PlayerDirectory(BaseModel):
    total: int
    limit: int
    offset: int
    scope: str
    items: list[DirectoryPlayer]
