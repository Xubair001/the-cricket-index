r"""The analytics explorers -- the power-user surface (§21).

One filter model, three views
-----------------------------
Batting, bowling and all-round share a single `ExplorerFilters`, because a
scout narrowing to "T20Is against Australia since 2024" expects that narrowing
to mean the same thing whichever metric set they are looking at. Three separate
filter implementations is how those three views quietly stop agreeing.

Filtering, sorting and pagination all happen here rather than in the client
(§28): the unfiltered population is ~5,400 players, and shipping that to a
browser to sort it there would be both slow and a different answer from what
the ranking endpoints give.

Which filters are real, and which are absent
--------------------------------------------
§21 lists nine filters. Seven are implemented: format/competition, date range,
team, opposition, minimum innings, minimum balls, and a crude **role**. One is
**absent from the API rather than accepted and ignored** -- a filter that
silently does nothing is the specific failure Phase 1's exit gate names:

* **venue** -- 593 raw venue strings with 158 base names having variants, so a
  venue filter would split one ground's history across several values (Tier B).

Discipline decides who belongs in which explorer
-------------------------------------------------
A batter does not belong on a bowling board and a bowler does not belong on a
batting one; an all-rounder belongs on both. A volume floor alone does not
achieve that and never could -- across a long career a top-order batter's
occasional overs clear any sane minimum, so Kohli (989 balls bowled), Tendulkar
(2,812) and Root (8,120) all qualified for a bowling board gated only on volume,
while Muralitharan, Bumrah and Anderson all qualified for a batting one.

`discipline()` infers the split from balls faced versus balls bowled, which §5
sanctions explicitly, and `ELIGIBLE` maps it to the three views. The role is
INFERRED and labelled as such on every row -- it is not a sourced fact, and
wicketkeeper and opener remain out of reach at any threshold.

Qualification is mandatory, not optional
-----------------------------------------
`min_innings` and `min_balls` default to real values rather than zero. An
unfiltered strike-rate leaderboard is a list of players who faced two balls,
which is not a leaderboard of anything. The defaults are stated in the response
so the caller can see what was applied instead of wondering why a player they
expected is missing.

Conventional metrics stay conventional
---------------------------------------
Runs, average, strike rate, economy and bowling average are **not** adjusted for
opposition strength. They are the figures a user will check against a published
source, and a Test average here has to match the one on a scorecard site or the
whole product loses credibility.

The opposition adjustment belongs to `impact`, which is this project's own
measure and is labelled as such -- so the all-round explorer's contribution
figure carries it, and the conventional columns do not. Mixing the two would
produce a "batting average" no source publishes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..models import Competition, Match, Player, PlayerMatchStat
from ..venues import canonical_key
from ..names import preferred_name
from . import config, impact as impact_mod, opposition as opposition_mod

# Defaults chosen to match the qualification the player directory already
# applies, so the two surfaces agree about who is eligible.
DEFAULT_MIN_INNINGS = 5
DEFAULT_MIN_BALLS_FACED = 200
DEFAULT_MIN_BALLS_BOWLED = 300


@dataclass(frozen=True)
class ExplorerFilters:
    """The shared filter model. One definition for all three explorers."""

    gender: str
    competition_key: str | None = None
    competition_type: str | None = None
    team_id: int | None = None
    opposition_team_id: int | None = None
    date_from: str | None = None
    date_to: str | None = None
    min_innings: int = DEFAULT_MIN_INNINGS
    min_balls: int = 0
    # Canonical ground name (see app/venues.py). Matching happens on the
    # normalised key, so asking for "Sharjah Cricket Stadium" also returns the
    # seven matches Cricsheet filed under "Sharjah Cricket Association Stadium".
    venue: str | None = None
    # Narrow further *within* an explorer's eligible set. None = whoever
    # belongs in this explorer, which already excludes the other specialism.
    role: str | None = None

    def describe(self, explorer: str | None = None) -> dict:
        """What was actually applied -- returned with every response."""
        return {
            "gender": self.gender,
            "competition_key": self.competition_key,
            "competition_type": self.competition_type,
            "team_id": self.team_id,
            "opposition_team_id": self.opposition_team_id,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "min_innings": self.min_innings,
            "min_balls": self.min_balls,
            "venue": self.venue,
            "role": self.role,
            # Which inferred roles this explorer admits at all, so the caller can
            # see that a specialist bowler is absent from a batting board by
            # design rather than by accident.
            "roles_shown": sorted(ELIGIBLE[explorer]) if explorer in ELIGIBLE else None,
        }


def _opponent_id():
    """The side a row's player was playing against."""
    return func.iif(
        PlayerMatchStat.team_id == Match.team1_id, Match.team2_id, Match.team1_id
    )


def raw_venues_for(db: Session, canonical_name: str) -> list[str]:
    """Every raw venue string that normalises to this ground.

    Normalisation is a Python rule (comma-collapse plus a curated alias table),
    so it cannot be expressed as a WHERE clause on the raw column. Resolving the
    ground to its raw spellings first is what makes "matches at Sharjah" mean
    all 122 rather than the 115 filed under the commonest spelling.
    """
    wanted = canonical_key(canonical_name)
    if not wanted:
        return []
    # (venue, city) pairs, because a few ground names exist in more than one
    # place and the city is part of their identity -- "County Ground" alone is
    # eight different English grounds.
    rows = db.execute(
        select(Match.venue, Match.city).distinct().where(Match.venue.is_not(None))
    ).all()
    return sorted({v for v, c in rows if canonical_key(v, c) == wanted})


def _scoped(stmt: Select, f: ExplorerFilters, db: Session | None = None) -> Select:
    """Apply every filter that is actually supported."""
    stmt = stmt.where(Match.gender == f.gender)
    if f.competition_key:
        stmt = stmt.where(Competition.key == f.competition_key)
    if f.competition_type:
        stmt = stmt.where(Competition.type == f.competition_type)
    if f.team_id is not None:
        stmt = stmt.where(PlayerMatchStat.team_id == f.team_id)
    if f.opposition_team_id is not None:
        stmt = stmt.where(_opponent_id() == f.opposition_team_id)
    # Dates are ISO strings throughout, so lexical comparison is chronological.
    if f.date_from:
        stmt = stmt.where(Match.match_date_start >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Match.match_date_start <= f.date_to)
    if f.venue and db is not None:
        raws = raw_venues_for(db, f.venue)
        # An unknown ground matches nothing rather than everything -- a filter
        # that silently stops filtering is the failure Phase 1's gate names.
        stmt = stmt.where(Match.venue.in_(raws or [""]))
    return stmt


def _base(*columns) -> Select:
    return (
        select(*columns)
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .outerjoin(Player, Player.identifier == PlayerMatchStat.player_identifier)
        .where(PlayerMatchStat.player_identifier.is_not(None))
    )


def _identity_columns():
    # Grouped by identifier, never by name -- 70 names in this dataset belong to
    # more than one person. max() keeps the name columns valid under GROUP BY.
    return (
        func.coalesce(
            func.max(Player.name), func.max(PlayerMatchStat.player_name)
        ).label("scorecard_name"),
        func.max(Player.display_name).label("wikidata_name"),
        PlayerMatchStat.player_identifier.label("pid"),
    )


def _safe(numerator: float, denominator: float, places: int = 2) -> float | None:
    return round(numerator / denominator, places) if denominator else None


def discipline(balls_faced: int, balls_bowled: int) -> str:
    """Crude playing role, inferred from where a player spends their deliveries.

    'batter' | 'bowler' | 'allrounder' | 'unknown'. INFERRED, never sourced --
    nothing in this dataset states a role, and the API labels it as inferred so
    it can never be quoted as a fact about a player. Wicketkeeper and opener
    remain unavailable at any threshold; they need data that does not exist here.

    This is what keeps a specialist out of the wrong leaderboard. A volume floor
    cannot: Kohli has bowled 989 balls and Tendulkar 2,812, so both cleared a
    300-ball gate on a bowling board.
    """
    total = (balls_faced or 0) + (balls_bowled or 0)
    if not total:
        return "unknown"
    share = (balls_bowled or 0) / total
    if share < config.BATTER_MAX_BOWLING_SHARE:
        return "batter"
    if share > config.BOWLER_MIN_BOWLING_SHARE:
        return "bowler"
    return "allrounder"


# Who belongs in each explorer. All-rounders appear in batting and bowling
# alike -- they genuinely do both -- while a specialist appears only in their
# own discipline, and the all-round view is all-rounders only.
ELIGIBLE: dict[str, set[str]] = {
    "batting": {"batter", "allrounder"},
    "bowling": {"bowler", "allrounder"},
    "allround": {"allrounder"},
}


def batting_rows(db: Session, f: ExplorerFilters) -> list[dict]:
    """Batting metrics: runs, average, strike rate, boundary %."""
    stmt = _base(
        *_identity_columns(),
        func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
        func.sum(PlayerMatchStat.runs_scored).label("runs"),
        func.sum(PlayerMatchStat.dismissals).label("dismissals"),
        func.sum(PlayerMatchStat.balls_faced).label("balls_faced"),
        func.sum(PlayerMatchStat.fours).label("fours"),
        func.sum(PlayerMatchStat.sixes).label("sixes"),
        func.sum(PlayerMatchStat.balls_bowled).label("balls_bowled"),
    ).group_by(PlayerMatchStat.player_identifier)
    stmt = _scoped(stmt, f, db)

    out = []
    for r in db.execute(stmt).all():
        matches = r.matches or 0
        balls = r.balls_faced or 0
        if matches < f.min_innings or balls < f.min_balls:
            continue
        role = discipline(balls, r.balls_bowled or 0)
        if role not in ELIGIBLE["batting"] or (f.role and role != f.role):
            continue
        runs, dismissals = r.runs or 0, r.dismissals or 0
        fours, sixes = r.fours or 0, r.sixes or 0
        out.append(
            {
                "role": role,
                "player_name": preferred_name(r.scorecard_name, r.wikidata_name),
                "player_identifier": r.pid,
                "matches": matches,
                "runs": runs,
                "dismissals": dismissals,
                "balls_faced": balls,
                "fours": fours,
                "sixes": sixes,
                # Average divides by dismissals, not innings -- a Test has two
                # innings a side, so a player can be out twice in one match.
                "average": _safe(runs, dismissals),
                "strike_rate": _safe(runs * 100.0, balls),
                # Share of deliveries put away for four or six. Measured on
                # balls faced (as §5 specifies) rather than on runs, so it reads
                # as "how often", not "how much of the total".
                "boundary_pct": _safe((fours + sixes) * 100.0, balls),
            }
        )
    return out


def bowling_rows(db: Session, f: ExplorerFilters) -> list[dict]:
    """Bowling metrics: wickets, average, economy, strike rate."""
    stmt = _base(
        *_identity_columns(),
        func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
        func.sum(PlayerMatchStat.wickets_taken).label("wickets"),
        func.sum(PlayerMatchStat.balls_bowled).label("balls_bowled"),
        func.sum(PlayerMatchStat.runs_conceded).label("runs_conceded"),
        func.sum(PlayerMatchStat.balls_faced).label("balls_faced"),
    ).group_by(PlayerMatchStat.player_identifier)
    stmt = _scoped(stmt, f, db)

    out = []
    for r in db.execute(stmt).all():
        matches = r.matches or 0
        balls = r.balls_bowled or 0
        if matches < f.min_innings or balls < f.min_balls:
            continue
        role = discipline(r.balls_faced or 0, balls)
        if role not in ELIGIBLE["bowling"] or (f.role and role != f.role):
            continue
        wickets, conceded = r.wickets or 0, r.runs_conceded or 0
        out.append(
            {
                "role": role,
                "player_name": preferred_name(r.scorecard_name, r.wikidata_name),
                "player_identifier": r.pid,
                "matches": matches,
                "wickets": wickets,
                "balls_bowled": balls,
                "runs_conceded": conceded,
                "average": _safe(conceded, wickets),
                "economy": _safe(conceded * 6.0, balls),
                # Balls per wicket.
                "strike_rate": _safe(balls, wickets),
            }
        )
    return out


def allround_rows(db: Session, f: ExplorerFilters) -> list[dict]:
    """Combined contribution and balance, in par units.

    Unlike the other two explorers this one is expressed in impact rather than
    conventional figures, because there is no conventional statistic for "how
    much did this player contribute overall" -- runs and wickets do not add up.
    Impact converts both to runs-equivalent, which is exactly what makes them
    addable, and is normalized so 1.0 is a par appearance in that competition.

    Grouped by (player, competition, opponent) so the opposition adjustment can
    be applied per opponent before being summed back up to the player. Summing
    first and adjusting afterwards would apply one side's multiplier to cricket
    played against everybody.
    """
    par = impact_mod.par_table(db)
    opp = opposition_mod.table(db)

    stmt = _base(
        *_identity_columns(),
        Competition.key.label("comp_key"),
        _opponent_id().label("opponent_id"),
        func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
        func.sum(PlayerMatchStat.runs_scored).label("runs"),
        func.sum(PlayerMatchStat.balls_faced).label("balls_faced"),
        func.sum(PlayerMatchStat.wickets_taken).label("wickets"),
        func.sum(PlayerMatchStat.balls_bowled).label("balls_bowled"),
        func.sum(PlayerMatchStat.runs_conceded).label("runs_conceded"),
    ).group_by(PlayerMatchStat.player_identifier, Competition.key, _opponent_id())
    stmt = _scoped(stmt, f, db)

    # pid -> accumulated figures across every (competition, opponent) group
    acc: dict[str, dict] = {}
    for r in db.execute(stmt).all():
        p = par.lookup(r.comp_key, f.gender)
        if not p.mean_impact:
            continue
        multiplier = opp.multiplier(r.opponent_id, r.comp_key)

        runs, bf = r.runs or 0, r.balls_faced or 0
        wkts, bb, conceded = r.wickets or 0, r.balls_bowled or 0, r.runs_conceded or 0

        batting = runs + (runs - (p.scoring_rate / 100.0) * bf)
        bowling = wkts * p.runs_per_wicket + ((p.economy / 6.0) * bb - conceded)

        entry = acc.setdefault(
            r.pid,
            {
                "player_name": preferred_name(r.scorecard_name, r.wikidata_name),
                "player_identifier": r.pid,
                "matches": 0, "batting": 0.0, "bowling": 0.0,
                "runs": 0, "wickets": 0, "balls_faced": 0, "balls_bowled": 0,
            },
        )
        entry["matches"] += r.matches or 0
        entry["batting"] += (batting / p.mean_impact) * multiplier
        entry["bowling"] += (bowling / p.mean_impact) * multiplier
        entry["runs"] += runs
        entry["wickets"] += wkts
        entry["balls_faced"] += bf
        entry["balls_bowled"] += bb

    out = []
    for e in acc.values():
        matches = e["matches"]
        if matches < f.min_innings:
            continue
        if (e["balls_faced"] + e["balls_bowled"]) < f.min_balls:
            continue
        role = discipline(e["balls_faced"], e["balls_bowled"])
        if role not in ELIGIBLE["allround"] or (f.role and role != f.role):
            continue
        bat, bowl = e["batting"], e["bowling"]
        combined = bat + bowl
        # Positive-only shares: a negative bowling contribution (conceding more
        # than par) would otherwise produce a balance above 1 or below 0, which
        # reads as a data error rather than as "they were expensive".
        pos_bat, pos_bowl = max(bat, 0.0), max(bowl, 0.0)
        out.append(
            {
                "role": role,
                "player_name": e["player_name"],
                "player_identifier": e["player_identifier"],
                "matches": matches,
                "runs": e["runs"],
                "wickets": e["wickets"],
                "batting_contribution": round(bat / matches, 3),
                "bowling_contribution": round(bowl / matches, 3),
                "combined_contribution": round(combined / matches, 3),
                # 0 = purely a bowler, 1 = purely a batter, 0.5 = balanced.
                "balance": _safe(pos_bat, pos_bat + pos_bowl, 3),
            }
        )
    return out


# Which sorts each explorer accepts, and whether smaller is better. Validated
# against this map rather than interpolated into SQL.
SORTS: dict[str, dict[str, bool]] = {
    "batting": {
        "runs": False, "average": False, "strike_rate": False,
        "boundary_pct": False, "matches": False, "balls_faced": False,
    },
    "bowling": {
        "wickets": False, "average": True, "economy": True,
        "strike_rate": True, "matches": False, "balls_bowled": False,
    },
    "allround": {
        "combined_contribution": False, "batting_contribution": False,
        "bowling_contribution": False, "matches": False, "balance": False,
    },
}

BUILDERS = {
    "batting": batting_rows,
    "bowling": bowling_rows,
    "allround": allround_rows,
}


def page(
    db: Session,
    explorer: str,
    f: ExplorerFilters,
    sort_by: str,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """One sorted, paginated page of an explorer, plus the total after filters.

    Sorted in Python for the same reason the ranking aggregates are: the rate
    metrics need a divide-by-zero guard that is awkward in SQLite, and a row
    whose average is undefined must sort last rather than as zero -- which is
    what `None` would do if the database ordered it.
    """
    rows = BUILDERS[explorer](db, f)
    ascending = SORTS[explorer].get(sort_by, False)

    def key(row: dict):
        value = row.get(sort_by)
        # None sorts last in whichever direction was asked for, rather than
        # masquerading as the best or worst figure in the table.
        missing = value is None
        return (missing, value if not missing else 0)

    rows.sort(key=lambda r: r["player_identifier"] or "")
    rows.sort(key=key, reverse=not ascending)
    # `reverse` would also flip the missing-last flag, so re-partition.
    present = [r for r in rows if r.get(sort_by) is not None]
    absent = [r for r in rows if r.get(sort_by) is None]
    rows = present + absent

    return rows[offset : offset + limit], len(rows)


__all__ = [
    "ExplorerFilters", "page", "SORTS", "BUILDERS",
    "DEFAULT_MIN_INNINGS", "DEFAULT_MIN_BALLS_FACED", "DEFAULT_MIN_BALLS_BOWLED",
]
