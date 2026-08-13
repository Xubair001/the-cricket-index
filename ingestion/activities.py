import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import zipfile
from datetime import datetime, timezone

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from db import get_connection
from parsing import parse_match
from enrichment import (
    CRICSHEET_PEOPLE_REGISTER,
    ICC_SCHEDULE_ENDPOINT,
    ICC_SCHEDULE_PAGE_SIZE,
    parse_fixture,
    ICC_CLIENT_ID,
    ICC_COMP_TYPES,
    ICC_RANKING_ENDPOINT,
    ICC_TEAM_TYPE,
    WIKIDATA_ENDPOINT,
    build_name_index,
    parse_icc_rankings,
    parse_people_register,
    parse_wikidata_rows,
    resolve_player,
    wikidata_query,
)
from shared import (
    PROJECT_ROOT,
    COMPETITION_META,
    CRICSHEET_URLS,
    PARSER_VERSION,
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

    # Version-namespaced: the hash has to change when the PARSER changes, not
    # only when Cricsheet's bytes do. See shared.PARSER_VERSION.
    content_hash = hashlib.sha256(
        f"v{PARSER_VERSION}\n".encode() + raw_bytes
    ).hexdigest()

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
async def sync_people_register() -> int:
    """Populates players.cricinfo_id from Cricsheet's own people register.

    This is what makes the Wikidata join exact rather than name-based: the
    register carries an ESPNcricinfo key for 99.8% of people, and Wikidata
    indexes the same key as P2697. Only players already in our DB are touched.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
        resp = await client.get(CRICSHEET_PEOPLE_REGISTER)
        resp.raise_for_status()
        mapping = parse_people_register(resp.text)

    activity.logger.info(f"people register: {len(mapping)} cricinfo keys")
    updated = 0
    with get_connection() as conn:
        known = {row[0] for row in conn.execute("SELECT identifier FROM players")}
        rows = [(cid, ident) for ident, cid in mapping.items() if ident in known]
        conn.executemany(
            "UPDATE players SET cricinfo_id = ? WHERE identifier = ?", rows
        )
        updated = len(rows)
        conn.commit()
    return updated


async def _wikidata_get(client, query: str, batch_index: int, attempts: int = 4):
    """GETs one SPARQL batch, backing off on throttling.

    Wikidata's public endpoint burst-throttles with 429 and no Retry-After, so
    the wait is exponential (2s, 4s, 8s) unless the header says otherwise.
    Returns None once retries are exhausted, and the caller counts that as a
    failed batch rather than an empty answer.
    """
    delay = 2.0
    for attempt in range(attempts):
        resp = await client.get(WIKIDATA_ENDPOINT, params={"query": query, "format": "json"})
        if resp.status_code == 200:
            return resp
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = float(resp.headers.get("retry-after") or delay)
            activity.logger.info(
                f"wikidata batch {batch_index}: HTTP {resp.status_code}, "
                f"retrying in {wait:.0f}s ({attempt + 1}/{attempts})"
            )
            await asyncio.sleep(wait)
            delay *= 2
            continue
        activity.logger.warning(
            f"wikidata batch {batch_index}: HTTP {resp.status_code} (not retryable)"
        )
        return None
    return None


@activity.defn
async def enrich_from_wikidata(batch_size: int = 200) -> dict:
    """Fills bio fields for players that have a cricinfo_id.

    Writes only what Wikidata actually returns -- a player with no match keeps
    NULLs and the UI keeps saying "Not available". `bio_source` is set only on
    rows that received at least one real value, so it stays a truthful record
    of provenance rather than a marker that we tried.
    """
    with get_connection() as conn:
        pending = [
            row[0]
            for row in conn.execute(
                "SELECT cricinfo_id FROM players WHERE cricinfo_id IS NOT NULL"
            )
        ]

    stats = {
        "queried": len(pending), "matched": 0, "batches": 0, "failed_batches": 0,
        "retirement_dates": 0, "display_names": 0, "images": 0,
    }
    headers = {
        # Wikidata asks that clients identify themselves.
        "User-Agent": "TheCricketIndex/1.0 (cricket stats project; Wikidata enrichment)",
        "Accept": "application/sparql-results+json",
    }
    total_batches = (len(pending) + batch_size - 1) // batch_size

    async with httpx.AsyncClient(follow_redirects=True, timeout=180, headers=headers) as client:
        for start in range(0, len(pending), batch_size):
            chunk = pending[start : start + batch_size]
            resp = await _wikidata_get(client, wikidata_query(chunk), start // batch_size)
            if resp is None:
                stats["failed_batches"] += 1
                continue
            records = parse_wikidata_rows(resp.json())
            stats["batches"] += 1
            stats["matched"] += len(records)
            stats["retirement_dates"] += sum(
                1 for r in records.values() if r.get("retirement_date")
            )
            stats["display_names"] += sum(1 for r in records.values() if r.get("display_name"))
            stats["images"] += sum(1 for r in records.values() if r.get("image_url"))

            with get_connection() as conn:
                conn.executemany(
                    """UPDATE players SET
                         display_name    = COALESCE(?, display_name),
                         image_url       = COALESCE(?, image_url),
                         date_of_birth   = COALESCE(?, date_of_birth),
                         date_of_death   = COALESCE(?, date_of_death),
                         retirement_date = COALESCE(?, retirement_date),
                         birth_place     = COALESCE(?, birth_place),
                         nationality     = COALESCE(?, nationality),
                         bio_source      = 'wikidata'
                       WHERE cricinfo_id = ?""",
                    [
                        (
                            r["display_name"], r["image_url"],
                            r["date_of_birth"], r["date_of_death"], r["retirement_date"],
                            r["birth_place"], r["nationality"], cid,
                        )
                        for cid, r in records.items()
                    ],
                )
                conn.commit()
            # Wikidata's public endpoint is a shared resource; don't hammer it.
            await asyncio.sleep(1.0)

    activity.logger.info(f"wikidata enrichment: {stats}")
    # A throttled run used to look exactly like a successful one -- every batch
    # 429s, each is logged and skipped, and the activity returns "0 matched" as
    # though Wikidata simply knew nobody. Fail instead, so Temporal retries and
    # the result can't be mistaken for an answer.
    if total_batches and stats["failed_batches"] * 2 > total_batches:
        raise ApplicationError(
            f"wikidata enrichment failed for {stats['failed_batches']} of "
            f"{total_batches} batches (rate limiting or endpoint trouble); "
            f"not reporting partial results as success"
        )
    return stats


@activity.defn
async def fetch_icc_feed(comp_type: str, feed_type: str) -> dict:
    """Fetches and stores one ICC ranking feed.

    Each (comp_type, feed_type) pair is its own activity so a single flaky feed
    retries on its own instead of restarting all twenty.
    """
    params = {
        "client_id": ICC_CLIENT_ID,
        "lang": "en",
        "feed_format": "json",
        "comp_type": comp_type,
        "type": feed_type,
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(ICC_RANKING_ENDPOINT, params=params)
        resp.raise_for_status()
        payload = resp.json()

    rank_type, rank_date, entries = parse_icc_rankings(payload)
    if not rank_type or not entries:
        # Women's Test rankings don't exist; an empty feed is expected there
        # and is not an error worth retrying.
        activity.logger.info(f"icc {comp_type}/{feed_type}: no data")
        return {"comp_type": comp_type, "type": feed_type, "stored": 0, "linked": 0}

    gender = ICC_COMP_TYPES[comp_type][0]
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection() as conn:
        if feed_type == ICC_TEAM_TYPE:
            stored = _store_team_rankings(conn, rank_type, rank_date, entries, gender, fetched_at)
            linked = 0
        else:
            stored, linked = _store_player_rankings(
                conn, rank_type, rank_date, entries, gender, fetched_at
            )
        conn.commit()

    activity.logger.info(
        f"icc {rank_type} @ {rank_date}: stored {stored}, linked {linked}"
    )
    return {
        "comp_type": comp_type, "type": feed_type, "rank_type": rank_type,
        "rank_date": rank_date, "stored": stored, "linked": linked,
    }


def _store_player_rankings(conn, rank_type, rank_date, entries, gender, fetched_at):
    players = conn.execute(
        "SELECT identifier, name, gender FROM players WHERE gender = ?", (gender,)
    ).fetchall()
    index = build_name_index([(r[0], r[1], r[2]) for r in players])

    # Country per player, used only to break ties between same-key candidates.
    country_lookup: dict[str, set[str]] = {}
    for ident, team_name in conn.execute(
        """SELECT DISTINCT pms.player_identifier, t.name
             FROM player_match_stats pms
             JOIN teams t ON t.team_id = pms.team_id
            WHERE t.team_type = 'international' AND pms.player_identifier IS NOT NULL"""
    ):
        country_lookup.setdefault(ident, set()).add(team_name)

    rows, linked = [], 0
    for e in entries:
        identifier = resolve_player(
            index, e["player_name"], gender, country_lookup, e.get("country")
        )
        if identifier:
            linked += 1
        rows.append(
            (
                rank_type, rank_date, e["position"], e["icc_player_id"], e["player_name"],
                e["country"], e["points"], e["career_best"], identifier, fetched_at,
            )
        )

    conn.executemany(
        """INSERT INTO icc_player_rankings (
               rank_type, rank_date, position, icc_player_id, player_name,
               country, points, career_best, player_identifier, fetched_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(rank_type, rank_date, position, player_name) DO UPDATE SET
               icc_player_id=excluded.icc_player_id,
               country=excluded.country, points=excluded.points,
               career_best=excluded.career_best,
               player_identifier=excluded.player_identifier,
               fetched_at=excluded.fetched_at""",
        rows,
    )
    return len(rows), linked


def _store_team_rankings(conn, rank_type, rank_date, entries, gender, fetched_at):
    known = {
        name.lower(): team_id
        for team_id, name in conn.execute(
            "SELECT team_id, name FROM teams WHERE gender = ? AND team_type = 'international'",
            (gender,),
        )
    }
    rows = [
        (
            rank_type, rank_date, e["position"], e.get("team_id"),
            e["team_name"] or e["player_name"], e["points"],
            known.get((e["team_name"] or "").lower()), fetched_at,
        )
        for e in entries
    ]
    conn.executemany(
        """INSERT INTO icc_team_rankings (
               rank_type, rank_date, position, icc_team_id, team_name,
               points, team_id, fetched_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(rank_type, rank_date, position, team_name) DO UPDATE SET
               icc_team_id=excluded.icc_team_id,
               points=excluded.points, team_id=excluded.team_id,
               fetched_at=excluded.fetched_at""",
        rows,
    )
    return len(rows)


@activity.defn
async def fetch_icc_fixtures(from_date: str, to_date: str) -> dict:
    """Fetches fixtures in a date window and upserts only what changed.

    Each fixture is SHA-256-hashed from its raw feed object and compared
    against the stored hash, the same idempotency contract `ingest_match` uses
    for Cricsheet. A daily run therefore rewrites only genuinely-changed rows
    (a scoreline landing, a start time moving) rather than all ~12,000.

    `from_date`/`to_date` are YYYYMMDD. Note the feed paginates on
    `page_number`; `page` is accepted and ignored, which silently returns page
    one every time.
    """
    stored = skipped = 0
    page_number = 1
    total = None
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async with httpx.AsyncClient(follow_redirects=True, timeout=90) as client:
        while True:
            resp = await client.get(
                ICC_SCHEDULE_ENDPOINT,
                params={
                    "client_id": ICC_CLIENT_ID,
                    "feed_format": "json",
                    "lang": "en",
                    "is_deleted": "false",
                    "pagination": "true",
                    "page_number": page_number,
                    "page_size": ICC_SCHEDULE_PAGE_SIZE,
                    "from_date": from_date,
                    "to_date": to_date,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            matches = ((payload.get("data") or {}).get("matches")) or []
            if total is None:
                total = (payload.get("meta") or {}).get("count") or 0
            if not matches:
                break

            with get_connection() as conn:
                team_lookup = {
                    (name.lower(), gender): team_id
                    for team_id, name, gender in conn.execute(
                        "SELECT team_id, name, gender FROM teams WHERE team_type = 'international'"
                    )
                }
                for raw in matches:
                    row = parse_fixture(raw)
                    if row is None:
                        continue
                    content_hash = hashlib.sha256(
                        json.dumps(raw, sort_keys=True, default=str).encode()
                    ).hexdigest()
                    existing = conn.execute(
                        "SELECT content_hash FROM fixtures WHERE icc_match_id = ?",
                        (row["icc_match_id"],),
                    ).fetchone()
                    if existing and existing[0] == content_hash:
                        skipped += 1
                        continue

                    gender = row["gender"]
                    row["team_a_id"] = team_lookup.get(
                        ((row["team_a_name"] or "").lower(), gender)
                    )
                    row["team_b_id"] = team_lookup.get(
                        ((row["team_b_name"] or "").lower(), gender)
                    )
                    row["content_hash"] = content_hash
                    row["fetched_at"] = fetched_at
                    columns = ", ".join(row)
                    placeholders = ", ".join("?" for _ in row)
                    updates = ", ".join(
                        f"{c}=excluded.{c}" for c in row if c != "icc_match_id"
                    )
                    conn.execute(
                        f"""INSERT INTO fixtures ({columns}) VALUES ({placeholders})
                            ON CONFLICT(icc_match_id) DO UPDATE SET {updates}""",
                        list(row.values()),
                    )
                    stored += 1
                conn.commit()

            if len(matches) < ICC_SCHEDULE_PAGE_SIZE:
                break
            page_number += 1

    activity.logger.info(
        f"icc fixtures {from_date}-{to_date}: {stored} written, {skipped} unchanged, feed total {total}"
    )
    return {"from_date": from_date, "to_date": to_date, "stored": stored,
            "skipped": skipped, "feed_total": total or 0}


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
