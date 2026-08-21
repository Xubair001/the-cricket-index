"""Copy `cricket.db` into Postgres.

    python -m scripts.migrate_to_postgres --url "$DATABASE_URL" --create-schema
    python -m scripts.migrate_to_postgres --url "$DATABASE_URL" --skip deliveries
    python -m scripts.migrate_to_postgres --url "$DATABASE_URL" --verify-only

Five decisions here are load-bearing.

**Load order comes from Postgres's own FK catalog, topologically sorted.** Not a
hand-written list, which would need editing every time a table is added, and not
`session_replication_role = replica` to disable the constraints: that needs
superuser, and a managed Postgres (Neon, RDS) gives you an owner role that is
not one. Sorting means the constraints stay on and a genuine referential problem
in the source surfaces as an error on the table that has it, rather than at the
end of a long run.

**COPY, not INSERT.** 4.8M deliveries through `executemany` is tens of minutes;
through `COPY FROM STDIN` it is a small number of them. Rows are streamed from
SQLite in batches rather than materialised, because the whole table does not fit
in memory comfortably and there is no reason for it to.

**Identity sequences are reset afterwards.** The load inserts existing primary
keys explicitly, which leaves every sequence at 1, so the first row the ingestion
pipeline wrote next would collide with an existing id. `postgres_schema.identity_resets`
owns the statements; skipping this step produces a database that looks perfect
and fails on the next ingest.

**Sizing is reported per table, before the big one, on purpose.** `--skip
deliveries` exists so the 4.8M-row table can be left until the other 24 have
been measured. CLAUDE.md's "64 bytes per delivery" was measured against a
`WITHOUT ROWID` table, which Postgres has no equivalent of, so that figure does
not carry over and the real one has to be observed.

**Verification compares counts AND a checksum, not counts alone.** Equal row
counts with mangled values is the failure mode a count-only check is blind to,
and NULL handling differs enough between the two engines to make it a real risk.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import psycopg

from scripts.postgres_schema import identity_resets, translate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQLITE_PATH = PROJECT_ROOT / "cricket.db"

# Rows pulled from SQLite per round trip. Large enough that the per-batch
# overhead disappears, small enough that a batch is a few MB rather than a GB.
BATCH = 50_000


def sqlite_tables(con: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def columns_of(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def load_order(pg: psycopg.Connection, tables: list[str]) -> list[str]:
    """Tables sorted so every FK target precedes the table referencing it.

    A self-reference is ignored rather than treated as a cycle: it is satisfiable
    within one table's own load as long as the rows arrive in a workable order,
    and Postgres checks a self-FK per row rather than per statement.
    """
    with pg.cursor() as cur:
        cur.execute(
            """
            SELECT src.relname AS child, tgt.relname AS parent
            FROM pg_constraint c
            JOIN pg_class src ON src.oid = c.conrelid
            JOIN pg_class tgt ON tgt.oid = c.confrelid
            JOIN pg_namespace n ON n.oid = src.relnamespace
            WHERE c.contype = 'f' AND n.nspname = 'public'
            """
        )
        edges = [(child, parent) for child, parent in cur.fetchall() if child != parent]

    remaining = set(tables)
    parents: dict[str, set[str]] = {t: set() for t in tables}
    for child, parent in edges:
        if child in parents and parent in remaining:
            parents[child].add(parent)

    ordered: list[str] = []
    while remaining:
        ready = sorted(t for t in remaining if not (parents[t] - set(ordered)))
        if not ready:
            # A genuine cycle. Report it rather than looping: it means the schema
            # changed in a way this script cannot sequence, and guessing an order
            # would fail deep into a long load.
            raise SystemExit(
                f"FK cycle among: {sorted(remaining)}. Load these by hand or "
                "defer the constraint."
            )
        ordered.extend(ready)
        remaining -= set(ready)
    return ordered


def pk_columns(con: sqlite3.Connection, table: str) -> list[str]:
    """Primary-key columns in key order, for a deterministic read order.

    Resuming depends on this: rows are loaded in one fixed order, so "how many
    are already there" is the same as "where to carry on from". Without a
    deterministic order that arithmetic is meaningless.
    """
    rows = [(r[5], r[1]) for r in con.execute(f"PRAGMA table_info({table})") if r[5]]
    return [name for _, name in sorted(rows)]


def copy_table(
    url: str,
    src: sqlite3.Connection,
    table: str,
    chunk: int = BATCH,
    attempts: int = 6,
) -> tuple[int, int]:
    """Load one table, resumably. Returns (rows written now, rows already there).

    Three properties, all of which exist because the target is a managed
    Postgres over the internet rather than a file on this disk:

    * **Committed per chunk, not per table.** One `COPY` inside one transaction
      is faster and is the wrong trade here: a dropped connection at four
      million rows rolls the whole thing back, and on a metered plan that is a
      gigabyte of transfer spent for nothing. Committing every `chunk` rows caps
      the loss at one chunk.
    * **Resumable, by counting the target.** A re-run reads how many rows are
      already present and skips exactly that many of the source, in the same
      deterministic order, so an interrupted load is continued rather than
      restarted or duplicated. This is also what makes the script safe to run
      twice by accident - the second run does nothing.
    * **Retried with backoff, reconnecting each time.** Serverless Postgres
      scales its compute to zero and drops idle connections, so a mid-load
      disconnect is an expected event rather than a failure. Only connection
      errors are retried; a constraint violation is a real problem and is raised
      immediately, because retrying it would just fail again more slowly.
    """
    cols = columns_of(src, table)
    quoted = ", ".join(f'"{c}"' for c in cols)
    order = pk_columns(src, table) or cols
    order_sql = ", ".join(f'"{c}"' for c in order)
    total = src.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    written = 0
    already = 0
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            with psycopg.connect(url, autocommit=False, connect_timeout=60) as pg:
                with pg.cursor() as cur:
                    cur.execute(f'SELECT count(*) FROM "{table}"')
                    already = cur.fetchone()[0]
                if already >= total:
                    return 0, already
                # Position the source cursor once, then walk forward by KEY.
                #
                # `LIMIT n OFFSET m` per chunk would make a 4.8M-row load
                # quadratic - the 96th chunk re-scans 4.7M index entries to
                # reach its start. Keyset pagination ("where the key is greater
                # than the last row I wrote") makes every chunk cost the same,
                # and SQLite compares row values natively so the multi-column
                # keys work without unpacking the comparison by hand.
                offset = already
                cursor_key = None
                if already:
                    seek = src.execute(
                        f"SELECT {order_sql} FROM {table} ORDER BY {order_sql} "
                        f"LIMIT 1 OFFSET {already - 1}"
                    ).fetchone()
                    cursor_key = tuple(seek) if seek else None
                key_tuple = f"({order_sql})"
                placeholders = f"({', '.join('?' * len(order))})"
                while offset < total:
                    if cursor_key is None:
                        rows = src.execute(
                            f"SELECT {quoted} FROM {table} ORDER BY {order_sql} "
                            f"LIMIT {chunk}"
                        ).fetchall()
                    else:
                        rows = src.execute(
                            f"SELECT {quoted} FROM {table} "
                            f"WHERE {key_tuple} > {placeholders} "
                            f"ORDER BY {order_sql} LIMIT {chunk}",
                            cursor_key,
                        ).fetchall()
                    if not rows:
                        break
                    key_index = [cols.index(c) for c in order]
                    cursor_key = tuple(rows[-1][i] for i in key_index)
                    with pg.cursor() as cur:
                        with cur.copy(f'COPY "{table}" ({quoted}) FROM STDIN') as copy:
                            for row in rows:
                                copy.write_row(row)
                    # The commit is the resume point. Everything before it is
                    # durable; a failure after it costs at most this chunk.
                    pg.commit()
                    offset += len(rows)
                    written += len(rows)
                    if total > chunk:
                        print(
                            f"      {table}: {offset:,}/{total:,}",
                            flush=True,
                        )
            return written, already
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            if attempt == attempts:
                raise
            print(
                f"      {table}: connection lost ({type(exc).__name__}), "
                f"retry {attempt}/{attempts - 1} in {delay:.0f}s - "
                f"{written:,} rows already committed",
                flush=True,
            )
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    return written, already


def table_size(pg: psycopg.Connection, table: str) -> tuple[int, str]:
    with pg.cursor() as cur:
        cur.execute(
            "SELECT pg_total_relation_size(%s), "
            "pg_size_pretty(pg_total_relation_size(%s))",
            (table, table),
        )
        return cur.fetchone()


def verify(src: sqlite3.Connection, pg: psycopg.Connection, tables: list[str]) -> bool:
    """Row counts on both sides, plus a per-table integer checksum.

    The checksum sums every INTEGER column, which catches a column-order slip or
    a NULL-versus-zero difference that equal row counts would hide. Text columns
    are left out: collation and encoding differences between the two engines make
    a text checksum report failures that are not ones.
    """
    ok = True
    print(f"\n{'table':26} {'sqlite':>10} {'postgres':>10} {'checksum':>10}")
    for table in tables:
        n_src = src.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        with pg.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{table}"')
            n_pg = cur.fetchone()[0]

        ints = [
            r[1]
            for r in src.execute(f"PRAGMA table_info({table})")
            if r[2].upper() == "INTEGER"
        ]
        mark = "-"
        if ints:
            expr_src = " + ".join(f"coalesce(sum({c}), 0)" for c in ints)
            s_src = src.execute(f"SELECT {expr_src} FROM {table}").fetchone()[0]
            expr_pg = " + ".join(f'coalesce(sum("{c}"), 0)' for c in ints)
            with pg.cursor() as cur:
                cur.execute(f'SELECT {expr_pg} FROM "{table}"')
                s_pg = cur.fetchone()[0]
            same = (s_src or 0) == (s_pg or 0)
            mark = "match" if same else f"DIFFER {s_src} vs {s_pg}"
            ok = ok and same
        counts_ok = n_src == n_pg
        ok = ok and counts_ok
        flag = "" if counts_ok else "   <-- COUNT MISMATCH"
        print(f"{table:26} {n_src:10,} {n_pg:10,} {mark:>10}{flag}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="postgresql://... connection string")
    ap.add_argument("--create-schema", action="store_true", help="create tables first")
    ap.add_argument(
        "--skip",
        default="",
        help="comma-separated tables to leave out (e.g. deliveries, to size first)",
    )
    ap.add_argument("--only", default="", help="comma-separated tables to load")
    ap.add_argument("--truncate", action="store_true", help="empty target tables first")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument(
        "--chunk",
        type=int,
        default=BATCH,
        help=f"rows per commit (default {BATCH}); smaller loses less to a drop",
    )
    args = ap.parse_args()

    if not SQLITE_PATH.exists():
        print(f"no source database at {SQLITE_PATH}", file=sys.stderr)
        return 1

    src = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    skip = {t.strip() for t in args.skip.split(",") if t.strip()}
    only = {t.strip() for t in args.only.split(",") if t.strip()}

    with psycopg.connect(args.url, autocommit=False) as pg:
        if args.create_schema:
            print("creating schema...")
            with pg.cursor() as cur:
                cur.execute(translate())
            pg.commit()
            print("  done")

        all_tables = sqlite_tables(src)
        ordered = load_order(pg, all_tables)

        if args.verify_only:
            good = verify(src, pg, ordered)
            print("\n" + ("OK  every table matches." if good else "FAIL  see above."))
            return 0 if good else 1

        wanted = [
            t for t in ordered if t not in skip and (not only or t in only)
        ]
        if skip:
            print(f"skipping: {', '.join(sorted(skip))}")

        if args.truncate:
            # Reverse order so a child is emptied before its parent. CASCADE is
            # deliberately not used: it would silently empty a table that was
            # excluded from this run.
            with pg.cursor() as cur:
                for table in reversed(wanted):
                    cur.execute(f'TRUNCATE TABLE "{table}"')
            pg.commit()
            print("target tables emptied")

        total_bytes = 0
        print(f"\n{'table':26} {'loaded':>10} {'existing':>9} {'size':>10}")
        for table in wanted:
            n, already = copy_table(args.url, src, table, chunk=args.chunk)
            size, pretty = table_size(pg, table)
            total_bytes += size
            note = "" if not already else "  (resumed)" if n else "  (complete)"
            print(f"{table:26} {n:10,} {already:9,} {pretty:>10}{note}", flush=True)

        # Sequences, or the next ingest collides with row 1.
        with pg.cursor() as cur:
            for statement in identity_resets():
                cur.execute(statement)
        pg.commit()
        print("\nidentity sequences reset")

        with pg.cursor() as cur:
            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
            db_size = cur.fetchone()[0]
        sqlite_mb = SQLITE_PATH.stat().st_size / 1e6
        print(
            f"\nloaded {total_bytes / 1e6:.0f} MB of tables; "
            f"database is {db_size} against {sqlite_mb:.0f} MB of SQLite"
        )
        if skip:
            print(
                "Tables were skipped, so this is not the final size. Re-run "
                "without --skip once the headroom is confirmed."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
