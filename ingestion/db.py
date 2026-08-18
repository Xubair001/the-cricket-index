import os
import sqlite3

from shared import DB_PATH

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    # WAL so the backend can keep serving reads while an archive is ingesting.
    # Under the default rollback journal the API blocks for the whole write.
    # It's a persistent property of the file, so this is a no-op after the
    # first time -- set here as well as in the backend because whichever
    # process opens the database first should establish it.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


# Columns added to `players` after the initial schema shipped. schema.sql uses
# CREATE TABLE IF NOT EXISTS, so an existing cricket.db never picks up new
# columns from it -- these are applied separately. ALTER TABLE ADD COLUMN is
# the one schema change SQLite does cheaply and without a table rewrite, so
# enrichment doesn't force a full re-ingest of ~9,600 matches.
_MATCH_COLUMN_MIGRATIONS = {
    "source": "TEXT NOT NULL DEFAULT 'cricsheet'",
    "natural_key": "TEXT",
}

# Columns added to `news_images` after the news schema first shipped. Same
# reason as the two dicts around it: schema.sql uses CREATE TABLE IF NOT
# EXISTS, so an existing cricket.db never picks up a new column from it.
_NEWS_IMAGE_COLUMN_MIGRATIONS = {
    "thumb_url": "TEXT",
}

_PLAYER_COLUMN_MIGRATIONS = {
    "date_of_death": "TEXT",
    "retirement_date": "TEXT",
    "display_name": "TEXT",
    "image_url": "TEXT",
}


# Indexes replaced by a composite that covers the same lookups as a prefix.
# Keeping both would cost every write twice for no read benefit -- and
# ingestion writes ~221k player_match_stats rows.
_SUPERSEDED_INDEXES = {
    "idx_player_match_stats_identifier": "idx_player_match_stats_identifier_match",
    "idx_player_match_stats_team": "idx_player_match_stats_team_player",
    "idx_fixtures_upcoming": "idx_fixtures_gender_window",
}

# Indexes that measured *worse* than no index. matches.gender is not selective
# enough to be worth indexing (73% of rows match), and its presence pushed the
# planner into a slower join order for the main aggregate -- 772ms with, 294ms
# without. Dropped unconditionally so an older database converges on the same
# shape as a fresh one.
_HARMFUL_INDEXES = (
    "idx_matches_gender",
    "idx_matches_gender_date",
    "idx_matches_gender_season",
)


def _drop_superseded_indexes(conn: sqlite3.Connection) -> None:
    present = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    for old, replacement in _SUPERSEDED_INDEXES.items():
        # Only drop once the replacement actually exists, so a partially
        # applied schema never leaves the table with neither.
        if old in present and replacement in present:
            conn.execute(f"DROP INDEX IF EXISTS {old}")
    for harmful in _HARMFUL_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {harmful}")


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    for column, coltype in _PLAYER_COLUMN_MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE players ADD COLUMN {column} {coltype}")

    existing = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    for column, coltype in _MATCH_COLUMN_MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {column} {coltype}")
    # news_images only exists once schema.sql has run, which init_db does
    # first, so this is safe on a fresh database as well as an upgraded one.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(news_images)")}
    if existing:
        for column, coltype in _NEWS_IMAGE_COLUMN_MIGRATIONS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE news_images ADD COLUMN {column} {coltype}")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_matches_natural_key ON matches(natural_key)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_source ON matches(source)")


def init_db() -> None:
    with get_connection() as conn:
        with open(_SCHEMA_PATH) as f:
            conn.executescript(f.read())
        _migrate(conn)
        _drop_superseded_indexes(conn)
        conn.commit()
        # Refresh planner statistics. Without sqlite_stat1 SQLite guesses at
        # selectivity and can pick the wrong index once a table grows past the
        # shape it assumed.
        conn.execute("ANALYZE")
        conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
