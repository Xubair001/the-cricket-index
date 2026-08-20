from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    gender: Mapped[str]
    team_type: Mapped[str]


class Competition(Base):
    __tablename__ = "competitions"

    competition_id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str]
    display_name: Mapped[str]
    type: Mapped[str]
    gender: Mapped[str]


class Season(Base):
    __tablename__ = "seasons"

    season_id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.competition_id"))
    label: Mapped[str]


class Player(Base):
    __tablename__ = "players"

    identifier: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    gender: Mapped[str]
    date_of_birth: Mapped[str | None]
    birth_place: Mapped[str | None]
    nationality: Mapped[str | None]
    cricinfo_id: Mapped[str | None]
    bio_source: Mapped[str | None]
    # Sourced career-end signals, never inferred. See queries.player_status for
    # how these combine with last-appearance data into a displayed status.
    date_of_death: Mapped[str | None]
    retirement_date: Mapped[str | None]
    # Wikidata label ("Joe Root") beside the scorecard name ("JE Root").
    display_name: Mapped[str | None]
    image_url: Mapped[str | None]


class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.competition_id"))
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.season_id"))
    gender: Mapped[str]
    data_granularity: Mapped[str]
    content_hash: Mapped[str | None]
    match_type: Mapped[str | None]
    team_type: Mapped[str | None]
    season_label: Mapped[str | None]
    event_name: Mapped[str | None]
    match_number: Mapped[int | None]
    # Cricsheet's event.stage / event.group. Sparse, and stage is what names a
    # Final - the only sourced route to a tournament's champion.
    event_stage: Mapped[str | None]
    event_group: Mapped[str | None]
    venue: Mapped[str | None]
    city: Mapped[str | None]
    match_date_start: Mapped[str | None]
    match_date_end: Mapped[str | None]
    overs_limit: Mapped[int | None]
    team1_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    team2_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    toss_winner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    toss_decision: Mapped[str | None]
    winner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    # Who took a TIED match on a tiebreak. Cricsheet reports it as
    # outcome.eliminator and not as outcome.winner, so a tied match has
    # winner_team_id NULL however it was actually settled - the 2019 World Cup
    # final among them. Kept separate rather than folded in, because every
    # aggregate that counts wins is right to keep excluding it.
    eliminator_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    win_by_runs: Mapped[int | None]
    win_by_wickets: Mapped[int | None]
    outcome_result: Mapped[str | None]
    player_of_match: Mapped[str | None]
    # 'cricsheet' (ball-by-ball derived, has `deliveries`) or 'icc' (ICC's own
    # computed scorecard, no deliveries). See ingestion/schema.sql.
    source: Mapped[str]
    natural_key: Mapped[str | None]

    competition: Mapped["Competition"] = relationship()
    player_stats: Mapped[list["PlayerMatchStat"]] = relationship(back_populates="match")


class PlayerMatchStat(Base):
    __tablename__ = "player_match_stats"

    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"), primary_key=True)
    player_name: Mapped[str] = mapped_column(primary_key=True)
    player_identifier: Mapped[str | None] = mapped_column(ForeignKey("players.identifier"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"))
    runs_scored: Mapped[int]
    balls_faced: Mapped[int]
    fours: Mapped[int]
    sixes: Mapped[int]
    dismissals: Mapped[int]
    wickets_taken: Mapped[int]
    balls_bowled: Mapped[int]
    runs_conceded: Mapped[int]

    match: Mapped["Match"] = relationship(back_populates="player_stats")


class FixtureSquad(Base):
    """An announced squad for a fixture, from the ICC scorecard feed.

    Kept separate from `players` for the same reason ICC rankings are: this is
    ICC's claim about their own squad lists, and a role here is a fact about a
    fixture rather than a permanent property -- a player can be named as keeper
    in one squad and a batter in another.
    """

    __tablename__ = "fixture_squads"

    icc_match_id: Mapped[str] = mapped_column(
        ForeignKey("fixtures.icc_match_id"), primary_key=True
    )
    icc_team_id: Mapped[str] = mapped_column(primary_key=True)
    player_name: Mapped[str] = mapped_column(primary_key=True)
    team_name: Mapped[str | None]
    player_identifier: Mapped[str | None] = mapped_column(
        ForeignKey("players.identifier")
    )
    position: Mapped[int | None]
    is_captain: Mapped[int]
    role: Mapped[str | None]            # Batter | Bowler | All-Rounder | Wicket Keeper
    batting_style: Mapped[str | None]   # RHB | LHB
    bowling_style: Mapped[str | None]   # RM, RFM, OB, SLO, LB ...
    status: Mapped[str | None]          # ICC's own wording, passed through
    fetched_at: Mapped[str]


class Delivery(Base):
    """One ball. ~4.8M rows - see ingestion/schema.sql for the storage notes.

    Read by the splits and phase analytics, never by a list endpoint: §28
    forbids a page request touching raw ball-by-ball data, which is why the
    per-match aggregates in `player_match_stats` still exist beside this.
    """

    __tablename__ = "deliveries"

    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"), primary_key=True)
    innings: Mapped[int] = mapped_column(primary_key=True)
    # Position within the innings. The key cannot be (over, ball): a wide or
    # no-ball adds a delivery to the over, so that pair is not unique.
    seq: Mapped[int] = mapped_column(primary_key=True)
    over: Mapped[int]
    ball: Mapped[int]
    batting_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    batter: Mapped[str | None] = mapped_column(ForeignKey("players.identifier"))
    bowler: Mapped[str | None] = mapped_column(ForeignKey("players.identifier"))
    non_striker: Mapped[str | None] = mapped_column(ForeignKey("players.identifier"))
    runs_batter: Mapped[int]
    runs_extras: Mapped[int]
    runs_total: Mapped[int]
    non_boundary: Mapped[int]
    wides: Mapped[int]
    noballs: Mapped[int]
    byes: Mapped[int]
    legbyes: Mapped[int]
    wicket_kind: Mapped[str | None]
    player_out: Mapped[str | None] = mapped_column(ForeignKey("players.identifier"))
    # Who effected the dismissal. This is what identifies a wicketkeeper: only
    # a keeper can stump, and a keeper takes far more catches than any other
    # fielder. See ingestion/schema.sql.
    fielder: Mapped[str | None] = mapped_column(ForeignKey("players.identifier"))


class PlayerCareerTotal(Base):
    __tablename__ = "player_career_totals"

    player_identifier: Mapped[str] = mapped_column(
        ForeignKey("players.identifier"), primary_key=True
    )
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.competition_id"), primary_key=True
    )
    source: Mapped[str]
    matches: Mapped[int]
    runs_scored: Mapped[int]
    balls_faced: Mapped[int]
    dismissals: Mapped[int]
    wickets_taken: Mapped[int]
    balls_bowled: Mapped[int]
    runs_conceded: Mapped[int]


class IccPlayerRanking(Base):
    """ICC's published player ratings. Not computed here -- see schema.sql."""

    __tablename__ = "icc_player_rankings"

    rank_type: Mapped[str] = mapped_column(primary_key=True)
    rank_date: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    icc_player_id: Mapped[str | None]
    # Part of the key: ICC ties share a position, so (type, date, position)
    # alone is not unique. Omitting it here collapses tied players into one ORM
    # identity, and the session then yields the same row twice.
    player_name: Mapped[str] = mapped_column(primary_key=True)
    country: Mapped[str | None]
    points: Mapped[int | None]
    career_best: Mapped[str | None]
    player_identifier: Mapped[str | None] = mapped_column(ForeignKey("players.identifier"))
    fetched_at: Mapped[str]


class IccTeamRanking(Base):
    __tablename__ = "icc_team_rankings"

    rank_type: Mapped[str] = mapped_column(primary_key=True)
    rank_date: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    icc_team_id: Mapped[str | None]
    team_name: Mapped[str] = mapped_column(primary_key=True)  # ties, as above
    points: Mapped[int | None]
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    fetched_at: Mapped[str]


class Fixture(Base):
    """ICC schedule entry: completed, live or upcoming. Not a `matches` row."""

    __tablename__ = "fixtures"

    icc_match_id: Mapped[str] = mapped_column(primary_key=True)
    series_id: Mapped[str | None]
    series_name: Mapped[str | None]
    tour_name: Mapped[str | None]
    comp_type: Mapped[str | None]
    match_type: Mapped[str | None]
    gender: Mapped[str | None]
    match_number: Mapped[str | None]
    match_status: Mapped[str | None]
    is_upcoming: Mapped[int]
    is_live: Mapped[int]
    start_date: Mapped[str | None]
    end_date: Mapped[str | None]
    start_time_gmt: Mapped[str | None]
    venue: Mapped[str | None]
    country: Mapped[str | None]
    team_a_name: Mapped[str | None]
    team_a_short: Mapped[str | None]
    team_b_name: Mapped[str | None]
    team_b_short: Mapped[str | None]
    team_a_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    team_b_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    match_result: Mapped[str | None]
    winning_team_name: Mapped[str | None]
    toss_won_by: Mapped[str | None]
    toss_elected_to: Mapped[str | None]
    content_hash: Mapped[str]
    fetched_at: Mapped[str]


class IngestionProgress(Base):
    __tablename__ = "ingestion_progress"

    competition_key: Mapped[str] = mapped_column(primary_key=True)
    total_matches: Mapped[int]
    processed_matches: Mapped[int]
    skipped_matches: Mapped[int]
    failed_matches: Mapped[int]


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------
# Written by ingestion/news_activities.py. Read-only on this side, as every
# other table here is. See ingestion/schema.sql for why content, SEO metadata
# and the ingestion ledger are three separate tables rather than one wide row.


class NewsPublisher(Base):
    __tablename__ = "news_publishers"

    publisher_id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str]
    name: Mapped[str]
    home_url: Mapped[str | None]
    strategy: Mapped[str]
    # 'full' | 'extract' | 'metadata_only'. Enforced when serving, not just
    # recorded: news.article_body() caps what an 'extract' publisher returns.
    content_policy: Mapped[str]
    attribution: Mapped[str | None]
    policy_note: Mapped[str | None]
    enabled: Mapped[int]
    last_synced_at: Mapped[str | None]


class NewsArticle(Base):
    __tablename__ = "news_articles"

    article_id: Mapped[int] = mapped_column(primary_key=True)
    publisher_id: Mapped[int] = mapped_column(ForeignKey("news_publishers.publisher_id"))
    source_key: Mapped[str]
    source_article_id: Mapped[str | None]
    canonical_url: Mapped[str]
    url_fingerprint: Mapped[str]
    discovered_url: Mapped[str | None]
    title: Mapped[str]
    standfirst: Mapped[str | None]
    body_html: Mapped[str | None]
    body_text: Mapped[str | None]
    word_count: Mapped[int]
    declared_word_count: Mapped[int | None]
    published_at: Mapped[str | None]
    updated_at: Mapped[str | None]
    section: Mapped[str | None]
    language: Mapped[str | None]
    sport: Mapped[str]
    content_hash: Mapped[str]
    text_simhash: Mapped[str | None]
    # Points at the article whose body this one duplicates. Not a delete: a
    # wire story running in three places is a fact worth keeping.
    syndication_of_article_id: Mapped[int | None] = mapped_column(
        ForeignKey("news_articles.article_id")
    )
    first_seen_at: Mapped[str]
    last_seen_at: Mapped[str]


class NewsArticleMetadata(Base):
    __tablename__ = "news_article_metadata"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.article_id"), primary_key=True
    )
    meta_title: Mapped[str | None]
    meta_description: Mapped[str | None]
    og_json: Mapped[str | None]
    twitter_json: Mapped[str | None]
    json_ld: Mapped[str | None]
    schema_type: Mapped[str | None]


class NewsAuthor(Base):
    __tablename__ = "news_authors"

    author_id: Mapped[int] = mapped_column(primary_key=True)
    publisher_id: Mapped[int] = mapped_column(ForeignKey("news_publishers.publisher_id"))
    name: Mapped[str]


class NewsArticleAuthor(Base):
    __tablename__ = "news_article_authors"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.article_id"), primary_key=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("news_authors.author_id"), primary_key=True
    )
    position: Mapped[int]


class NewsTag(Base):
    __tablename__ = "news_tags"

    tag_id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    value: Mapped[str]
    slug: Mapped[str]


class NewsArticleTag(Base):
    __tablename__ = "news_article_tags"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.article_id"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("news_tags.tag_id"), primary_key=True)


class NewsImage(Base):
    """A referenced image, never a stored one. See schema.sql for why."""

    __tablename__ = "news_images"

    image_id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str]
    provider: Mapped[str | None]
    cdn_url: Mapped[str]
    thumb_url: Mapped[str | None]
    origin_url: Mapped[str | None]
    width: Mapped[int | None]
    height: Mapped[int | None]
    mime_type: Mapped[str | None]
    byte_size: Mapped[int | None]
    probed_at: Mapped[str | None]
    probe_status: Mapped[str | None]


class NewsArticleImage(Base):
    """Caption, credit and alt live HERE, not on the image.

    The same photograph is reused across articles with a different caption
    each time, so storing them on the asset would have the last article
    ingested overwrite every earlier one's caption.
    """

    __tablename__ = "news_article_images"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.article_id"), primary_key=True
    )
    image_id: Mapped[int] = mapped_column(
        ForeignKey("news_images.image_id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int]
    alt_text: Mapped[str | None]
    caption: Mapped[str | None]
    credit: Mapped[str | None]
    image_type: Mapped[str | None]


class NewsArticleEntity(Base):
    """A resolved link to a player, team or competition.

    A row exists only when something actually resolved. An article mentioning
    a player who cannot be identified confidently has no row here, the same
    rule icc_player_rankings.player_identifier follows.
    """

    __tablename__ = "news_article_entities"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.article_id"), primary_key=True
    )
    entity_type: Mapped[str] = mapped_column(primary_key=True)
    mention: Mapped[str] = mapped_column(primary_key=True)
    player_identifier: Mapped[str | None] = mapped_column(
        ForeignKey("players.identifier")
    )
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    competition_id: Mapped[int | None] = mapped_column(
        ForeignKey("competitions.competition_id")
    )
    confidence: Mapped[str]


class NewsIngestion(Base):
    """The work ledger, keyed on the URL rather than on an article.

    A URL that failed to extract has a row here and NO article row anywhere,
    which is what stops a partial scrape being mistaken for a stored article.
    """

    __tablename__ = "news_ingestions"

    url_fingerprint: Mapped[str] = mapped_column(primary_key=True)
    source_key: Mapped[str]
    url: Mapped[str]
    article_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.article_id"))
    status: Mapped[str]
    extractor_version: Mapped[int]
    http_status: Mapped[int | None]
    etag: Mapped[str | None]
    last_modified: Mapped[str | None]
    content_hash: Mapped[str | None]
    attempts: Mapped[int]
    last_error: Mapped[str | None]
    problems: Mapped[str | None]
    first_attempt_at: Mapped[str | None]
    last_attempt_at: Mapped[str | None]
    next_attempt_after: Mapped[str | None]


class NewsFeedState(Base):
    __tablename__ = "news_feed_state"

    feed_url: Mapped[str] = mapped_column(primary_key=True)
    source_key: Mapped[str]
    etag: Mapped[str | None]
    last_modified: Mapped[str | None]
    last_fetched_at: Mapped[str | None]
    last_status: Mapped[int | None]
    consecutive_failures: Mapped[int]
    items_last_seen: Mapped[int]
