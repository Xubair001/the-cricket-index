"""Derive the form band thresholds from the observed distribution.

The bands in `analytics.config.FORM_BANDS` are calibrated against real data
rather than picked by eye. Symmetric round numbers produce a classifier that
reports most of the population as declining, because the recent-window mean of a
right-skewed variable sits below the long-run mean more often than above it.

Run after a change to the impact model or a large ingest:

    cd backend && python -m scripts.calibrate_form [--sample N] [--scope international]

Prints the thresholds to paste into config, and the band distribution they give.
"""

from __future__ import annotations

import argparse
import statistics
import sys

from sqlalchemy import func, select

from app.analytics import config, form
from app.database import SessionLocal
from app.models import Match, PlayerMatchStat

# Share of the population each band should hold. "Stable" is deliberately the
# largest: most players, most of the time, are playing about as well as usual,
# and a classifier that says otherwise is measuring noise.
TARGETS = {"in_form": 0.15, "improving": 0.15, "stable": 0.40, "declining": 0.15}
MIN_CAREER_MATCHES = 20


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1500)
    ap.add_argument("--scope", default="international")
    ap.add_argument("--min-matches", type=int, default=MIN_CAREER_MATCHES)
    args = ap.parse_args()

    db = SessionLocal()
    ids = [
        i
        for (i,) in db.execute(
            select(PlayerMatchStat.player_identifier)
            .join(Match, Match.match_id == PlayerMatchStat.match_id)
            .where(PlayerMatchStat.player_identifier.is_not(None))
            .group_by(PlayerMatchStat.player_identifier)
            .having(func.count() >= args.min_matches)
        ).all()
    ]
    print(f"{len(ids)} players with >= {args.min_matches} matches; sampling {args.sample}")

    deltas: list[float] = []
    for pid in ids[: args.sample]:
        verdict = form.assess(db, pid, competition_type=args.scope)
        if verdict.delta_ratio is not None:
            deltas.append(verdict.delta_ratio)

    if not deltas:
        print("no deltas computed", file=sys.stderr)
        return 1

    deltas.sort()
    n = len(deltas)

    def pct(p: float) -> float:
        return deltas[min(n - 1, max(0, int(n * p)))]

    print(f"\nn={n}  median={statistics.median(deltas):+.3f}  mean={statistics.mean(deltas):+.3f}")
    print("percentiles: " + "  ".join(f"p{int(p*100)}={pct(p):+.2f}" for p in (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)))

    # Thresholds are the cut points that give each band its target share,
    # reading from the top of the distribution down.
    in_form = pct(1 - TARGETS["in_form"])
    improving = pct(1 - TARGETS["in_form"] - TARGETS["improving"])
    stable = pct(1 - TARGETS["in_form"] - TARGETS["improving"] - TARGETS["stable"])
    declining = pct(
        1 - TARGETS["in_form"] - TARGETS["improving"] - TARGETS["stable"] - TARGETS["declining"]
    )

    print("\nFORM_BANDS: list[tuple[str, float]] = [")
    for state, value in (
        ("in_form", in_form),
        ("improving", improving),
        ("stable", stable),
        ("declining", declining),
    ):
        print(f'    ("{state}", {value:.2f}),')
    print('    ("out_of_form", float("-inf")),\n]')

    bands = [("in_form", in_form), ("improving", improving), ("stable", stable),
             ("declining", declining), ("out_of_form", float("-inf"))]
    counts: dict[str, int] = {}
    for d in deltas:
        for state, threshold in bands:
            if d >= threshold:
                counts[state] = counts.get(state, 0) + 1
                break
    print("\nresulting distribution")
    for state, _ in bands:
        c = counts.get(state, 0)
        print(f"  {state:<14}{c:>6}{c / n * 100:>7.1f}%")

    print("\ncurrently in config:")
    for state, threshold in config.FORM_BANDS:
        print(f"  {state:<14}{threshold:>8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
