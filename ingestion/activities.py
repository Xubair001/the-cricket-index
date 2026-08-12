import hashlib
import json
import logging
import os
import sqlite3
import zipfile

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from db import get_connection
from parsing import parse_match
from shared import (
    PROJECT_ROOT,
    COMPETITION_META,
    CRICSHEET_URLS,
    TEAM_TYPE_BY_COMPETITION_TYPE,
    DownloadResult,
    MatchIngestionInput,
    MatchIngestionResult,
)

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")


def _get_or_create_team(conn: sqlite3.Connection, name: str, gender: str, team_type: str) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO teams (name, gender, team_type) VALUES (?, ?, ?)",
        (name, gender, team_type),
    )
    row = conn.execute(
        "SELECT team_id FROM teams WHERE name = ? AND gender = ? AND team_type = ?",
        (name, gender, team_type),
    ).fetchone()
    return row[0]


def _get_or_create_competition(
    conn: sqlite3.Connection, key: str, gender: str, display_name: str, comp_type: str
) -> int:
    conn.execute(
        """INSERT OR IGNORE INTO competitions (key, gender, display_name, type)
           VALUES (?, ?, ?, ?)""",
        (key, gender, display_name, comp_type),
    )
    row = conn.execute(
        "SELECT competition_id FROM competitions WHERE key = ? AND gender = ?",
        (key, gender),
    ).fetchone()
    return row[0]


def _get_or_create_season(conn: sqlite3.Connection, competition_id: int, label: str | None) -> int | None:
    if not label:
        return None
    conn.execute(
        "INSERT OR IGNORE INTO seasons (competition_id, label) VALUES (?, ?)",
        (competition_id, label),
    )
    row = conn.execute(
        "SELECT season_id FROM seasons WHERE competition_id = ? AND label = ?",
        (competition_id, label),
    ).fetchone()
    return row[0]


@activity.defn
async def download_archive(competition: str) -> DownloadResult:
    """Downloads the competition's zip archive if not already cached.

    Deliberately does NOT extract it: match files are read directly out of
    the zip on demand (see ingest_match), so disk usage stays bounded to the
    compressed archive itself (tens of MB) instead of the full extracted
    JSON tree (hundreds of MB).
    """
    if competition not in CRICSHEET_URLS:
        raise ApplicationError(f"unknown competition '{competition}'", non_retryable=True)

    os.makedirs(DATA_DIR, exist_ok=True)
    archive_path = os.path.join(DATA_DIR, f"{competition}.zip")

    if not os.path.exists(archive_path):
        activity.logger.info(f"Downloading {competition} archive from Cricsheet")
        url = CRICSHEET_URLS[competition]
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            with open(archive_path, "wb") as f:
                f.write(resp.content)
    else:
        activity.logger.info(f"Using cached archive for {competition}")

    with zipfile.ZipFile(archive_path) as z:
        match_ids = sorted(
            name[:-5]
            for name in z.namelist()
            if name.endswith(".json") and name != "README.txt"
        )

    activity.logger.info(f"{competition}: discovered {len(match_ids)} matches")
    return DownloadResult(
        competition=competition, archive_path=archive_path, match_ids=match_ids
    )


@activity.defn
async def ingest_match(input: MatchIngestionInput) -> MatchIngestionResult:
    try:
        with zipfile.ZipFile(input.archive_path) as z:
            raw_bytes = z.read(f"{input.match_id}.json")
    except KeyError as e:
        raise ApplicationError(
            f"{input.match_id}.json not found in {input.archive_path}: {e}",
            non_retryable=True,
        )

    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT content_hash FROM matches WHERE match_id = ?", (input.match_id,)
        ).fetchone()
        if row is not None and row[0] == content_hash:
            return MatchIngestionResult(match_id=input.match_id, success=True, skipped=True)

    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as e:
        raise ApplicationError(f"malformed JSON for {input.match_id}: {e}", non_retryable=True)

    match = parse_match(input.match_id, input.competition, raw)

    if match.gender not in ("male", "female"):
        raise ApplicationError(
            f"{input.match_id}: missing/unrecognized gender '{match.gender}'", non_retryable=True
        )

    display_name, comp_type = COMPETITION_META[input.competition]
    team_type = TEAM_TYPE_BY_COMPETITION_TYPE[comp_type]

    with get_connection() as conn:
        competition_id = _get_or_create_competition(
            conn, input.competition, match.gender, display_name, comp_type
        )
        season_id = _get_or_create_season(conn, competition_id, match.season)

        team_ids: dict[str, int] = {
            name: _get_or_create_team(conn, name, match.gender, team_type)
            for name in match.teams
        }
        team1_id = team_ids.get(match.team1) if match.team1 else None
        team2_id = team_ids.get(match.team2) if match.team2 else None
        toss_winner_team_id = team_ids.get(match.toss_winner) if match.toss_winner else None
        winner_team_id = team_ids.get(match.winner) if match.winner else None

        for name, identifier in match.players.items():
            conn.execute(
                """INSERT INTO players (identifier, name, gender) VALUES (?, ?, ?)
                   ON CONFLICT(identifier) DO UPDATE SET name = excluded.name""",
                (identifier, name, match.gender),
            )

        conn.execute(
            """INSERT INTO matches (
                match_id, competition_id, season_id, gender, data_granularity,
                content_hash, match_type, team_type, season_label, event_name,
                match_number, venue, city, match_date_start, match_date_end,
                overs_limit, team1_id, team2_id, toss_winner_team_id,
                toss_decision, winner_team_id, win_by_runs, win_by_wickets,
                outcome_result, player_of_match
            ) VALUES (?, ?, ?, ?, 'full', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                competition_id=excluded.competition_id, season_id=excluded.season_id,
                gender=excluded.gender, content_hash=excluded.content_hash,
                match_type=excluded.match_type, team_type=excluded.team_type,
                season_label=excluded.season_label, event_name=excluded.event_name,
                match_number=excluded.match_number, venue=excluded.venue, city=excluded.city,
                match_date_start=excluded.match_date_start,
                match_date_end=excluded.match_date_end,
                overs_limit=excluded.overs_limit, team1_id=excluded.team1_id,
                team2_id=excluded.team2_id, toss_winner_team_id=excluded.toss_winner_team_id,
                toss_decision=excluded.toss_decision, winner_team_id=excluded.winner_team_id,
                win_by_runs=excluded.win_by_runs, win_by_wickets=excluded.win_by_wickets,
                outcome_result=excluded.outcome_result, player_of_match=excluded.player_of_match
            """,
            (
                match.match_id, competition_id, season_id, match.gender, content_hash,
                match.match_type, match.team_type, match.season, match.event_name,
                match.match_number, match.venue, match.city, match.match_date_start,
                match.match_date_end, match.overs_limit, team1_id, team2_id,
                toss_winner_team_id, match.toss_decision, winner_team_id,
                match.win_by_runs, match.win_by_wickets, match.outcome_result,
                match.player_of_match,
            ),
        )

        conn.execute(
            "DELETE FROM player_match_stats WHERE match_id = ?", (match.match_id,)
        )
        conn.executemany(
            """INSERT INTO player_match_stats (
                match_id, player_identifier, player_name, team_id, runs_scored,
                balls_faced, fours, sixes, dismissals, wickets_taken,
                balls_bowled, runs_conceded
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    match.match_id, match.players.get(s.player_name), s.player_name,
                    team_ids[s.team], s.runs_scored, s.balls_faced, s.fours, s.sixes,
                    s.dismissals, s.wickets_taken, s.balls_bowled, s.runs_conceded,
                )
                for s in match.player_match_stats
            ],
        )
        conn.commit()

    return MatchIngestionResult(match_id=input.match_id, success=True)


@activity.defn
async def record_progress(
    competition: str, total: int, processed: int, skipped: int, failed: int
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO ingestion_progress (
                competition_key, total_matches, processed_matches, skipped_matches, failed_matches
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(competition_key) DO UPDATE SET
                total_matches=excluded.total_matches,
                processed_matches=excluded.processed_matches,
                skipped_matches=excluded.skipped_matches,
                failed_matches=excluded.failed_matches""",
            (competition, total, processed, skipped, failed),
        )
        conn.commit()
