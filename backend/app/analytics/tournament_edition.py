r"""One edition of one tournament: its table, its fixtures, and who won it.

Why this is a module and not a bigger `tournaments.get_tournament`
-----------------------------------------------------------------
`app/tournaments.py` answers "which tournaments exist, and who has won them",
and it does that by folding 10k match rows into canonical events in Python. An
edition page asks a different set of questions - a standings table, a fixture
list, per-edition leaderboards - and every one of them is a statistical
aggregate over a known set of match ids. §32 puts that in the analytics layer,
so the event-name folding stays in `tournaments.py` and the arithmetic lives
here. `tournaments.py` passes the match ids in; this module never parses an
event name.

The three things worth knowing about the standings table
--------------------------------------------------------
**Points are the near-universal limited-overs convention, not a lookup.** Two
for a win, one for a tie or no-result, none for a loss. That is what the ICC
uses across World Cups, the Champions Trophy and the PSL alike, so it is stated
as the convention it is rather than dressed up as this tournament's own rules.
Where a tournament used something else - bonus points, carry-over points from a
group stage, Super Six carry-forward - this table will disagree with the
published one, so `standings_caveats` says so on any edition with a stage that
implies it. Nothing here is presented as an official table.

**Net run rate uses the all-out rule, because ignoring it is silently wrong.**
A side bowled out inside its overs is charged the FULL quota, not the overs it
actually used. Skipping that inflates the run rate of every side that collapsed
and deflates its opponent's, which is the difference between a table that
matches the published one and a table that looks close and is not. `overs_limit`
supplies the quota, so NRR is computed only where the format has one - a Test
edition gets no NRR at all rather than a meaningless one.

**A tie and a no-result are different rows in the table and the same points.**
Cricsheet records a tie with `outcome_result='tie'` and no winner, and an
abandoned match with `'no result'`. Both score one point and only one of them
means the sides were level, so they are counted separately and shown
separately.

Coverage governs the whole page
-------------------------------
This dataset holds 36 of the 48 matches of the 2019 men's World Cup, and most
editions are short by a few matches. So a standings table computed here is a
table of *the matches held*, which is not the tournament's own table, and a
per-edition leading run-scorer is a floor rather than the published figure.
Both are labelled that way rather than left to be assumed - the same rule
`tournaments._notes` already follows.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import flags, queries as queries_mod
from ..models import Delivery, Match, Player, PlayerMatchStat, Team
from ..names import preferred_name

# Rows per leaderboard. Enough to show a real contest for the golden bat rather
# than only the winner.
TOP_N = 10

# From here Afghanistan were regulars at global events, so their absence from a
# later edition needs explaining. Before it they simply had not qualified, and
# saying otherwise would be false. Duplicated from `tournaments.py` rather than
# imported, because `tournaments` imports this module and the reverse would be
# a cycle; the two must stay equal.
AFGHANISTAN_QUALIFIED_FROM = "2015-01-01"

# 2 for a win, 1 for a tie or an abandoned match, 0 for a loss.
POINTS_WIN = 2
POINTS_SHARED = 1

# Stages whose presence means the published table almost certainly used
# carry-over or bonus points, so ours will not match it.
NON_STANDARD_POINTS_STAGES = {
    "Super Sixes", "Super Six", "Super Four", "Super Three", "Super 10",
}

# A KNOCKOUT match does not belong in a standings table, and leaving it in is
# not a rounding error: counted into the 2019 World Cup group table the tied
# final gave England 10 played and 13 points against the published 9 and 12.
#
# Enumerated rather than pattern-matched, the same call `venues.py` and
# `events.py` make: `matches.event_stage` holds 35 distinct values in this
# dataset and every one of them is classifiable by reading it. A substring rule
# on "Final" would also catch a hypothetical league stage containing the word,
# and this project has been burned by exactly that kind of rule before.
KNOCKOUT_STAGES = {
    "11th Place Play-Off", "3rd Place Play-Off", "3rd Place Play-off",
    "4th Place Play-Off", "5th Place Play-Off", "5th place playoff",
    "7th Place Play-Off", "7th place playoff", "9th Place Play-Off",
    "Eliminator", "Final", "Play-Off", "Play-off", "Play-off Semi-Final",
    "Preliminary Final", "Qualifier", "Qualifier 1", "Qualifier 2",
    "Qualifier 3", "Qualifier 4", "Qualifying Play-off", "Quarter Final",
    "Semi Final", "Semi-Final", "Semi-final", "Super League Final",
    "Trophy Final",
}

# Round-robin stages, which DO have a table. `None` - a plain group or league
# match - is the overwhelming majority and is treated as one of these. "ODI"
# and "T20" are format labels that have leaked into the stage column on a
# handful of rows rather than stages at all, so they are league by default.
LEAGUE_STAGES = {
    "First Round", "Qualifying Group", "Super 10", "Super Four",
    "Super Sixes", "Super Three", "ODI", "T20",
}

# Fallback for a spelling neither set has seen. Cricket names its knockouts from
# a small vocabulary, so these hints catch a new spelling of one; anything else
# falls through to league, which is the right default because a new ROUND-ROBIN
# name ("Group Stage", "League Phase") is far likelier to appear than a knockout
# that avoids every word below. Whatever happens, the stage is reported in
# `standings_caveats`, so the guess is visible rather than silent.
_KNOCKOUT_HINTS = ("final", "qualifier", "eliminator", "play-off", "playoff")


def is_knockout(stage: str | None) -> bool:
    """Whether a match is single-elimination, and so outside any table."""
    if stage is None or stage in LEAGUE_STAGES:
        return False
    if stage in KNOCKOUT_STAGES:
        return True
    lowered = stage.lower()
    return any(hint in lowered for hint in _KNOCKOUT_HINTS)


def unknown_stages(stages: set[str | None]) -> list[str]:
    """Stages in neither vocabulary, so a new spelling surfaces rather than
    being silently classified."""
    return sorted(
        s for s in stages
        if s is not None and s not in LEAGUE_STAGES and s not in KNOCKOUT_STAGES
    )


@dataclass(slots=True)
class StandingsRow:
    team_id: int
    team_name: str
    country_code: str | None
    group: str | None
    played: int = 0
    won: int = 0
    lost: int = 0
    tied: int = 0
    no_result: int = 0
    points: int = 0
    win_pct: float | None = None
    runs_for: int = 0
    balls_faced: int = 0
    runs_against: int = 0
    balls_bowled: int = 0
    # None where the format has no overs limit, or where no ball record exists
    # for this side's matches. Never 0.0 as a stand-in.
    net_run_rate: float | None = None


@dataclass(slots=True)
class EditionMatch:
    match_id: str
    match_date: str | None
    stage: str | None
    group: str | None
    venue: str | None
    city: str | None
    team1_id: int | None
    team1_name: str | None
    team1_code: str | None
    team2_id: int | None
    team2_name: str | None
    team2_code: str | None
    winner_team_id: int | None
    winner_name: str | None
    # Populated only for a tie settled on a super over, boundary count or
    # bowl-out. Cricsheet puts this in `eliminator`, NOT in `winner`.
    eliminator_name: str | None
    outcome_result: str | None
    win_by_runs: int | None
    win_by_wickets: int | None
    # "England won by 8 wickets", already assembled so a client is not left to
    # reconstruct cricket's own phrasing.
    result_text: str
    # Preferred form where the name resolves to one of our players ("Matt
    # Henry"), the raw Cricsheet value otherwise. The scorecard form travels
    # alongside, the same shape the player endpoints use.
    player_of_match: str | None
    player_of_match_scorecard: str | None
    player_of_match_identifier: str | None
    # Team totals off the ball record, so extras are included. None where this
    # match has no deliveries stored (an ICC-sourced stand-in).
    team1_score: str | None
    team2_score: str | None


@dataclass(slots=True)
class EditionLeader:
    player_identifier: str
    player_name: str
    country_code: str | None
    matches: int
    runs: int | None = None
    balls_faced: int | None = None
    average: float | None = None
    strike_rate: float | None = None
    fifties: int | None = None
    hundreds: int | None = None
    highest: int | None = None
    wickets: int | None = None
    balls_bowled: int | None = None
    runs_conceded: int | None = None
    economy: float | None = None
    bowling_average: float | None = None
    best_innings: int | None = None
    awards: int | None = None


@dataclass(slots=True)
class EditionDetail:
    tournament_name: str
    tournament_slug: str
    season: str | None
    gender: str
    competition_key: str
    competition_name: str
    matches: int
    sides: int
    first_date: str | None
    last_date: str | None
    champion_team_id: int | None = None
    champion_name: str | None = None
    runner_up_name: str | None = None
    has_final: bool = False
    decided_by_tiebreak: bool = False
    final_match_id: str | None = None
    venues: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    standings: list[StandingsRow] = field(default_factory=list)
    fixtures: list[EditionMatch] = field(default_factory=list)
    top_run_scorers: list[EditionLeader] = field(default_factory=list)
    top_wicket_takers: list[EditionLeader] = field(default_factory=list)
    most_awards: list[EditionLeader] = field(default_factory=list)
    standings_caveats: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _chunks(ids: list[str], size: int = 500):
    """SQLite caps a statement's variables, and an edition can be 50+ matches."""
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


def _result_text(
    match: Match, team_names: dict[int, str], winner: str | None, eliminator: str | None
) -> str:
    """The result the way a scorecard states it."""
    if eliminator:
        # The 2019 final. Cricsheet stores a tie with no winner and the side
        # that took the tiebreak in `eliminator`, so reading only `winner` shows
        # the most famous final of the decade as won by nobody.
        return f"{eliminator} won on a tiebreak after the match was tied"
    if winner:
        if match.win_by_runs:
            return f"{winner} won by {match.win_by_runs} run{'s' if match.win_by_runs != 1 else ''}"
        if match.win_by_wickets:
            return f"{winner} won by {match.win_by_wickets} wicket{'s' if match.win_by_wickets != 1 else ''}"
        return f"{winner} won"
    result = (match.outcome_result or "").strip().lower()
    if result == "tie":
        return "Match tied"
    if result in {"no result", "no_result"}:
        return "No result"
    if result:
        return result.capitalize()
    return "Result not recorded"


# A limited-overs match has two innings. Anything past that is a super over,
# which Cricsheet stores as further innings on the same match with no flag of
# its own - so the innings number is the only signal there is.
#
# Summing every innings is wrong in a way that looks right: the 2019 World Cup
# final comes out England 256/10 against New Zealand 256/9, because each side's
# 15-run super over is folded into their 241. The real scoreline is 241 each,
# and the super over is not part of either total or of any run rate.
LIMITED_OVERS_INNINGS = 2


def _team_innings(
    db: Session, match_ids: list[str], overs_limit: dict[str, int | None]
) -> dict[tuple[str, int], list[dict]]:
    """Per (match, batting side): each of their innings, newest last.

    Reads `runs_total` rather than summing batters, so extras are included and a
    score here is a real team total. `player_match_stats` cannot do this - a wide
    is charged to the bowler and byes to nobody, so a side's batters understate
    the total by roughly 5%, which is exactly the error that would make a net
    run rate look plausible and be wrong.

    Super-over innings are dropped, per the note above.
    """
    rows: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for chunk in _chunks(match_ids):
        stmt = (
            select(
                Delivery.match_id,
                Delivery.batting_team_id,
                Delivery.innings,
                func.sum(Delivery.runs_total),
                # A legal ball: wides and no-balls do not count towards the over.
                func.sum(
                    func.iif((Delivery.wides == 0) & (Delivery.noballs == 0), 1, 0)
                ),
                # Dismissals that cost the side a wicket. Retired hurt is not
                # one, which is why this is not simply "wicket_kind not null".
                func.sum(
                    func.iif(
                        Delivery.wicket_kind.is_not(None)
                        & Delivery.wicket_kind.notin_(("retired hurt", "retired not out")),
                        1,
                        0,
                    )
                ),
            )
            .where(Delivery.match_id.in_(chunk), Delivery.batting_team_id.is_not(None))
            .group_by(Delivery.match_id, Delivery.batting_team_id, Delivery.innings)
            .order_by(Delivery.match_id, Delivery.innings)
        )
        for match_id, team_id, innings, runs, balls, wickets in db.execute(stmt).all():
            # Only limited-overs cricket has super overs; a Test's third and
            # fourth innings are the match, not a tiebreak.
            if overs_limit.get(match_id) and innings > LIMITED_OVERS_INNINGS:
                continue
            rows[(match_id, team_id)].append(
                {
                    "innings": innings,
                    "runs": runs or 0,
                    "balls": balls or 0,
                    "wickets": wickets or 0,
                }
            )
    return rows


def _score_text(innings: list[dict] | None) -> str | None:
    """"286/9", or "241 & 180/4" where a side batted twice."""
    if not innings:
        return None
    return " & ".join(f"{i['runs']}/{i['wickets']}" for i in innings)


def _standings(
    db: Session,
    matches: list[Match],
    team_names: dict[int, str],
    team_codes: dict[int, str | None],
    innings: dict[tuple[str, int], list[dict]],
) -> tuple[list[StandingsRow], list[str]]:
    """The table, from results, with net run rate off the ball record.

    Only round-robin matches are counted. See `is_knockout` for why leaving the
    knockouts in is worse than it sounds.
    """
    rows: dict[tuple[int, str | None], StandingsRow] = {}
    caveats: list[str] = []

    def row_for(team_id: int, group: str | None) -> StandingsRow:
        key = (team_id, group)
        if key not in rows:
            rows[key] = StandingsRow(
                team_id=team_id,
                team_name=team_names.get(team_id, str(team_id)),
                country_code=team_codes.get(team_id),
                group=group,
            )
        return rows[key]

    quota_seen: set[int] = set()
    league = [m for m in matches if not is_knockout(m.event_stage)]
    excluded = [m for m in matches if is_knockout(m.event_stage)]
    for match in league:
        if match.team1_id is None or match.team2_id is None:
            continue
        group = match.event_group
        for team_id, opponent_id in (
            (match.team1_id, match.team2_id),
            (match.team2_id, match.team1_id),
        ):
            row = row_for(team_id, group)
            row.played += 1
            result = (match.outcome_result or "").strip().lower()
            if match.winner_team_id == team_id:
                row.won += 1
                row.points += POINTS_WIN
            elif match.winner_team_id is not None:
                row.lost += 1
            elif result == "tie":
                row.tied += 1
                row.points += POINTS_SHARED
            else:
                row.no_result += 1
                row.points += POINTS_SHARED

            limit = match.overs_limit
            if not limit:
                continue
            # An abandoned match contributes to neither side's run rate, which
            # is the rule every published table follows: with no result there is
            # nothing to rate.
            if match.winner_team_id is None and result in {"no result", "no_result"}:
                continue
            for own in innings.get((match.match_id, team_id), []):
                row.runs_for += own["runs"]
                # The all-out rule: a side bowled out is charged its full quota,
                # not the overs it used. Without this every collapse inflates
                # the batting side's run rate and deflates the bowling side's.
                row.balls_faced += limit * 6 if own["wickets"] >= 10 else own["balls"]
                quota_seen.add(limit)
            for other in innings.get((match.match_id, opponent_id), []):
                row.runs_against += other["runs"]
                row.balls_bowled += limit * 6 if other["wickets"] >= 10 else other["balls"]

    for row in rows.values():
        decided = row.won + row.lost
        row.win_pct = round(100.0 * row.won / decided, 1) if decided else None
        if row.balls_faced and row.balls_bowled:
            scored = row.runs_for / (row.balls_faced / 6)
            conceded = row.runs_against / (row.balls_bowled / 6)
            row.net_run_rate = round(scored - conceded, 3)

    ordered = sorted(
        rows.values(),
        key=lambda r: (
            r.group or "",
            -r.points,
            -(r.net_run_rate if r.net_run_rate is not None else -99),
            -r.won,
            r.team_name,
        ),
    )

    if excluded:
        stage_list = ", ".join(sorted({m.event_stage for m in excluded if m.event_stage}))
        caveats.append(
            f"{len(excluded)} knockout match"
            f"{'es' if len(excluded) != 1 else ''} ({stage_list}) are excluded "
            f"from this table, because a single-elimination match is not part of "
            f"any group's record."
        )
    surprises = unknown_stages({m.event_stage for m in matches})
    if surprises:
        caveats.append(
            "Stage not recognised, so it was classified by name: "
            + ", ".join(
                f'"{s}" (treated as {"a knockout" if is_knockout(s) else "round-robin"})'
                for s in surprises
            )
            + ". Add it to KNOCKOUT_STAGES or LEAGUE_STAGES in "
            "analytics/tournament_edition.py to make the classification explicit."
        )

    stages = {m.event_stage for m in matches if m.event_stage}
    if stages & NON_STANDARD_POINTS_STAGES:
        caveats.append(
            "This edition had a "
            + ", ".join(sorted(stages & NON_STANDARD_POINTS_STAGES))
            + " stage, which normally carries points forward from the group "
            "stage. Points here are counted from the matches held and will not "
            "match the published table."
        )
    if not quota_seen:
        caveats.append(
            "No net run rate: this format has no overs limit, so a run rate "
            "describes nothing comparable between sides."
        )
    return ordered, caveats


def _leaders(
    db: Session,
    match_ids: list[str],
    names: dict[str, str],
    codes: dict[str, str | None],
    awards: dict[str, int],
) -> tuple[list[EditionLeader], list[EditionLeader], list[EditionLeader]]:
    """Runs, wickets and awards within one edition.

    Conventional figures, deliberately NOT opposition-adjusted: a tournament's
    leading run-scorer is a published, checkable number, and a version weighted
    by a fitted model would match no source. Same call `tournaments._leaderboards`
    makes for the same reason.
    """
    if not match_ids:
        return [], [], []

    agg: dict[str, dict] = defaultdict(
        lambda: {
            "runs": 0, "balls_faced": 0, "dismissals": 0, "matches": 0,
            "wickets": 0, "balls_bowled": 0, "conceded": 0,
            "fifties": 0, "hundreds": 0, "highest": 0, "best": 0,
        }
    )
    for chunk in _chunks(match_ids):
        stmt = select(
            PlayerMatchStat.player_identifier,
            PlayerMatchStat.runs_scored,
            PlayerMatchStat.balls_faced,
            PlayerMatchStat.dismissals,
            PlayerMatchStat.wickets_taken,
            PlayerMatchStat.balls_bowled,
            PlayerMatchStat.runs_conceded,
        ).where(
            PlayerMatchStat.match_id.in_(chunk),
            PlayerMatchStat.player_identifier.is_not(None),
        )
        for pid, runs, faced, outs, wkts, bowled, conceded in db.execute(stmt).all():
            a = agg[pid]
            a["matches"] += 1
            a["runs"] += runs or 0
            a["balls_faced"] += faced or 0
            a["dismissals"] += outs or 0
            a["wickets"] += wkts or 0
            a["balls_bowled"] += bowled or 0
            a["conceded"] += conceded or 0
            # Milestones are per match rather than per innings. A Test can give
            # a player two innings in one row, so a 60 and a 55 would count once
            # here where a scorecard counts twice. Limited-overs editions - which
            # is every tournament in this dataset bar the odd Test event - have
            # one innings per match, so the two agree.
            if (runs or 0) >= 100:
                a["hundreds"] += 1
            elif (runs or 0) >= 50:
                a["fifties"] += 1
            a["highest"] = max(a["highest"], runs or 0)
            a["best"] = max(a["best"], wkts or 0)

    def batting(pid: str, a: dict) -> EditionLeader:
        return EditionLeader(
            player_identifier=pid,
            player_name=names.get(pid, pid),
            country_code=codes.get(pid),
            matches=a["matches"],
            runs=a["runs"],
            balls_faced=a["balls_faced"],
            # Runs per dismissal, not per innings: `dismissals` is a count
            # because a Test can dismiss a player twice.
            average=round(a["runs"] / a["dismissals"], 2) if a["dismissals"] else None,
            strike_rate=round(100.0 * a["runs"] / a["balls_faced"], 2) if a["balls_faced"] else None,
            fifties=a["fifties"],
            hundreds=a["hundreds"],
            highest=a["highest"] or None,
            awards=awards.get(pid) or None,
        )

    def bowling(pid: str, a: dict) -> EditionLeader:
        return EditionLeader(
            player_identifier=pid,
            player_name=names.get(pid, pid),
            country_code=codes.get(pid),
            matches=a["matches"],
            wickets=a["wickets"],
            balls_bowled=a["balls_bowled"],
            runs_conceded=a["conceded"],
            economy=round(a["conceded"] / (a["balls_bowled"] / 6), 2) if a["balls_bowled"] else None,
            bowling_average=round(a["conceded"] / a["wickets"], 2) if a["wickets"] else None,
            best_innings=a["best"] or None,
            awards=awards.get(pid) or None,
        )

    scorers = [
        batting(pid, a)
        for pid, a in sorted(agg.items(), key=lambda x: (-x[1]["runs"], x[0]))[:TOP_N]
        if a["runs"] > 0
    ]
    takers = [
        bowling(pid, a)
        for pid, a in sorted(agg.items(), key=lambda x: (-x[1]["wickets"], x[0]))[:TOP_N]
        if a["wickets"] > 0
    ]
    # Player-of-the-match awards within the edition. The closest thing this data
    # holds to a player of the tournament, and named for what it is rather than
    # presented as that award - which is a selection panel's decision, not a
    # count.
    top_awards = [
        EditionLeader(
            player_identifier=pid,
            player_name=names.get(pid, pid),
            country_code=codes.get(pid),
            matches=agg.get(pid, {}).get("matches", 0),
            runs=agg.get(pid, {}).get("runs"),
            wickets=agg.get(pid, {}).get("wickets"),
            awards=n,
        )
        for pid, n in sorted(awards.items(), key=lambda x: (-x[1], x[0]))[:5]
        if n > 0
    ]
    return scorers, takers, top_awards


def build(
    db: Session,
    *,
    tournament_name: str,
    tournament_slug: str,
    season: str | None,
    gender: str,
    competition_key: str,
    competition_name: str,
    match_ids: set[str],
) -> EditionDetail | None:
    """Everything one edition page shows. `match_ids` come from `tournaments.py`."""
    if not match_ids:
        return None
    ids = sorted(match_ids)

    matches: list[Match] = []
    for chunk in _chunks(ids):
        matches += list(
            db.execute(select(Match).where(Match.match_id.in_(chunk))).scalars()
        )
    if not matches:
        return None
    matches.sort(key=lambda m: (m.match_date_start or "", m.match_id))

    # Codes come from the flag resolver so a tournament page marks sides the
    # same way every other page does. `team_type` is passed because a franchise
    # must not resolve to a country even when its city sits plainly inside one.
    team_names: dict[int, str] = {}
    team_codes: dict[int, str | None] = {}
    for team in db.execute(select(Team)).scalars():
        team_names[team.team_id] = team.name
        team_codes[team.team_id] = flags.country_code(team.name, team.team_type)

    innings = _team_innings(
        db, ids, {m.match_id: m.overs_limit for m in matches}
    )

    # Player-of-the-match is stored as a NAME, not an identifier, so it needs
    # resolving against the register before it can be linked or counted.
    people = list(db.execute(select(Player)).scalars())
    names = {p.identifier: preferred_name(p.name, p.display_name) for p in people}
    codes: dict[str, str | None] = {}
    by_scorecard = {p.name: p.identifier for p in people}
    by_display = {p.display_name: p.identifier for p in people if p.display_name}

    awards: dict[str, int] = defaultdict(int)
    potm_identifier: dict[str, str | None] = {}
    for match in matches:
        raw = match.player_of_match
        if not raw:
            potm_identifier[match.match_id] = None
            continue
        pid = by_scorecard.get(raw) or by_display.get(raw)
        potm_identifier[match.match_id] = pid
        if pid:
            awards[pid] += 1

    # Country per player, from their appearances, the same rule every other
    # board uses. Deliberately not `players.nationality`, which records Chris
    # Gayle as Australian.
    country_map = queries_mod._player_country_map(db, gender)
    for pid in names:
        codes[pid] = country_map.get(pid, (None, None))[1]

    standings, caveats = _standings(db, matches, team_names, team_codes, innings)
    scorers, takers, top_awards = _leaders(db, ids, names, codes, awards)

    final = next((m for m in matches if m.event_stage == "Final"), None)
    champion_id = runner_up = None
    tiebreak = False
    if final is not None:
        champion_id = final.winner_team_id or final.eliminator_team_id
        tiebreak = final.winner_team_id is None and final.eliminator_team_id is not None
        if champion_id:
            other = final.team2_id if champion_id == final.team1_id else final.team1_id
            runner_up = team_names.get(other)

    fixtures = [
        EditionMatch(
            match_id=m.match_id,
            match_date=m.match_date_start,
            stage=m.event_stage,
            group=m.event_group,
            venue=m.venue,
            city=m.city,
            team1_id=m.team1_id,
            team1_name=team_names.get(m.team1_id) if m.team1_id else None,
            team1_code=team_codes.get(m.team1_id) if m.team1_id else None,
            team2_id=m.team2_id,
            team2_name=team_names.get(m.team2_id) if m.team2_id else None,
            team2_code=team_codes.get(m.team2_id) if m.team2_id else None,
            winner_team_id=m.winner_team_id,
            winner_name=team_names.get(m.winner_team_id) if m.winner_team_id else None,
            eliminator_name=(
                team_names.get(m.eliminator_team_id) if m.eliminator_team_id else None
            ),
            outcome_result=m.outcome_result,
            win_by_runs=m.win_by_runs,
            win_by_wickets=m.win_by_wickets,
            result_text=_result_text(
                m,
                team_names,
                team_names.get(m.winner_team_id) if m.winner_team_id else None,
                team_names.get(m.eliminator_team_id) if m.eliminator_team_id else None,
            ),
            player_of_match=(
                names.get(potm_identifier[m.match_id], m.player_of_match)
                if potm_identifier.get(m.match_id)
                else m.player_of_match
            ),
            player_of_match_scorecard=m.player_of_match,
            player_of_match_identifier=potm_identifier.get(m.match_id),
            team1_score=_score_text(innings.get((m.match_id, m.team1_id))) if m.team1_id else None,
            team2_score=_score_text(innings.get((m.match_id, m.team2_id))) if m.team2_id else None,
        )
        for m in matches
    ]

    dates = sorted(m.match_date_start for m in matches if m.match_date_start)
    sides = {m.team1_id for m in matches if m.team1_id} | {
        m.team2_id for m in matches if m.team2_id
    }
    groups = sorted({m.event_group for m in matches if m.event_group})

    notes: list[str] = [
        "This table and these leaderboards are computed from the matches this "
        "dataset holds for the edition, which is not always all of them. They "
        "are a floor, not the published figures.",
    ]

    # A round-robin group gives every side the same number of matches, so an
    # uneven `played` column is proof that matches are missing rather than a
    # guess about it. This is what turns the coverage note above from a
    # disclaimer into a measurement: the 2019 World Cup group table comes out
    # with sides on 6 to 8 played where all ten played 9, because Cricsheet
    # holds 33 of the 45 group matches.
    by_group: dict[str | None, list[StandingsRow]] = defaultdict(list)
    for row in standings:
        by_group[row.group].append(row)
    uneven = [
        (group, min(r.played for r in rows_), max(r.played for r in rows_))
        for group, rows_ in by_group.items()
        if len(rows_) > 2 and min(r.played for r in rows_) != max(r.played for r in rows_)
    ]
    if uneven:
        detail = "; ".join(
            f"{'group ' + g if g else 'the group stage'}: {lo} to {hi} matches each"
            for g, lo, hi in uneven
        )
        notes.append(
            f"Sides in the same group have played different numbers of matches "
            f"({detail}). A round-robin gives everyone the same number, so this "
            f"is direct evidence that matches of this edition are missing from "
            f"the source - not a modelling choice. Points and net run rate are "
            f"correspondingly short of the published table."
        )
    without_ball_record = sum(
        1 for m in matches
        if (m.match_id, m.team1_id) not in innings and (m.match_id, m.team2_id) not in innings
    )
    if without_ball_record:
        notes.append(
            f"{without_ball_record} of {len(matches)} matches have no "
            f"ball-by-ball record, so they carry no score and contribute "
            f"nothing to net run rate. These are ICC-sourced stand-ins, which "
            f"hold a result and per-player figures but no deliveries."
        )
    # The single largest systematic gap in this dataset, and on an edition page
    # it changes the leaderboard rather than just the totals: Cricsheet has
    # withdrawn Afghanistan's entire ball-by-ball record in protest at the ICC's
    # treatment of Afghan women's cricket, so no Afghanistan player appears at
    # all. At the 2024 men's T20 World Cup that removes the edition's actual
    # leading run-scorer (Rahmanullah Gurbaz, 281) and a joint leading
    # wicket-taker (Fazalhaq Farooqi, 17) - which without this note reads as
    # this dataset simply disagreeing with every published source.
    #
    # Men's only: Afghanistan have never played women's international cricket,
    # so saying they are missing from a women's edition would be false.
    side_names = {team_names.get(t) for t in sides}
    if (
        gender == "male"
        and "Afghanistan" not in side_names
        and dates
        and dates[-1] >= AFGHANISTAN_QUALIFIED_FROM
    ):
        notes.append(
            "Afghanistan does not appear in this edition. Cricsheet has "
            "withdrawn their entire ball-by-ball record in protest at the ICC's "
            "treatment of Afghan women's cricket, so their matches are absent "
            "from the source rather than missing from this ingestion. Where they "
            "competed, the leading run-scorer and wicket-taker here can differ "
            "from the published ones for that reason alone."
        )

    missing_potm = sum(1 for m in matches if not m.player_of_match)
    if missing_potm:
        notes.append(
            f"No player of the match recorded for {missing_potm} of "
            f"{len(matches)} matches."
        )

    return EditionDetail(
        tournament_name=tournament_name,
        tournament_slug=tournament_slug,
        season=season,
        gender=gender,
        competition_key=competition_key,
        competition_name=competition_name,
        matches=len(matches),
        sides=len(sides),
        first_date=dates[0] if dates else None,
        last_date=dates[-1] if dates else None,
        champion_team_id=champion_id,
        champion_name=team_names.get(champion_id) if champion_id else None,
        runner_up_name=runner_up,
        has_final=final is not None,
        decided_by_tiebreak=tiebreak,
        final_match_id=final.match_id if final is not None else None,
        venues=sorted({m.venue for m in matches if m.venue}),
        groups=groups,
        standings=standings,
        fixtures=fixtures,
        top_run_scorers=scorers,
        top_wicket_takers=takers,
        most_awards=top_awards,
        standings_caveats=caveats,
        notes=notes,
    )


__all__ = ["build", "EditionDetail", "StandingsRow", "EditionMatch", "EditionLeader"]
