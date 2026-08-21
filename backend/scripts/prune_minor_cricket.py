"""Remove matches between two minor sides, and everything derived from them.

    python -m scripts.prune_minor_cricket --top 15 --dry-run
    python -m scripts.prune_minor_cricket --top 15 --apply

**What this is for.** The dataset holds every international side Cricsheet
publishes - 112 men's T20I teams, 90 women's - and because associate cricket is
played constantly, the most RECENT matches are almost all between sides nobody
is scouting. A matches list sorted newest-first therefore opens on Bulgaria v
Luxembourg, and the tournaments list carries 167 events of which most are
regional qualifiers. This prunes the dataset to the sides the product is about.

**The rule: a match goes only if NEITHER side is in the top N of its own scope.**
Both halves of that matter:

* *Neither side*, because a match between a top side and a minor one is part of
  the top side's record. Deleting it would silently change published career
  figures for the very players the product exists to rate.
* *Its own scope*, ranked per (competition, gender), because a side that is
  minor in T20Is may be major in Tests. One global ranking would cut the wrong
  matches. Ranked by matches played, which is the only ranking that covers all
  112 sides - ICC ranks about twenty.

**This is reversible, but not cheaply.** Deliveries and per-match figures are
re-derivable: `python starter.py t20is` re-downloads the Cricsheet archive and
re-parses, and content hashing means only the missing matches are written. That
is a full ingest run, not an undo, so take a copy of the file first.

**What it deliberately does not touch.** `teams` and `players` rows stay, even
when a side or a player is left with no matches at all. They cost kilobytes,
they carry the identity a future re-ingest would need to match against, and
deleting a player who once existed is a bigger claim than removing a fixture.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "cricket.db"

# Deleted parent-last, so a foreign key never dangles mid-transaction even with
# `PRAGMA foreign_keys=ON`.
CHILD_TABLES = ("deliveries", "player_match_stats")


def scope_rankings(con: sqlite3.Connection, top: int) -> dict[tuple[str, str], set[int]]:
    """The team_ids to KEEP, per (competition, gender)."""
    keep: dict[tuple[str, str], set[int]] = {}
    scopes = con.execute(
        """SELECT co.key, m.gender FROM matches m
           JOIN competitions co ON co.competition_id = m.competition_id
           GROUP BY co.key, m.gender"""
    ).fetchall()
    for key, gender in scopes:
        ranked = [
            r[0]
            for r in con.execute(
                """SELECT p.team_id FROM player_match_stats p
                   JOIN matches m ON m.match_id = p.match_id
                   JOIN competitions co ON co.competition_id = m.competition_id
                   WHERE co.key = ? AND m.gender = ?
                   GROUP BY p.team_id
                   -- team_id closes the ordering: sides tie on matches played,
                   -- and an arbitrary tie-break would make the cut differ
                   -- between runs on the same data.
                   ORDER BY COUNT(DISTINCT p.match_id) DESC, p.team_id ASC""",
                (key, gender),
            )
        ]
        keep[(key, gender)] = set(ranked[:top])
    return keep


def removable_matches(con: sqlite3.Connection, top: int) -> list[str]:
    keep = scope_rankings(con, top)
    rows = con.execute(
        """SELECT m.match_id, co.key, m.gender FROM matches m
           JOIN competitions co ON co.competition_id = m.competition_id"""
    ).fetchall()
    # One pass for every match's sides, rather than a query per match: the naive
    # form is 10,000 round trips and this is two.
    sides: dict[str, set[int]] = {}
    for match_id, team_id in con.execute(
        "SELECT match_id, team_id FROM player_match_stats WHERE team_id IS NOT NULL"
    ):
        sides.setdefault(match_id, set()).add(team_id)

    out = []
    for match_id, key, gender in rows:
        played = sides.get(match_id)
        if not played:
            continue
        if not (played & keep.get((key, gender), set())):
            out.append(match_id)
    return out


def summarise(con: sqlite3.Connection, ids: list[str]) -> None:
    if not ids:
        print("  nothing to remove")
        return
    con.execute("CREATE TEMP TABLE doomed(match_id TEXT PRIMARY KEY)")
    con.executemany("INSERT OR IGNORE INTO doomed VALUES (?)", [(i,) for i in ids])
    print(f"\n  {'scope':22} {'matches':>9} {'deliveries':>12} {'player rows':>12}")
    for key, gender, n, d, p in con.execute(
        """SELECT co.key, m.gender, COUNT(DISTINCT m.match_id),
                  (SELECT COUNT(*) FROM deliveries dv
                    JOIN matches mm ON mm.match_id = dv.match_id
                    JOIN competitions cc ON cc.competition_id = mm.competition_id
                    WHERE dv.match_id IN (SELECT match_id FROM doomed)
                      AND cc.key = co.key AND mm.gender = m.gender),
                  (SELECT COUNT(*) FROM player_match_stats pm
                    JOIN matches mm ON mm.match_id = pm.match_id
                    JOIN competitions cc ON cc.competition_id = mm.competition_id
                    WHERE pm.match_id IN (SELECT match_id FROM doomed)
                      AND cc.key = co.key AND mm.gender = m.gender)
           FROM matches m
           JOIN competitions co ON co.competition_id = m.competition_id
           WHERE m.match_id IN (SELECT match_id FROM doomed)
           GROUP BY co.key, m.gender ORDER BY 3 DESC"""
    ):
        print(f"  {key + '/' + gender:20} {n:9,} {d:12,} {p:12,}")
    events = con.execute(
        """SELECT COUNT(DISTINCT event_name) FROM matches
           WHERE match_id IN (SELECT match_id FROM doomed) AND event_name IS NOT NULL"""
    ).fetchone()[0]
    orphan_events = con.execute(
        """SELECT COUNT(*) FROM (
             SELECT event_name FROM matches WHERE event_name IS NOT NULL
             GROUP BY event_name
             HAVING SUM(CASE WHEN match_id IN (SELECT match_id FROM doomed)
                             THEN 0 ELSE 1 END) = 0)"""
    ).fetchone()[0]
    print(f"\n  events touched: {events}, of which {orphan_events} disappear entirely")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15, help="sides to keep per scope")
    ap.add_argument("--apply", action="store_true", help="actually delete")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"no database at {DB_PATH}", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA cache_size=-131072")

    before = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("matches", "player_match_stats", "deliveries")
    }
    ids = removable_matches(con, args.top)
    print(f"keeping the top {args.top} sides per (competition, gender)")
    print(f"matches to remove: {len(ids):,} of {before['matches']:,}")
    summarise(con, ids)

    if not args.apply:
        print("\ndry run - nothing written. Re-run with --apply to delete.")
        return 0

    size_before = DB_PATH.stat().st_size
    # Chunked so the parameter list stays inside SQLite's limit, and committed
    # per chunk so an interruption leaves a consistent database rather than a
    # half-rolled-back one.
    CHUNK = 500
    for table in CHILD_TABLES + ("matches",):
        removed = 0
        for i in range(0, len(ids), CHUNK):
            batch = ids[i : i + CHUNK]
            q = ",".join("?" * len(batch))
            cur = con.execute(f"DELETE FROM {table} WHERE match_id IN ({q})", batch)
            removed += cur.rowcount
            con.commit()
        print(f"  deleted {removed:,} rows from {table}")

    print("  vacuuming...", flush=True)
    con.execute("VACUUM")
    con.close()
    size_after = DB_PATH.stat().st_size
    print(
        f"\nfile: {size_before / 1e6:.0f} MB -> {size_after / 1e6:.0f} MB "
        f"({(size_before - size_after) / 1e6:.0f} MB freed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
