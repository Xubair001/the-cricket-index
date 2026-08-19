import asyncio
import csv
import hashlib
import json
import logging
import os
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from email.utils import formatdate

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
from icc_scorecard import (
    build_register_index,
    natural_key,
    parse_scorecard,
    resolve_register_player,
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


# Ceiling on a single match's uncompressed JSON. See the note in `ingest_match`.
MAX_MATCH_JSON_BYTES = 16 * 1024 * 1024

@activity.defn
async def download_archive(competition: str) -> DownloadResult:
    """Fetches the competition's zip archive, refreshing it when Cricsheet has
    republished.

    Deliberately does NOT extract it: match files are read directly out of
    the zip on demand (see ingest_match), so disk usage stays bounded to the
    compressed archive itself (tens of MB) instead of the full extracted
    JSON tree (hundreds of MB).
    """
    if competition not in CRICSHEET_URLS:
        raise ApplicationError(f"unknown competition '{competition}'", non_retryable=True)

    os.makedirs(DATA_DIR, exist_ok=True)
    archive_path = os.path.join(DATA_DIR, f"{competition}.zip")

    # Conditional refresh, not cache-forever. The previous rule was "download
    # only if the file is absent", which made a scheduled re-run incapable of
    # ever seeing a new match: the stale zip was re-read and every match in it
    # hash-matched, so the job reported success having ingested nothing.
    #
    # Cricsheet serves Last-Modified and honours If-Modified-Since, so asking
    # costs one 304 and no body when nothing has been published. Note the
    # publishing cadence is Cricsheet's, not ours -- the archives update in
    # bulk every few days, so a daily run mostly 304s and that is the point.
    url = CRICSHEET_URLS[competition]
    headers = {}
    if os.path.exists(archive_path):
        headers["If-Modified-Since"] = formatdate(
            os.path.getmtime(archive_path), usegmt=True
        )

    async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 304:
            activity.logger.info(
                f"{competition}: archive unchanged since last fetch (304), using cache"
            )
        elif resp.status_code == 200:
            with open(archive_path, "wb") as f:
                f.write(resp.content)
            activity.logger.info(
                f"{competition}: downloaded {len(resp.content) / 1_048_576:.1f} MB "
                f"(published {resp.headers.get('last-modified', 'unknown')})"
            )
        elif os.path.exists(archive_path):
            # A transient upstream failure must not take out a scheduled run
            # when a perfectly usable archive is already on disk.
            activity.logger.warning(
                f"{competition}: HTTP {resp.status_code} fetching archive; using cached copy"
            )
        else:
            resp.raise_for_status()

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
            # Check the declared uncompressed size BEFORE reading. `z.read`
            # decompresses into memory with no bound, so a crafted entry that
            # expands from a few kB to gigabytes takes the worker down with an
            # OOM rather than an error. The archive comes from cricsheet.org over
            # HTTPS, so this is defence in depth rather than a live threat - but
            # the check is one comparison and the failure mode it prevents is a
            # process kill, not a bad response.
            #
            # The bound is ~18x the largest real match (a Test at 892 kB; ODIs
            # top out near 217 kB), so it cannot reject genuine data.
            info = z.getinfo(f"{input.match_id}.json")
            if info.file_size > MAX_MATCH_JSON_BYTES:
                raise ApplicationError(
                    f"{input.match_id}.json declares {info.file_size} bytes, "
                    f"over the {MAX_MATCH_JSON_BYTES} limit; refusing to decompress",
                    non_retryable=True,
                )
            raw_bytes = z.read(info)
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
        eliminator_team_id = team_ids.get(match.eliminator) if match.eliminator else None

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
                match_number, event_stage, event_group, venue, city,
                match_date_start, match_date_end,
                overs_limit, team1_id, team2_id, toss_winner_team_id,
                toss_decision, winner_team_id, eliminator_team_id,
                win_by_runs, win_by_wickets,
                outcome_result, player_of_match, source, natural_key
            ) VALUES (?, ?, ?, ?, 'full', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'cricsheet', ?)
            ON CONFLICT(match_id) DO UPDATE SET
                competition_id=excluded.competition_id, season_id=excluded.season_id,
                gender=excluded.gender, content_hash=excluded.content_hash,
                match_type=excluded.match_type, team_type=excluded.team_type,
                season_label=excluded.season_label, event_name=excluded.event_name,
                match_number=excluded.match_number, event_stage=excluded.event_stage,
                event_group=excluded.event_group,
                venue=excluded.venue, city=excluded.city,
                match_date_start=excluded.match_date_start,
                match_date_end=excluded.match_date_end,
                overs_limit=excluded.overs_limit, team1_id=excluded.team1_id,
                team2_id=excluded.team2_id, toss_winner_team_id=excluded.toss_winner_team_id,
                toss_decision=excluded.toss_decision, winner_team_id=excluded.winner_team_id,
                eliminator_team_id=excluded.eliminator_team_id,
                win_by_runs=excluded.win_by_runs, win_by_wickets=excluded.win_by_wickets,
                outcome_result=excluded.outcome_result, player_of_match=excluded.player_of_match,
                source='cricsheet', natural_key=excluded.natural_key
            """,
            (
                match.match_id, competition_id, season_id, match.gender, content_hash,
                match.match_type, match.team_type, match.season, match.event_name,
                match.match_number, match.event_stage, match.event_group,
                match.venue, match.city, match.match_date_start,
                match.match_date_end, match.overs_limit, team1_id, team2_id,
                toss_winner_team_id, match.toss_decision, winner_team_id,
                eliminator_team_id,
                match.win_by_runs, match.win_by_wickets, match.outcome_result,
                match.player_of_match,
                natural_key(match.gender, input.competition, match.match_date_start,
                            match.team1, match.team2),
            ),
        )

        # Cricsheet is authoritative. If an ICC stand-in described this same
        # real-world match, drop it now rather than counting both.
        superseded = conn.execute(
            """SELECT match_id FROM matches
               WHERE natural_key = ? AND source = 'icc' AND match_id <> ?""",
            (natural_key(match.gender, input.competition, match.match_date_start,
                         match.team1, match.team2), input.match_id),
        ).fetchall()
        for (old_id,) in superseded:
            conn.execute("DELETE FROM player_match_stats WHERE match_id = ?", (old_id,))
            conn.execute("DELETE FROM deliveries WHERE match_id = ?", (old_id,))
            conn.execute("DELETE FROM matches WHERE match_id = ?", (old_id,))
            activity.logger.info(
                f"{input.match_id}: superseded ICC stand-in {old_id}"
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

        # Deliveries. Replaced wholesale for the match rather than upserted:
        # the primary key is positional (innings, seq), so a re-parse that
        # changes the ball count would otherwise leave orphaned tail rows from
        # the previous version behind.
        conn.execute("DELETE FROM deliveries WHERE match_id = ?", (match.match_id,))
        conn.executemany(
            """INSERT INTO deliveries (
                match_id, innings, seq, over, ball, batting_team_id,
                batter, bowler, non_striker,
                runs_batter, runs_extras, runs_total, non_boundary,
                wides, noballs, byes, legbyes, wicket_kind, player_out, fielder
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    match.match_id, d.innings, d.seq, d.over, d.ball,
                    team_ids.get(d.batting_team),
                    # Names resolve to identifiers through the match's own
                    # registry, the same mapping player_match_stats uses -- so a
                    # delivery and an aggregate always name the same person.
                    match.players.get(d.batter),
                    match.players.get(d.bowler),
                    match.players.get(d.non_striker),
                    d.runs_batter, d.runs_extras, d.runs_total, int(d.non_boundary),
                    d.wides, d.noballs, d.byes, d.legbyes,
                    d.wicket_kind, match.players.get(d.player_out),
                    match.players.get(d.fielder),
                )
                for d in match.deliveries
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


# Longest Retry-After this will sit through inside one activity. See _wikidata_get.
MAX_RETRY_AFTER = 60.0


async def _wikidata_get(client, query: str, batch_index: int, attempts: int = 4):
    """GETs one SPARQL batch, backing off on throttling.

    Wikidata's public endpoint burst-throttles with 429, sometimes with a
    Retry-After and sometimes without, so the wait is exponential (2s, 4s, 8s)
    unless the header asks for longer.

    The header is honoured only up to MAX_RETRY_AFTER. Wikidata answers a
    sustained run with `Retry-After: 1000`, and sleeping that off inside the
    activity would spend 16 minutes per batch against a one-hour
    start_to_close_timeout -- the activity would die around batch 3 of 48 having
    written almost nothing. Past the cap the batch is given up on instead, which
    surfaces as a failed batch and lets Temporal retry the activity later, when
    the throttle window has passed. Waiting is the right response to a 429; the
    question is only who does the waiting, and Temporal is better at it than a
    blocked coroutine.

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
            if wait > MAX_RETRY_AFTER:
                activity.logger.warning(
                    f"wikidata batch {batch_index}: HTTP {resp.status_code} asks for "
                    f"{wait:.0f}s, above the {MAX_RETRY_AFTER:.0f}s cap; giving the batch "
                    f"up so Temporal can retry the activity after the throttle clears"
                )
                return None
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

    # Resume point from a previous attempt. Without this a worker restart at
    # batch 40 of 48 would re-query all forty, and every one of them is a
    # throttled round trip against a shared public endpoint.
    resume_from = 0
    try:
        details = activity.info().heartbeat_details
        if details:
            resume_from = int(details[0])
    except Exception:  # noqa: BLE001 - a missing/odd heartbeat just means start over
        resume_from = 0
    if resume_from:
        activity.logger.info(f"wikidata enrichment resuming at batch {resume_from}")

    async with httpx.AsyncClient(follow_redirects=True, timeout=180, headers=headers) as client:
        for start in range(0, len(pending), batch_size):
            batch_index = start // batch_size
            if batch_index < resume_from:
                continue
            # Heartbeat carries the batch index, so it does double duty: it tells
            # Temporal the worker is alive (without it a worker that dies mid-run
            # is only noticed when start_to_close_timeout expires, an hour later),
            # and it is the resume point for the next attempt.
            activity.heartbeat(batch_index)
            chunk = pending[start : start + batch_size]
            resp = await _wikidata_get(client, wikidata_query(chunk), batch_index)
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


ICC_SCORECARD_ENDPOINT = "https://assets-icc.sportz.io/cricket/v1/game/scorecard"

# ICC's match_type -> our competition key. Only the formats this schema models;
# the feed also carries "List A", "ODI Youth" and warm-ups, which are skipped
# rather than shoehorned into a competition that would misrepresent them.
ICC_MATCH_TYPE_TO_COMPETITION = {"Test": "tests", "ODI": "odis", "T20": "t20is"}

_REGISTER_PATH = os.path.join(DATA_DIR, "people.csv")


async def _cached_register(client) -> dict:
    """Cricsheet's people register, cached on disk with a conditional GET.

    Fetched once per run rather than per match: it is 1.1 MB and every
    scorecard needs the whole index.
    """
    headers = {}
    if os.path.exists(_REGISTER_PATH):
        headers["If-Modified-Since"] = formatdate(os.path.getmtime(_REGISTER_PATH), usegmt=True)
    resp = await client.get(CRICSHEET_PEOPLE_REGISTER, headers=headers)
    if resp.status_code == 200:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_REGISTER_PATH, "w", encoding="utf-8") as f:
            f.write(resp.text)
    elif resp.status_code != 304 and not os.path.exists(_REGISTER_PATH):
        resp.raise_for_status()
    with open(_REGISTER_PATH, encoding="utf-8") as f:
        return build_register_index(list(csv.DictReader(f)))


# Keys whose value changes on every request and says nothing about the match.
# Hashing the raw payload made the hash unique per fetch, so every run rewrote
# all 113 matches and "unchanged" was never once reported.
_ICC_VOLATILE_KEYS = {"Timestamp", "Venue_Weather", "SerialNumber"}


def _icc_scorecard_hash(payload: dict) -> str:
    """Stable content hash of a scorecard, ignoring per-request noise."""
    data = dict((payload or {}).get("data") or {})
    for key in _ICC_VOLATILE_KEYS:
        data.pop(key, None)
    detail = data.get("Matchdetail")
    if isinstance(detail, dict):
        detail = {k: v for k, v in detail.items() if k not in _ICC_VOLATILE_KEYS}
        venue = detail.get("Venue")
        if isinstance(venue, dict):
            detail["Venue"] = {k: v for k, v in venue.items() if k not in _ICC_VOLATILE_KEYS}
        data["Matchdetail"] = detail
    return hashlib.sha256(
        b"icc-v1\n" + json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()


@activity.defn
async def find_icc_scorecard_candidates(since: str, limit: int = 200) -> list[str]:
    """Completed fixtures, in a modelled format, that we hold no match for.

    Driven off `fixtures` rather than re-querying the schedule feed: that table
    is already synced daily and already carries the gender and format we need
    to decide whether a match is even in scope.

    The natural_key join is what stops this re-fetching a match Cricsheet has
    since published -- without it every run would pull scorecards we already
    have a better version of.
    """
    in_scope = ", ".join(f"'{t}'" for t in ICC_MATCH_TYPE_TO_COMPETITION)
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT f.icc_match_id
                 FROM fixtures f
                WHERE f.match_result IS NOT NULL
                  AND f.is_upcoming = 0
                  AND f.gender IS NOT NULL
                  AND f.match_type IN ({in_scope})
                  AND f.start_date >= ?
                  AND f.start_date <= date('now')
                  AND NOT EXISTS (
                        SELECT 1 FROM matches m
                         WHERE m.source = 'cricsheet'
                           AND m.natural_key = f.gender || '|' ||
                               CASE f.match_type WHEN 'Test' THEN 'tests'
                                                 WHEN 'ODI'  THEN 'odis'
                                                 ELSE 't20is' END
                               || '|' || f.start_date || '|' ||
                               CASE WHEN f.team_a_name < f.team_b_name
                                    THEN f.team_a_name || '|' || f.team_b_name
                                    ELSE f.team_b_name || '|' || f.team_a_name END)
                ORDER BY f.start_date DESC
                LIMIT ?""",
            (since, limit),
        ).fetchall()
    ids = [r[0] for r in rows]
    activity.logger.info(f"icc scorecard candidates since {since}: {len(ids)}")
    return ids


@activity.defn
async def ingest_icc_scorecards(icc_match_ids: list[str]) -> dict:
    """Ingests ICC scorecards for the given fixtures.

    These are ICC's computed figures, stored with source='icc' so they are never
    mistaken for the Cricsheet-derived ones, and keyed by `natural_key` so a
    later Cricsheet publication of the same match supersedes rather than
    duplicates it.

    Player identity comes from Cricsheet's people register, NOT from ICC's own
    player ids -- see icc_scorecard.build_register_index for why that choice is
    what makes the two sources merge cleanly.
    """
    stats = {"seen": 0, "stored": 0, "skipped_unchanged": 0, "skipped_incomplete": 0,
             "skipped_cricsheet_has_it": 0, "skipped_format": 0, "failed": 0,
             "players_linked": 0, "players_unlinked": 0, "players_created": 0}

    async with httpx.AsyncClient(follow_redirects=True, timeout=90) as client:
        register = await _cached_register(client)

        for index, icc_id in enumerate(icc_match_ids):
            # One heartbeat per match: the batch can be 200 scorecards, and a
            # worker restart part-way through should be noticed in seconds.
            activity.heartbeat(index)
            stats["seen"] += 1
            try:
                resp = await client.get(
                    ICC_SCORECARD_ENDPOINT,
                    params={"client_id": ICC_CLIENT_ID, "feed_format": "json",
                            "game_id": icc_id, "lang": "en"},
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as e:  # noqa: BLE001 - one bad match must not sink the batch
                activity.logger.warning(f"icc scorecard {icc_id}: fetch failed {e!r}")
                stats["failed"] += 1
                continue

            with get_connection() as conn:
                row = conn.execute(
                    """SELECT gender, match_type, winning_team_name, match_result
                         FROM fixtures WHERE icc_match_id = ?""",
                    (icc_id,),
                ).fetchone()
            gender_hint = row[0] if row else None
            # The scorecard states the result in prose; the fixtures row already
            # names the winning side, so use that rather than parsing English.
            winner_name = row[2] if row else None
            result_text = row[3] if row else None

            match = parse_scorecard(icc_id, payload, gender_hint=gender_hint)
            if match is None or not match.is_complete:
                stats["skipped_incomplete"] += 1
                continue

            competition = ICC_MATCH_TYPE_TO_COMPETITION.get(match.match_type or "")
            if not competition or match.gender not in ("male", "female"):
                stats["skipped_format"] += 1
                continue

            nkey = natural_key(match.gender, competition, match.match_date,
                               match.team_a_name, match.team_b_name)
            content_hash = _icc_scorecard_hash(payload)
            match_id = f"icc-{icc_id}"

            with get_connection() as conn:
                # Cricsheet is authoritative: if it already describes this
                # match, the ICC stand-in must not exist alongside it.
                if conn.execute(
                    "SELECT 1 FROM matches WHERE natural_key = ? AND source = 'cricsheet'", (nkey,)
                ).fetchone():
                    conn.execute("DELETE FROM player_match_stats WHERE match_id = ?", (match_id,))
                    conn.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))
                    conn.commit()
                    stats["skipped_cricsheet_has_it"] += 1
                    continue

                existing = conn.execute(
                    "SELECT content_hash FROM matches WHERE match_id = ?", (match_id,)
                ).fetchone()
                if existing and existing[0] == content_hash:
                    stats["skipped_unchanged"] += 1
                    continue

                display_name, comp_type = COMPETITION_META[competition]
                competition_id = _get_or_create_competition(
                    conn, competition, match.gender, display_name, comp_type
                )
                team_type = TEAM_TYPE_BY_COMPETITION_TYPE[comp_type]
                team_ids = {
                    icc_tid: _get_or_create_team(conn, name, match.gender, team_type)
                    for icc_tid, name in (
                        (match.team_a_icc_id, match.team_a_name),
                        (match.team_b_icc_id, match.team_b_name),
                    )
                    if icc_tid and name
                }

                rows = []
                for p in match.players:
                    identifier = resolve_register_player(register, p.name_full)
                    if identifier:
                        stats["players_linked"] += 1
                        meta = register["meta"].get(identifier, {})
                        # Seed the player if this is the first time we have seen
                        # them. Cricsheet's own name is used so they read the
                        # same as everyone else, and cricinfo_id lets the
                        # Wikidata pass pick up their bio and photo.
                        before = conn.total_changes
                        conn.execute(
                            """INSERT INTO players (identifier, name, gender, cricinfo_id)
                               VALUES (?, ?, ?, ?)
                               ON CONFLICT(identifier) DO UPDATE SET
                                 cricinfo_id = COALESCE(players.cricinfo_id, excluded.cricinfo_id)""",
                            (identifier, meta.get("name") or p.name_full, match.gender,
                             meta.get("cricinfo_id")),
                        )
                        if conn.total_changes > before:
                            stats["players_created"] += 1
                    else:
                        stats["players_unlinked"] += 1
                    rows.append((match_id, identifier, p.name_full,
                                 team_ids.get(p.team_icc_id), p.runs_scored, p.balls_faced,
                                 p.fours, p.sixes, p.dismissals, p.wickets_taken,
                                 p.balls_bowled, p.runs_conceded))

                conn.execute(
                    """INSERT INTO matches (
                         match_id, competition_id, gender, data_granularity, content_hash,
                         match_type, team_type, season_label, event_name, venue, city,
                         match_date_start, match_date_end, team1_id, team2_id,
                         outcome_result, winner_team_id, source, natural_key
                       ) VALUES (?, ?, ?, 'full', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'icc', ?)
                       ON CONFLICT(match_id) DO UPDATE SET
                         content_hash=excluded.content_hash, venue=excluded.venue,
                         city=excluded.city, event_name=excluded.event_name,
                         outcome_result=excluded.outcome_result,
                         winner_team_id=excluded.winner_team_id,
                         natural_key=excluded.natural_key""",
                    (match_id, competition_id, match.gender, content_hash, match.match_type,
                     team_type, (match.match_date or "")[:4] or None, match.series_name,
                     match.venue, match.city, match.match_date, match.match_date,
                     team_ids.get(match.team_a_icc_id), team_ids.get(match.team_b_icc_id),
                     result_text or match.result_text,
                     next((tid for icc_tid, tid in team_ids.items()
                           if winner_name and (
                               (icc_tid == match.team_a_icc_id and match.team_a_name == winner_name)
                               or (icc_tid == match.team_b_icc_id and match.team_b_name == winner_name))),
                          None),
                     nkey),
                )
                # Positional replace, same rule as the Cricsheet path: the squad
                # can change between fetches, so upserting alone would strand rows.
                conn.execute("DELETE FROM player_match_stats WHERE match_id = ?", (match_id,))
                conn.executemany(
                    """INSERT INTO player_match_stats (
                         match_id, player_identifier, player_name, team_id, runs_scored,
                         balls_faced, fours, sixes, dismissals, wickets_taken,
                         balls_bowled, runs_conceded
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [r for r in rows if r[3] is not None],
                )
                conn.commit()
                stats["stored"] += 1

    activity.logger.info(f"icc scorecards: {stats}")
    return stats


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


@activity.defn
async def sync_fixture_squads(window_days: int = 120, include_completed: bool = False) -> dict:
    """Announced squads for upcoming fixtures, from the ICC scorecard feed.

    This is what makes availability answerable. §5 lists "squad lists per
    fixture" as the core blocker and says fixtures "carry team names only, no
    player lists" -- true of the *schedule* endpoint, but the scorecard endpoint
    returns a full squad for a fixture that has not been played, along with each
    player's role, batting hand, bowling style and an availability status.

    Only upcoming fixtures inside the window are fetched: a squad for a match
    played last year is history, and the point of this table is who is picked
    for cricket that has not happened yet.

    Names are resolved through the same (surname, initial) index the ICC
    rankings use, with the squad's own team as the country tiebreak. An
    unresolved name is still stored -- the squad is real whether or not we can
    link it to a player we hold.
    """
    with get_connection() as conn:
        # Completed fixtures are worth fetching too, and not for their result:
        # the same payload carries each player's role, batting hand and bowling
        # style, and squads only exist for the handful of upcoming fixtures that
        # have been announced. Without them the sourced attributes cover 3.6% of
        # the register, which is a filter that silently excludes almost everyone.
        if include_completed:
            rows = conn.execute(
                """SELECT icc_match_id, gender FROM fixtures
                    WHERE start_date IS NOT NULL ORDER BY start_date DESC"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT icc_match_id, gender FROM fixtures
                    WHERE is_upcoming = 1 AND start_date IS NOT NULL
                      AND start_date <= date('now', ?)
                    ORDER BY start_date""",
                (f"+{window_days} days",),
            ).fetchall()

        players = conn.execute(
            "SELECT identifier, name, gender FROM players"
        ).fetchall()
        index = build_name_index([(r[0], r[1], r[2]) for r in players])
        country_lookup: dict[str, set[str]] = {}
        for ident, team_name in conn.execute(
            """SELECT DISTINCT pms.player_identifier, t.name
                 FROM player_match_stats pms
                 JOIN teams t ON t.team_id = pms.team_id
                WHERE t.team_type = 'international'
                  AND pms.player_identifier IS NOT NULL"""
        ):
            country_lookup.setdefault(ident, set()).add(team_name)

    activity.logger.info(f"fixture squads: {len(rows)} upcoming fixtures in window")

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stored = matched = 0
    empty = 0

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        for icc_id, gender in rows:
            try:
                resp = await client.get(
                    ICC_SCORECARD_ENDPOINT,
                    params={"client_id": ICC_CLIENT_ID, "feed_format": "json",
                            "game_id": icc_id, "lang": "en"},
                )
                resp.raise_for_status()
                teams = ((resp.json() or {}).get("data") or {}).get("Teams") or {}
            except Exception as e:  # noqa: BLE001 - one bad fixture must not sink the run
                activity.logger.warning(f"squad {icc_id}: {e}")
                continue

            batch = []
            for team_id, team in teams.items():
                squad = (team or {}).get("Players") or {}
                team_name = (team or {}).get("Name_Full")
                for p in squad.values():
                    name = p.get("Name_Full")
                    if not name:
                        continue
                    identifier = resolve_player(
                        index, name, gender or "male", country_lookup, team_name
                    )
                    if identifier:
                        matched += 1
                    batting = p.get("Batting") or {}
                    bowling = p.get("Bowling") or {}
                    batch.append((
                        icc_id, str(team_id), team_name, name, identifier,
                        int(p.get("Position") or 0) or None,
                        1 if p.get("Iscaptain") else 0,
                        p.get("Role"), batting.get("Style") or None,
                        bowling.get("Style") or None, p.get("status"),
                        fetched_at,
                    ))
            if not batch:
                empty += 1
                continue

            with get_connection() as conn:
                # Replaced per fixture: a squad is re-announced, not appended to.
                conn.execute(
                    "DELETE FROM fixture_squads WHERE icc_match_id = ?", (icc_id,)
                )
                conn.executemany(
                    """INSERT INTO fixture_squads (
                        icc_match_id, icc_team_id, team_name, player_name,
                        player_identifier, position, is_captain, role,
                        batting_style, bowling_style, status, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    batch,
                )
                conn.commit()
            stored += len(batch)

    activity.logger.info(
        f"fixture squads: {stored} rows, {matched} linked to a player, "
        f"{empty} fixtures with no squad announced"
    )
    return {"fixtures": len(rows), "rows": stored, "matched": matched, "no_squad": empty}


# --------------------------------------------------------------------------
# Daily tournament integrity
# --------------------------------------------------------------------------
#
# Tournament data itself needs no separate job: `event_name`, `event_stage` and
# `eliminator_team_id` are written by `ingest_match`, so the Cricsheet leg of
# the daily sync already refreshes them. What the daily sync does NOT do is
# keep the tournaments correct, and two things can silently break them.

# How recently a multi-team event's first match must fall for it to count as
# newly appeared. 45 days comfortably covers a tournament that started between
# two daily runs while not re-reporting one that has been running for months.
NEW_EVENT_WINDOW_DAYS = 45

# Below this an "event" is a bilateral tour, not a tournament. Matches
# `tournaments.MIN_SIDES` on the read side; kept as its own constant because
# ingestion must not import from backend.
TOURNAMENT_MIN_SIDES = 3


@activity.defn
async def audit_tournaments() -> dict:
    """Flag newly-appeared tournament names, and repair cross-source duplicates.

    Two failure modes, both of which have already happened here:

    **A new spelling splits a tournament, silently.** Cricsheet renames events
    between editions - the men's 50-over World Cup has appeared under three
    names and the women's T20 World Cup under four. An unaliased spelling does
    not error; it quietly becomes a separate one-edition tournament, and the
    real one loses those matches. That is not hypothetical: "Women's World T20"
    hid the 2014 and 2016 editions, 46 matches, until it was found by hand.
    Aliases are curated in `backend/app/events.py` and cannot be applied from
    here, so this reports rather than fixes - which is the right split anyway,
    since deciding two names are one tournament is a judgement.

    **A match gets stored twice.** The ICC scorecard leg runs daily and writes
    stand-ins for matches Cricsheet has not published. When Cricsheet publishes
    one later, `ingest_match` drops the stand-in - but only if that match is
    parsed, and only if the natural keys agree. This re-runs the check over
    everything and removes what is left, so duplicates cannot accumulate
    between the daily runs that would otherwise catch them.
    """
    with get_connection() as conn:
        cutoff = (
            datetime.now(timezone.utc).date() - timedelta(days=NEW_EVENT_WINDOW_DAYS)
        ).isoformat()

        # A multi-team event whose EARLIEST match is inside the window is
        # either a genuinely new tournament or an existing one under a new
        # name. Both want a human eye; neither is an error.
        # Sides are counted from the UNION of both columns, in Python. The
        # obvious SQL - COUNT(DISTINCT team1_id) + COUNT(DISTINCT team2_id) -
        # is wrong, and wrong in the direction that matters: a two-team tour
        # whose sides swap home and away between matches has two distinct
        # values in each column and scores 4, so every such tour would be
        # reported as a new tournament and bury the renames this exists to
        # surface. It flagged "Canada Women tour of Argentina" as a 4-side
        # event before this was caught.
        per_event: dict[tuple, dict] = {}
        for name, gender, key, team1, team2, date in conn.execute(
            """SELECT m.event_name, m.gender, c.key, m.team1_id, m.team2_id,
                      m.match_date_start
               FROM matches m
               JOIN competitions c ON c.competition_id = m.competition_id
               WHERE m.event_name IS NOT NULL"""
        ):
            bucket = per_event.setdefault(
                (name, gender, key), {"matches": 0, "sides": set(), "first": None}
            )
            bucket["matches"] += 1
            bucket["sides"].update(t for t in (team1, team2) if t)
            if date and (bucket["first"] is None or date < bucket["first"]):
                bucket["first"] = date

        new_events = sorted(
            (
                {"event": name, "gender": gender, "competition": key,
                 "matches": v["matches"], "sides": len(v["sides"]),
                 "first": v["first"]}
                for (name, gender, key), v in per_event.items()
                if len(v["sides"]) >= TOURNAMENT_MIN_SIDES
                and v["first"] is not None
                and v["first"] >= cutoff
            ),
            key=lambda e: -e["matches"],
        )

        # Recompute every key with the CURRENT rule rather than reading the
        # stored column, which is exactly the value that is wrong on an
        # affected row - and WRITE IT BACK where it differs.
        #
        # The write-back is what stops this job churning. `ingest_icc_scorecards`
        # decides whether Cricsheet already has a match by comparing its own
        # freshly-computed key against the STORED key on Cricsheet rows. Those
        # stored keys were computed at insert time, so after `natural_key`
        # changed they no longer matched, the ICC leg stored 22 stand-ins it
        # should have skipped, this audit deleted them, and the whole cycle
        # repeated the next day. Re-deriving the stored key fixes the check
        # itself rather than cleaning up after it.
        buckets: dict[str, list[tuple[str, str]]] = {}
        restated = 0
        for match_id, source, gender, date, competition, team_a, team_b, stored in conn.execute(
            """SELECT m.match_id, m.source, m.gender, m.match_date_start, c.key,
                      t1.name, t2.name, m.natural_key
               FROM matches m
               JOIN competitions c ON c.competition_id = m.competition_id
               LEFT JOIN teams t1 ON t1.team_id = m.team1_id
               LEFT JOIN teams t2 ON t2.team_id = m.team2_id
               WHERE m.match_date_start IS NOT NULL"""
        ):
            key = natural_key(gender, competition, date, team_a, team_b)
            if key != stored:
                conn.execute(
                    "UPDATE matches SET natural_key = ? WHERE match_id = ?",
                    (key, match_id),
                )
                restated += 1
            buckets.setdefault(key, []).append((match_id, source))

        superseded = [
            match_id
            for rows in buckets.values()
            if len(rows) > 1 and {s for _, s in rows} == {"cricsheet", "icc"}
            for match_id, source in rows
            if source == "icc"
        ]
        for match_id in superseded:
            conn.execute("DELETE FROM deliveries WHERE match_id = ?", (match_id,))
            conn.execute("DELETE FROM player_match_stats WHERE match_id = ?", (match_id,))
            conn.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))
        conn.commit()

    if new_events:
        activity.logger.warning(
            "new multi-team event names since %s - check whether any is an "
            "existing tournament renamed, and add an alias to "
            "backend/app/events.py if so: %s",
            cutoff,
            ", ".join(f"{e['event']} ({e['matches']}m)" for e in new_events),
        )
    if superseded:
        activity.logger.info(
            f"removed {len(superseded)} ICC matches superseded by a Cricsheet record"
        )

    if restated:
        activity.logger.info(
            f"re-derived natural_key on {restated} matches so the ICC leg's "
            f"'Cricsheet already has this' check matches again"
        )

    return {
        "new_events": new_events,
        "duplicates_removed": len(superseded),
        "keys_restated": restated,
        "window_days": NEW_EVENT_WINDOW_DAYS,
    }
