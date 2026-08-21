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
    `country_code` alone is null for the West Indies - a real side with no ISO
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


class CompetitionInfo(BaseModel):
    """One competition, in the API's own vocabulary.

    `type` is 'international' or 'domestic_league' and can be passed straight
    back as `competition_type`, so a client never has to map a UI label onto a
    query value.
    """

    key: str
    display_name: str
    type: str
    matches: int
    """Which genders hold this competition. `competitions` is keyed by
    (key, gender), so grouping by key alone would hide that the PSL is
    men-only - which let a Leagues switch appear in a women's scope where
    every board behind it came back empty."""
    genders: list[str] = []


class WeaknessFacet(BaseModel):
    key: str
    label: str
    """'batting' or 'bowling'. Decides which direction of change is worse."""
    side: str
    recent: float | None = None
    baseline: float | None = None
    peer_median: float | None = None
    recent_deliveries: int
    baseline_deliveries: int
    """Change against the side's OWN past, signed so negative is always worse
    whether the underlying figure is a run rate or an economy conceded.

    UNBOUNDED: a run rate can more than double on a thin sample, and 3 of 2,340
    measured facet figures exceed 100%. Show `delta_display` instead."""
    delta_percent: float | None = None
    """The same change in words, never a percentage above 100."""
    delta_display: str | None = None
    versus_peers_percent: float | None = None
    """'declined' | 'improved' | 'steady' | 'unmeasured'."""
    verdict: str
    note: str = ""


class TeamWeakness(BaseModel):
    team_id: int
    team_name: str
    competition_key: str | None = None
    recent_matches: int
    baseline_matches: int
    facets: list[WeaknessFacet] = []
    """Only facets that declined against the side's own baseline. Empty is a
    real answer, not a failure."""
    weaknesses: list[str] = []
    unavailable: dict[str, str] = {}
    notes: list[str] = []


class UnderratedPlayer(PlayerCountry):
    player_identifier: str
    player_name: str
    """ICC's own published position, unmodified."""
    icc_position: int
    icc_points: int | None = None
    """Both sides re-ranked 1..N within the comparable set. The gap is computed
    from these, because comparing raw positions across two populations of
    different sizes would not mean anything."""
    icc_rank_in_set: int
    index_rank_in_set: int
    gap: int
    index: float
    matches: int


class UnderratedTable(BaseModel):
    rank_type: str
    gender: str
    competition_key: str
    role: str
    """ICC's most recent publication date. Older snapshots are not compared -
    they would report disagreements ICC has since resolved."""
    rank_date: str | None = None
    icc_listed: int
    icc_linked: int
    comparable: int
    """The gap required for this board, a quarter of the comparable set."""
    min_gap: int
    items: list[UnderratedPlayer] = []
    notes: list[str] = []


class TournamentEdition(BaseModel):
    season: str | None
    matches: int
    sides: int
    first_date: str | None
    last_date: str | None
    winner_team_id: int | None = None
    winner_name: str | None = None
    runner_up_name: str | None = None
    """False when the deciding match is not in this dataset. Distinguishes
    "we do not hold the final" from "nobody won it"."""
    has_final: bool = False
    """The final was tied and settled on a super over, boundary count or
    bowl-out, so the champion comes from the eliminator rather than a winner."""
    decided_by_tiebreak: bool = False
    venues: list[str] = []


class TournamentSummary(BaseModel):
    name: str
    slug: str
    gender: str
    competition_key: str
    competition_name: str
    competition_type: str
    is_icc: bool
    is_flagship: bool
    matches: int
    sides: int
    editions: int
    first_date: str | None
    last_date: str | None
    latest_season: str | None
    latest_winner: str | None


class TournamentLeader(BaseModel):
    player_identifier: str
    player_name: str
    matches: int
    runs: int | None = None
    average: float | None = None
    wickets: int | None = None


class TournamentTitles(BaseModel):
    team: str
    titles: int


class EditionStandingsRow(BaseModel):
    """One side's line in an edition table.

    Not an official points table. Points are the near-universal limited-overs
    convention (2 for a win, 1 shared) applied to the matches this dataset
    holds, and `standings_caveats` names any reason it will differ from the
    published one.
    """

    team_id: int
    team_name: str
    country_code: str | None = None
    """Group letter where the edition had groups, else null."""
    group: str | None = None
    played: int
    won: int
    lost: int
    """A tie and an abandoned match both score one point and only one of them
    means the sides finished level, so they are separate columns."""
    tied: int
    no_result: int
    points: int
    win_pct: float | None = None
    runs_for: int
    balls_faced: int
    runs_against: int
    balls_bowled: int
    """Charges a side bowled out its FULL overs quota rather than the overs it
    used, which is the actual rule. Null where the format has no quota."""
    net_run_rate: float | None = None


class EditionFixture(BaseModel):
    match_id: str
    match_date: str | None = None
    stage: str | None = None
    group: str | None = None
    venue: str | None = None
    city: str | None = None
    team1_id: int | None = None
    team1_name: str | None = None
    team1_code: str | None = None
    team2_id: int | None = None
    team2_name: str | None = None
    team2_code: str | None = None
    winner_team_id: int | None = None
    winner_name: str | None = None
    """Set only for a tie settled on a super over, boundary count or bowl-out.
    Cricsheet records that in `eliminator` and leaves `winner` null."""
    eliminator_name: str | None = None
    outcome_result: str | None = None
    win_by_runs: int | None = None
    win_by_wickets: int | None = None
    """The result as a scorecard states it, assembled server-side."""
    result_text: str
    """The preferred display form where the name resolves to a player here, the
    raw Cricsheet value otherwise. `player_of_match_scorecard` always holds the
    raw form, so a reader can see both."""
    player_of_match: str | None = None
    player_of_match_scorecard: str | None = None
    player_of_match_identifier: str | None = None
    """Team totals from the ball record, so extras are included. Null where the
    match has no deliveries stored."""
    team1_score: str | None = None
    team2_score: str | None = None


class EditionLeader(BaseModel):
    player_identifier: str
    player_name: str
    country_code: str | None = None
    matches: int
    runs: int | None = None
    balls_faced: int | None = None
    average: float | None = None
    strike_rate: float | None = None
    fifties: int | None = None
    hundreds: int | None = None
    highest: int | None = None
    wickets: int | None = None
    balls_bowled: int | None = None
    runs_conceded: int | None = None
    economy: float | None = None
    bowling_average: float | None = None
    best_innings: int | None = None
    """Player-of-the-match awards in this edition. The nearest thing this data
    holds to a player of the tournament, and not presented as that award."""
    awards: int | None = None


class TournamentEditionDetail(BaseModel):
    tournament_name: str
    tournament_slug: str
    season: str | None = None
    gender: Gender
    competition_key: str
    competition_name: str
    matches: int
    sides: int
    first_date: str | None = None
    last_date: str | None = None
    champion_team_id: int | None = None
    champion_name: str | None = None
    runner_up_name: str | None = None
    """False when this dataset does not hold the deciding match. Distinguishes
    "we do not have the final" from "nobody won it"."""
    has_final: bool = False
    decided_by_tiebreak: bool = False
    final_match_id: str | None = None
    venues: list[str] = []
    groups: list[str] = []
    standings: list[EditionStandingsRow] = []
    fixtures: list[EditionFixture] = []
    top_run_scorers: list[EditionLeader] = []
    top_wicket_takers: list[EditionLeader] = []
    most_awards: list[EditionLeader] = []
    standings_caveats: list[str] = []
    notes: list[str] = []


class TournamentDetail(TournamentSummary):
    editions_detail: list[TournamentEdition] = []
    top_run_scorers: list[TournamentLeader] = []
    top_wicket_takers: list[TournamentLeader] = []
    most_titles: list[TournamentTitles] = []
    """Raw Cricsheet spellings folded into this tournament, so a reader who
    disagrees with an alias can see exactly what was merged."""
    source_names: list[str] = []
    notes: list[str] = []


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
    """The window `by_competition` covers, resolved. Absent means career, which
    is what a profile has always shown; a narrowed window has to say so, because
    "9,230 runs" and "668 runs" are the same player."""
    period: dict | None = None


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
    """One row of a comparison, across 2 to 5 players.

    `values` is positional against `PlayerComparison.sides`. `best_index` names
    the winner and is null on a tie or where fewer than two players qualify -
    never a guess, and never a highlight on one of two equal figures.
    """

    key: str
    label: str
    values: list[float | None]
    """Per player: whether they have enough cricket for this figure to be
    comparable. A player below the threshold keeps their value - it is a fact
    about them - but cannot win the row. Applied per player rather than to the
    set, so one thin sample does not blank the row for everybody."""
    qualified: list[bool]
    best_index: int | None
    lower_is_better: bool
    format: str                            # 'int' | 'float' | 'none'
    """What the qualification is measured on, and the minimum, so the UI can
    say why a figure is greyed rather than just greying it."""
    gate_field: str | None = None
    gate_min: int | None = None


class PlayerComparison(BaseModel):
    """2 to 5 players within one competition scope (§13).

    `sides` replaced an `a`/`b` pair: a two-player special case cannot express
    "best of five" without the client re-deriving it, and `better: 'a' | 'b'`
    had nowhere to put a third player. Everything positional - `values` on a
    metric, `values` in a season row - indexes into `sides`.
    """

    scope: str                             # competition key, or a competition type
    scope_label: str
    gender: Gender
    sides: list[ComparisonSide]
    metrics: list[ComparisonMetric]
    # [{season, values: [...]}], positional against `sides`.
    season_runs: list[dict]
    season_wickets: list[dict]
    """The window these figures cover, resolved. A relative window counts back
    from the newest match in the scope rather than from today, and a
    count-bounded one is each player's own last N."""
    period: dict | None = None


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
    # Which feed the figures came from, and therefore what can be asked of them.
    # 'cricsheet' carries ball-by-ball, so phase splits, partnerships, spells and
    # keeper detection all work. 'icc' is ICC's own computed scorecard: the
    # totals are real and independently verified, but there are no deliveries,
    # so every ball-by-ball-derived view is genuinely unavailable rather than
    # empty. Surfaced rather than hidden so a reader is never misled about which
    # they are looking at.
    source: str = "cricsheet"
    has_ball_by_ball: bool = True
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


class VenueFormatStats(BaseModel):
    """One ground's cricket within one competition."""

    competition_key: str
    competition_name: str
    matches: int
    # Runs OFF THE BAT, not the team total: extras are not attributed to a
    # batter, so this understates a true score by roughly 5%. Named for what it
    # actually is (see analytics/venue.py).
    runs_off_bat_per_match: float | None
    runs_per_wicket: float | None
    balls_per_wicket: float | None
    boundary_rate: float | None
    # Ratios against this competition's own par: 1.0 = typical for the format.
    scoring_index: float | None
    wicket_index: float | None
    bat_first_wins: int
    bat_first_losses: int
    bat_first_win_pct: float | None
    toss_win_pct: float | None
    chose_to_bat_pct: float | None
    decided_matches: int
    # False when too few matches for the rates to describe the ground.
    reliable: bool


class GroundCharacter(BaseModel):
    """One ground on the two axes that describe a pitch, within one competition.

    Both are ratios against the competition's OWN par, because a raw runs per
    wicket says nothing without the format: 31 is a low Test figure and a very
    high T20I one. As an index a ground is comparable with every other ground in
    the same competition, which is the only comparison that means anything.
    """

    venue: str
    city: str | None = None
    matches: int
    """1.0 = typical scoring for this format. Above means a batting ground."""
    scoring_index: float | None = None
    """1.0 = typical balls per wicket. Above means wickets are harder to take."""
    wicket_index: float | None = None
    bat_first_win_pct: float | None = None
    decided_matches: int
    """False below the match count at which these rates describe a ground rather
    than a handful of games. Marked, never withheld."""
    reliable: bool


class VenueProfile(BaseModel):
    venue: str
    city: str | None
    matches: int
    first_match: str | None
    last_match: str | None
    # How many ways the source spells this ground -- the normalisation receipt.
    raw_spellings: list[str]
    formats: list[VenueFormatStats]


class TeamStrengthEra(BaseModel):
    era: str
    difficulty: float          # multiplier: >1 = harder than an average side
    matches: int
    # False when too little cricket in this era for the figure to mean much.
    reliable: bool = True


class TeamStrengthRow(BaseModel):
    """One side's fitted difficulty. NOT an official rating and NOT a
    prediction of results -- see analytics/opposition.py."""

    team_id: int
    name: str
    country_code: str | None
    matches: int
    difficulty: float          # long-run, across every era
    current_difficulty: float | None   # most recent era with cricket in it
    eras: list[TeamStrengthEra]


class TeamStrengthTable(BaseModel):
    gender: Gender
    competition_type: str
    total: int
    # Correlation against ICC's published team ratings. A CHECK on the model,
    # never an input to it (§6).
    validated_against_icc: str
    items: list[TeamStrengthRow]


class SplitBucket(BaseModel):
    """One slice of a player's cricket, batting and bowling side by side."""

    key: str
    label: str
    innings: int
    runs: int
    balls_faced: int
    dismissals: int
    fours: int
    sixes: int
    dots: int
    average: float | None
    strike_rate: float | None
    dot_pct: float | None
    boundary_pct: float | None
    wickets: int
    balls_bowled: int
    runs_conceded: int
    economy: float | None
    bowling_average: float | None
    bowling_dot_pct: float | None
    """False where this bucket rests on too little cricket for that side's RATES
    to mean anything. Per discipline: a batter who bowled two overs at a ground
    must not have their batting average flagged on the bowling sample. Marked
    rather than withheld - the runs were scored, but an average of 146.50 from
    two innings is not a record and must not be shown as one."""
    batting_reliable: bool = True
    bowling_reliable: bool = True
    """Narrower still, for the two rates whose denominator is not balls: an
    average divides by dismissals and a bowling average by wickets, so four
    innings can give a sound strike rate and a meaningless average."""
    average_reliable: bool = True
    bowling_average_reliable: bool = True


class PlayerSplits(BaseModel):
    player_identifier: str
    split: str
    label: str
    gender: Gender
    competition_key: str | None
    # False when the split does not describe this format at all -- phases in a
    # Test, for instance. Reported rather than computed anyway.
    applies: bool
    not_applicable_because: str | None
    available: list[str]
    # Splits §12 names that no current source supports, with the reason.
    unavailable: dict[str, str]
    buckets: list[SplitBucket]


class PartnershipRow(BaseModel):
    wicket: int
    batter_a: str
    batter_b: str
    runs: int
    balls: int
    run_rate: float | None
    unbroken: bool
    ended_by: str | None
    start_over: int
    end_over: int


class SpellRow(BaseModel):
    bowler: str
    overs: int
    balls: int
    runs_conceded: int
    wickets: int
    economy: float | None
    start_over: int
    end_over: int


class OverPointRow(BaseModel):
    over: int
    runs: int
    wickets: int
    cumulative_runs: int
    cumulative_wickets: int


class InningsIntelligence(BaseModel):
    innings: int
    batting_team: str | None
    runs: int
    wickets: int
    balls: int
    run_rate: float | None
    partnerships: list[PartnershipRow]
    spells: list[SpellRow]
    overs: list[OverPointRow]


class MatchIntelligence(BaseModel):
    match_id: str
    innings: list[InningsIntelligence]
    # What §22 defers, with the reason - so a reader can tell a missing feature
    # from a missing figure.
    deferred: dict[str, str]


class SelectionPick(PlayerCountry):
    player_identifier: str
    player_name: str
    # INFERRED from balls faced vs bowled / dismissal credits, never sourced.
    role: str
    slot: str
    is_wicketkeeper: bool
    # 'squad' (ICC named them a keeper), 'stumping' (they took one, which only
    # a keeper can), or null for a non-keeper.
    keeper_source: str | None = None
    opens: bool
    matches: int
    index: float | None
    # Raw ratio against the player's own baseline, unbounded. Kept for
    # traceability; `form_score` is the bounded figure to show.
    form_delta: float | None
    form_score: float | None = None
    form_display: str | None = None
    """The weights actually used for THIS player, renormalised over the
    components they have. A retired player carries no form term rather than a
    neutral stand-in, so the shape differs per pick and is reported."""
    applied_weights: dict[str, float] = {}
    """This player's record at the requested ground, where one was requested and
    they have played there. `venue_matches` is the sample the adjustment rests
    on and is always shown beside it: two matches at a ground is not a record."""
    venue_matches: int | None = None
    venue_mean: float | None = None
    venue_score: float | None = None
    form_state: str | None
    recent_mean: float | None
    selection_score: float
    reason: str
    # Sourced from ICC squads where present, else null. Never inferred.
    batting_style: str | None = None
    bowling_family: str | None = None


class SelectionTradeOff(BaseModel):
    """A player good enough to be picked who was not, and why (§18).

    §18 requires the highest-rated omitted player and the constraint that
    omitted them. Only players who out-score somebody actually picked appear -
    a candidate below every pick was not traded off, they were not good enough.
    """

    player_identifier: str
    player_name: str
    role: str
    selection_score: float
    index: float | None = None
    matches: int
    country: str | None = None
    country_code: str | None = None
    """The constraint that kept them out, in the selector's own terms."""
    reason: str = ""
    """Who holds the place they would have taken, and that player's score."""
    displaced: str | None = None
    displaced_score: float | None = None


class SelectedSide(BaseModel):
    scope: str
    gender: Gender
    size: int
    team_id: int | None
    team_name: str | None
    picks: list[SelectionPick]
    # The role shape the side was filled to.
    shape: dict
    # What could not be considered, with the reason (§18 balance needs these).
    unavailable: dict
    # What the selector could not guarantee about THIS side.
    notes: list[str]
    # Which pool the side was picked from, and what that came to. Present for
    # both pools so a client never has to infer which question was answered.
    pool: str = "all_time"
    pool_size: int = 0
    pool_considered: int = 0
    """The scope's most recent match, and the cutoff derived from it. Null for
    an all-time pool, where no window applies."""
    reference_date: str | None = None
    cutoff_date: str | None = None
    weights: dict[str, float] = {}
    """Matches a player needs in this scope to be considered. Scope-relative for
    an all-time side: a fixed floor empties scopes that are simply short - no
    player has more than 14 women's Tests here - so it is a fraction of what a
    long career in this scope looks like, and is reported rather than assumed."""
    eligibility_floor: int = 8
    """The ground the side was tilted towards, and how many candidates have any
    record there. Reported because a venue term computed over 12 of 327
    candidates is a different claim from one computed over most of them."""
    venue: str | None = None
    venue_candidates_with_record: int = 0
    """Which of §18's objectives this side answers. The same heading means a
    different side depending on it, so it is always reported."""
    objective: str = "overall"
    objective_label: str = ""
    objective_detail: str = ""
    """The best players left out, with the constraint that left them out."""
    tradeoffs: list[SelectionTradeOff] = []
    """Candidates whose age is unknown, where the objective depends on age.
    Reported rather than dropped: date of birth covers about 42% of the
    register, so a hard bound would discard the majority silently."""
    unknown_age: int = 0


class CommitmentRow(BaseModel):
    icc_match_id: str
    team_name: str | None
    opponent: str | None
    start_date: str | None
    end_date: str | None
    match_type: str | None
    series_name: str | None
    role: str | None
    batting_style: str | None
    bowling_style: str | None
    is_captain: bool
    status: str | None


class PlayerAvailabilityRow(BaseModel):
    player_identifier: str | None
    player_name: str
    committed: bool
    # Sourced from the squad feed -- role, hand and bowling type, which no
    # other source in this project carries.
    role: str | None
    batting_style: str | None
    bowling_style: str | None
    commitments: list[CommitmentRow]


class AvailabilityWindow(BaseModel):
    date_from: str
    date_to: str
    fixtures_in_window: int
    # How much of the window is actually KNOWN. Absence from a squad means
    # nothing when most fixtures have no squad announced yet.
    fixtures_with_squads: int
    players: list[PlayerAvailabilityRow]
    caveats: dict


class ScoutCandidate(PlayerCountry):
    player_identifier: str
    player_name: str
    matches: int
    role: str | None
    # True when the role came from a squad list; False when inferred from
    # balls faced versus bowled. A scout filtering on role needs to know which.
    role_sourced: bool
    batting_style: str | None
    bowling_style: str | None
    bowling_family: str | None
    age: int | None
    index: float | None
    # As on a selection pick: the raw ratio, with the bounded score beside it.
    form_delta: float | None
    form_score: float | None = None
    form_display: str | None = None
    form_state: str | None
    recent_mean: float | None
    committed_in_window: bool | None
    score: float
    reason: str


class ScoutResult(BaseModel):
    scope: str
    gender: Gender
    candidates_considered: int
    # How many of those have any sourced attribute at all. A hand or bowling
    # filter can only ever match within this subset.
    with_sourced_attributes: int
    unknown_age: int
    # Which constraints in the brief were honoured...
    applied: dict
    # ...and which could not be, with the reason. §17 is explicit that a filter
    # quietly ignoring half the brief is the failure to avoid.
    ignored: dict
    candidates: list[ScoutCandidate]


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
    """How many players matched every filter BEFORE the volume floor, and the
    floor that was actually applied.

    Both are returned because their being different is the whole story on a
    narrowed slice, and without the first a reader cannot tell "no cricket here"
    from "the floor removed all of it". Measured before this existed: a batting
    board for one ground against one side reported 0 players where 148 had
    played, because a 200-ball career floor is unreachable in that cut."""
    total_before_volume_floor: int = 0
    applied_min_balls: int = 0
    applied_min_innings: int = 0
    """The window these figures cover, resolved. A relative window counts back
    from the newest match in the scope rather than from today, and a
    count-bounded one is each player's own last N - neither of which a caller
    can re-derive from the spec alone."""
    period: dict | None = None
    items: list[ExplorerRow]


class SquadMember(PlayerCountry):
    player_identifier: str
    player_name: str
    matches: int
    runs: int
    balls_faced: int
    dismissals: int
    wickets: int
    balls_bowled: int
    runs_conceded: int
    batting_average: float | None
    strike_rate: float | None
    bowling_average: float | None
    economy: float | None
    # INFERRED from where this player spent their deliveries in this window,
    # for this team -- never a sourced fact. See analytics/explorer.discipline.
    role: str
    bowling_share: float | None
    # False when the window holds too few deliveries for the role to be a
    # claim; the UI marks these rather than hiding them.
    role_confident: bool
    last_played: str | None


class IccMover(BaseModel):
    """One player's movement between two published ICC lists.

    `places_gained` is signed so POSITIVE means improvement, despite position 1
    being the top of the list. A board where the best mover shows the most
    negative number is misread every time.
    """

    rank_type: str
    player_name: str
    player_identifier: str | None = None
    country: str | None = None
    country_code: str | None = None
    position: int
    previous_position: int
    places_gained: int
    points: int | None = None
    previous_points: int | None = None
    points_gained: int | None = None


class IccNewEntry(BaseModel):
    """A player in the current list who was not in the previous one.

    Separate from the movers, never counted as one: a player absent from a list
    has no published position, and inventing one to subtract from would
    attribute a move the ICC never published.
    """

    rank_type: str
    player_name: str
    player_identifier: str | None = None
    country: str | None = None
    country_code: str | None = None
    position: int
    points: int | None = None


class IccMovementReport(BaseModel):
    """Movement in one ICC ranking since the previous published list (§8).

    Not a ranking history: `snapshots` reports how many dated lists are held for
    this ranking, and at the time of writing that is a handful spanning weeks
    because the daily sync began recently and the ICC republishes about weekly.
    Drawing a trend over that would present weeks as a career.
    """

    rank_type: str
    current_date: str | None = None
    previous_date: str | None = None
    snapshots: int
    compared: int = 0
    risers: list[IccMover] = []
    fallers: list[IccMover] = []
    new_entries: list[IccNewEntry] = []
    dropped_out: int = 0
    notes: list[str] = []


class StrengthDimension(BaseModel):
    """One dimension of §19's strength profile.

    `score` is a percentile against the CORE sides of the scope, not against the
    average side - there are far more international teams than teams that play
    regularly, so an average-based reference tells every established side it is
    exceptional. Null where no peer figure could be built, never 50, which would
    read as "exactly typical" for a side nobody could measure.
    """

    key: str
    label: str
    value: float | None = None
    unit: str
    score: float | None = None
    peer_value: float | None = None
    peer_sides: int
    basis: str
    """False where the window holds too few matches for the figure to describe
    the side. Marked rather than withheld."""
    reliable: bool = True


class TeamStrengthProfile(BaseModel):
    """A side's depth profile (§19), the other half of the weakness analysis.

    Named `Profile` because `TeamStrengthTable` is already the opposition
    model's fitted difficulty rating, which is a different thing entirely: that
    answers "how hard is this side to face", this answers "where is this side
    deep and where is it thin".
    """

    team_id: int
    team_name: str
    gender: Gender
    team_type: str
    competition_key: str | None = None
    window_matches: int
    matches_in_window: int
    squad_size: int
    first_match: str | None = None
    last_match: str | None = None
    dimensions: list[StrengthDimension] = []
    notes: list[str] = []
    unavailable: dict[str, str] = {}


class SquadAnalysis(BaseModel):
    team_id: int
    team_name: str
    country_code: str | None = None
    gender: Gender
    team_type: str
    # The requested window, and how many matches were actually found in it --
    # a side with 6 matches on record must not look like a 20-match sample.
    window_matches: int
    matches_in_window: int
    first_match: str | None
    last_match: str | None
    members: list[SquadMember]
    role_counts: dict[str, int]
    runs_by_role: dict[str, int]
    wickets_by_role: dict[str, int]
    # Share of the window's runs/wickets taken by the top three contributors.
    top_run_share: float | None
    top_wicket_share: float | None
    reliance_top_n: int
    # What this analysis cannot say, stated in the payload so the UI cannot
    # quietly present a partial picture as a complete one.
    unavailable: list[str]


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
    """0-100 and the figure to show. A percentile of the evidence-weighted move
    within this scope, so it is bounded by construction and orders players the
    same way the boards do. `delta_percent` is the raw ratio and is kept for
    traceability, but it has no ceiling - see analytics/form.stamp_form_scores."""
    form_score: float | None = None
    """The change against baseline in words, never a percentage above 100: past
    a doubling it is stated as a multiple instead."""
    delta_display: str | None = None
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
    # Bounded 0-100 and monotonic with this board's ordering. The percentage
    # above is unbounded and was previously the displayed figure, which meant
    # the column and the sort disagreed.
    form_score: float | None = None
    delta_display: str | None = None
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
    # 0-100. What the card shows, and what sort_by=form orders on.
    form_score: float | None = None
    form_display: str | None = None
    form_confidence: float | None


class PlayerDirectory(BaseModel):
    total: int
    limit: int
    offset: int
    scope: str
    items: list[DirectoryPlayer]
    """The window these figures cover, resolved. A relative window counts back
    from the newest match in the scope rather than from today, and a
    count-bounded one is each player's own last N."""
    period: dict | None = None
    """How many players matched before the volume floor, and the floor applied.
    On a narrowed window the default floor is derived from the slice rather than
    fixed - a 200-ball career qualification is most of a season inside a 30-day
    window, and left fixed it showed 12 of the 71 players who actually batted."""
    total_before_volume_floor: int = 0
    applied_min_balls: int = 0


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


class NewsImage(BaseModel):
    url: str
    """A list-sized rendition. Null when the CDN is unknown; fall back to `url`."""
    thumb_url: str | None = None
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    caption: str | None = None
    credit: str | None = None
    role: str = "hero"
    image_type: str | None = None


class NewsArticleSummary(BaseModel):
    article_id: int
    title: str
    standfirst: str | None
    url: str
    published_at: str | None
    updated_at: str | None
    section: str | None
    word_count: int
    source: str
    publisher: str
    # Carried on every row, not just capped ones, so a client can always tell
    # a short article from a trimmed one.
    content_policy: str
    attribution: str | None
    body_truncated: bool = False
    # Non-null means this body duplicates another article in the archive.
    syndication_of_article_id: int | None = None
    image: NewsImage | None = None


class PaginatedNews(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[NewsArticleSummary]


class NewsTag(BaseModel):
    kind: str
    value: str
    slug: str


class NewsEntity(BaseModel):
    """A link to a player, team or competition, with how it was resolved.

    `confidence` is displayed, not hidden: 'tag_dob' is a publisher tag whose
    date of birth matched, and 'body_name_men_default' is a team name matched
    with the gender defaulted because nothing in the text established one.
    """

    type: str
    mention: str
    confidence: str
    player_identifier: str | None = None
    player_name: str | None = None
    team_id: int | None = None
    team_name: str | None = None
    competition_id: int | None = None
    competition_name: str | None = None


class NewsArticleMetadata(BaseModel):
    meta_title: str | None = None
    meta_description: str | None = None
    schema_type: str | None = None
    open_graph: dict = {}
    twitter: dict = {}


class NewsSyndication(BaseModel):
    article_id: int
    source: str
    url: str


class NewsArticleDetail(NewsArticleSummary):
    body_text: str | None = None
    body_html: str | None = None
    authors: list[str] = []
    tags: list[NewsTag] = []
    entities: list[NewsEntity] = []
    images: list[NewsImage] = []
    metadata: NewsArticleMetadata | None = None
    syndications: list[NewsSyndication] = []


class NewsSourceInfo(BaseModel):
    key: str
    name: str
    home_url: str | None
    strategy: str
    content_policy: str
    attribution: str | None
    policy_note: str | None
    enabled: bool
    last_synced_at: str | None
    articles: int


class NewsSourceHealth(BaseModel):
    source: str
    articles: int
    latest: str | None
    with_hero: int
    linked_players: int


class NewsDegradedFeed(BaseModel):
    source: str
    feed: str
    failures: int
    last_status: int | None
    last_fetched_at: str | None


class NewsHealth(BaseModel):
    ledger: dict[str, int]
    sources: list[NewsSourceHealth]
    degraded_feeds: list[NewsDegradedFeed]
    syndicated: int
    entity_links: dict[str, int]
