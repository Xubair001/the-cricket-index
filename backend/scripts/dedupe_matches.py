"""Find and repair matches described twice by two different sources.

Why this exists
---------------
`matches` holds Cricsheet records and, for matches Cricsheet has not published,
ICC scorecard stand-ins. The two must never both count: an ICC row for a match
Cricsheet also describes inflates every aggregate that reads `matches`, and it
does so invisibly.

`ingest_match` already drops a superseded ICC row when the Cricsheet version is
written, keyed on `natural_key` = (gender, competition, date, sorted sides). Two
things defeated it:

1. **The cleanup only fires when a Cricsheet match is parsed.** An ICC row that
   arrives *after* the Cricsheet match was already stored is never revisited,
   because the Cricsheet match then hash-skips and the delete never runs.
2. **The key used raw team names.** The feeds spell some sides differently -
   ICC says "Turkiye" and "France Cricket" where Cricsheet says "Turkey" and
   "France" - so the keys did not match and the rows survived as a pair.

`icc_scorecard.natural_key` now normalises the spellings, which fixes new
inserts. It does not fix rows already stored, because their key was computed at
insert time. This repairs those.

    cd backend && python -m scripts.dedupe_matches           # report only
    cd backend && python -m scripts.dedupe_matches --apply   # delete the ICC copies

Cricsheet always wins, for the reason CLAUDE.md gives: it is the ball-by-ball
source every derived figure is built on, and the ICC scorecard exists only to
cover what it has not published.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

from sqlalchemy import text

from app.database import SessionLocal

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "ingestion",
    ),
)
from icc_scorecard import natural_key  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="delete the duplicate ICC rows. Without it, report only.")
    args = parser.parse_args()
    db = SessionLocal()

    rows = db.execute(text("""
        SELECT m.match_id, m.source, m.gender, m.match_date_start,
               c.key AS competition, t1.name AS a, t2.name AS b
        FROM matches m
        JOIN competitions c ON c.competition_id = m.competition_id
        LEFT JOIN teams t1 ON t1.team_id = m.team1_id
        LEFT JOIN teams t2 ON t2.team_id = m.team2_id
        WHERE m.match_date_start IS NOT NULL
    """)).all()

    # Recompute the key with the CURRENT rule rather than reading the stored
    # column, which is exactly the value that is wrong on the affected rows.
    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in rows:
        key = natural_key(r.gender, r.competition, r.match_date_start, r.a, r.b)
        buckets[key].append((r.match_id, r.source))

    dupes = {
        k: v for k, v in buckets.items()
        if len(v) > 1 and {s for _, s in v} == {"cricsheet", "icc"}
    }
    victims = [mid for v in dupes.values() for mid, src in v if src == "icc"]

    print(f"{len(rows)} matches scanned")
    print(f"{len(dupes)} fixtures described by BOTH sources")
    print(f"{len(victims)} ICC rows superseded by a Cricsheet record\n")
    for key, v in list(dupes.items())[:10]:
        print(f"  {key}")
        for mid, src in v:
            print(f"      {src:<10} {mid}")

    # Rows where two sources describe the same fixture but neither is
    # Cricsheet, or where two Cricsheet rows collide, are NOT touched: the
    # first is not a case this repair understands and the second would mean
    # Cricsheet published one match twice, which is a different problem.
    odd = {k: v for k, v in buckets.items()
           if len(v) > 1 and {s for _, s in v} != {"cricsheet", "icc"}}
    if odd:
        print(f"\n{len(odd)} same-key groups NOT from a cricsheet/icc pair, left alone:")
        for k, v in list(odd.items())[:5]:
            print(f"  {k} -> {v}")

    if not victims:
        print("\nnothing to repair")
        return 0
    if not args.apply:
        print("\nre-run with --apply to delete the ICC copies")
        return 0

    for mid in victims:
        # Same order ingest_match uses: dependants first, then the match.
        db.execute(text("DELETE FROM deliveries WHERE match_id = :m"), {"m": mid})
        db.execute(text("DELETE FROM player_match_stats WHERE match_id = :m"), {"m": mid})
        db.execute(text("DELETE FROM matches WHERE match_id = :m"), {"m": mid})
    db.commit()
    print(f"\ndeleted {len(victims)} superseded ICC matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
