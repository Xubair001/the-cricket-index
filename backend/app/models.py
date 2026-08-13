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
    win_by_runs: Mapped[int | None]
    win_by_wickets: Mapped[int | None]
    outcome_result: Mapped[str | None]
    player_of_match: Mapped[str | None]

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
