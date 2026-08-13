import os
import sqlite3

from shared import DB_PATH

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


# Columns added to `players` after the initial schema shipped. schema.sql uses
# CREATE TABLE IF NOT EXISTS, so an existing cricket.db never picks up new
# columns from it -- these are applied separately. ALTER TABLE ADD COLUMN is
# the one schema change SQLite does cheaply and without a table rewrite, so
# enrichment doesn't force a full re-ingest of ~9,600 matches.
_PLAYER_COLUMN_MIGRATIONS = {
    "date_of_death": "TEXT",
    "retirement_date": "TEXT",
    "display_name": "TEXT",
    "image_url": "TEXT",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    for column, coltype in _PLAYER_COLUMN_MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE players ADD COLUMN {column} {coltype}")


def init_db() -> None:
    with get_connection() as conn:
        with open(_SCHEMA_PATH) as f:
            conn.executescript(f.read())
        _migrate(conn)
        conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
