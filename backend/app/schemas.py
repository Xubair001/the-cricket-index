from pydantic import BaseModel, ConfigDict

Gender = str  # 'male' | 'female' -- kept as str (not Literal) for forward-compat with API responses


class TeamRef(BaseModel):
    team_id: int
    name: str


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


class BattingRankingRow(BaseModel):
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


class BowlingRankingRow(BaseModel):
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


class PlayerSummary(BaseModel):
    identifier: str
    name: str
    gender: Gender
    matches: int


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


class PlayerDetail(BaseModel):
    identifier: str
    name: str
    gender: Gender
    teams: list[TeamRef]
    bio: PlayerBio
    by_competition: list[PlayerFormatStats]
    recent_matches: list["MatchSummary"]


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


class MatchPerformer(BaseModel):
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
