import os
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# backend/app/ -> backend/ -> project root, where cricket.db lives (shared
# with the ingestion pipeline). Resolved from this file's location so it
# works regardless of the process's current working directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "cricket.db")

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Per-connection settings the API needs to coexist with the ingester.

    Both processes hold the same file open, so these are not tuning knobs --
    they're what stops one from breaking the other:

    * WAL lets readers and the writer run concurrently. Under the default
      rollback journal a single ingestion write blocks every read, and the API
      returns "database is locked" for the duration of an archive ingest.
    * busy_timeout makes a reader that does hit a lock wait for it rather than
      failing instantly.
    * foreign_keys is per-connection in SQLite and OFF by default, so the FKs
      declared in schema.sql are otherwise unenforced on this side.

    synchronous=NORMAL is the one genuine trade: under WAL it risks losing the
    last transactions on an OS crash, which is acceptable for a read replica of
    data that is re-derivable from Cricsheet.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
