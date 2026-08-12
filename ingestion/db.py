import os
import sqlite3

from shared import DB_PATH

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        with open(_SCHEMA_PATH) as f:
            conn.executescript(f.read())


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
