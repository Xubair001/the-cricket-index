"""Pure parsing logic for a single Cricsheet match JSON blob.

Deliberately does not retain ball-by-ball data: we walk the innings/overs/
deliveries structure only to derive per-player aggregate figures (runs,
wickets, balls faced/bowled), then discard the raw balls. Kept free of any
I/O so it can be unit tested directly, independent of the activity/workflow
machinery around it.
"""
from dataclasses import dataclass, field

# Wicket kinds not credited to the bowler (run outs, retirements, code-of-conduct
# dismissals) vs. the rest, which are.
BOWLER_CREDITED_KINDS = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}

# "Retired hurt"/"retired not out" are not dismissals for batting-average purposes;
# every other wicket kind (including "retired out" and "timed out") is.
NOT_OUT_KINDS = {"retired hurt", "retired not out"}


@dataclass
class PlayerMatchStat:
    player_name: str
    team: str
    runs_scored: int = 0
    balls_faced: int = 0
    fours: int = 0
    sixes: int = 0
    # A count, not a bool: Test matches have up to two innings per side, so a
    # player can be dismissed twice in one match.
    dismissals: int = 0
    wickets_taken: int = 0
    balls_bowled: int = 0
    runs_conceded: int = 0


@dataclass
class Delivery:
    """One ball, kept whole.

    The aggregate stats above are derived from these, but the two are stored
    side by side rather than one from the other: §5's Tier B list -- phase
    splits, dot-ball rates, batting position, chasing -- all need the ball back,
    and re-deriving an aggregate from deliveries at read time would put a scan
    of ~4.9M rows on a page request (§28 forbids exactly that).
    """

    innings: int          # 1-based, so batting first vs chasing is readable
    seq: int              # 0-based within the innings; the stable sort key
    over: int             # 0-based, for powerplay / middle / death
    ball: int             # 1-based within the over, extras included
    batting_team: str
    batter: str | None
    bowler: str | None
    non_striker: str | None
    runs_batter: int = 0
    runs_extras: int = 0
    runs_total: int = 0
    non_boundary: bool = False
    wides: int = 0
    noballs: int = 0
    byes: int = 0
    legbyes: int = 0
    wicket_kind: str | None = None
    player_out: str | None = None


@dataclass
class ParsedMatch:
    match_id: str
    competition: str
    match_type: str | None
    gender: str | None
    team_type: str | None
    season: str | None
    event_name: str | None
    match_number: int | None
    venue: str | None
    city: str | None
    match_date_start: str | None
    match_date_end: str | None
    overs_limit: int | None
    team1: str | None
    team2: str | None
    toss_winner: str | None
    toss_decision: str | None
    winner: str | None
    win_by_runs: int | None
    win_by_wickets: int | None
    outcome_result: str | None
    player_of_match: str | None
    teams: list[str] = field(default_factory=list)
    players: dict[str, str] = field(default_factory=dict)  # name -> registry id
    player_match_stats: list[PlayerMatchStat] = field(default_factory=list)
    deliveries: list[Delivery] = field(default_factory=list)


def parse_match(match_id: str, competition: str, raw: dict) -> ParsedMatch:
    info = raw.get("info", {})
    teams = info.get("teams", [])
    outcome = info.get("outcome", {})
    dates = info.get("dates", [])
    event = info.get("event", {}) or {}
    registry = (info.get("registry") or {}).get("people", {})
    squads = info.get("players", {})  # team -> [player names]

    winner = outcome.get("winner")
    by = outcome.get("by", {}) or {}
    outcome_result = outcome.get("result")  # e.g. "tie", "no result"

    match = ParsedMatch(
        match_id=match_id,
        competition=competition,
        match_type=info.get("match_type"),
        gender=info.get("gender"),
        team_type=info.get("team_type"),
        season=str(info.get("season")) if info.get("season") is not None else None,
        event_name=event.get("name"),
        match_number=event.get("match_number"),
        venue=info.get("venue"),
        city=info.get("city"),
        match_date_start=dates[0] if dates else None,
        match_date_end=dates[-1] if dates else None,
        overs_limit=info.get("overs"),
        team1=teams[0] if len(teams) > 0 else None,
        team2=teams[1] if len(teams) > 1 else None,
        toss_winner=(info.get("toss") or {}).get("winner"),
        toss_decision=(info.get("toss") or {}).get("decision"),
        winner=winner,
        win_by_runs=by.get("runs"),
        win_by_wickets=by.get("wickets"),
        outcome_result=outcome_result,
        player_of_match=", ".join(info.get("player_of_match", [])) or None,
        teams=teams,
        players=registry,
    )

    # Seed every named player in the squads with a zero-stat row first, so
    # participants who never faced a ball or bowled (e.g. an unused
    # wicketkeeper) still show up as having played the match.
    stats: dict[str, PlayerMatchStat] = {}
    for team, names in squads.items():
        for name in names:
            stats[name] = PlayerMatchStat(player_name=name, team=team)

    deliveries: list[Delivery] = []

    # `innings` is 1-based and counts in the order Cricsheet lists them, which
    # IS the order they were played -- that is what makes chasing derivable.
    for innings_number, innings in enumerate(raw.get("innings", []), start=1):
        batting_team = innings.get("team")
        # Position within the innings, not within the over: a wide or no-ball
        # adds a delivery, so (over, ball) is not unique and cannot be a key.
        seq = 0
        for over in innings.get("overs", []):
            over_number = over.get("over", 0)
            for ball_number, delivery in enumerate(over.get("deliveries", []), start=1):
                runs = delivery.get("runs", {})
                extras = delivery.get("extras") or {}
                wickets = delivery.get("wickets") or []
                is_wide = "wides" in extras
                is_noball = "noballs" in extras
                batter_runs = runs.get("batter", 0)

                batter_name = delivery.get("batter")
                if batter_name in stats and not is_wide:
                    s = stats[batter_name]
                    s.runs_scored += batter_runs
                    s.balls_faced += 1
                    # A four is a BOUNDARY, not "the batter took four runs".
                    # Cricsheet marks all-run fours and overthrow-assisted ones
                    # with runs.non_boundary, precisely so the two can be told
                    # apart; counting on the run total alone overstates
                    # boundaries. Validated against published figures: Joe Root
                    # came out at 1,523 Test fours against ESPNcricinfo's 1,515,
                    # and the flag appears on real deliveries in the archives
                    # (10 of 14,557 four/six deliveries in the PSL set).
                    if not runs.get("non_boundary"):
                        if batter_runs == 4:
                            s.fours += 1
                        elif batter_runs == 6:
                            s.sixes += 1

                bowler_name = delivery.get("bowler")
                if bowler_name in stats:
                    s = stats[bowler_name]
                    if not is_wide and not is_noball:
                        s.balls_bowled += 1
                    # Byes/leg-byes aren't the bowler's fault and don't count
                    # against their figures; wides/no-balls (and any runs off
                    # the bat) do.
                    s.runs_conceded += (
                        batter_runs + extras.get("wides", 0) + extras.get("noballs", 0)
                    )
                    for wicket in wickets:
                        if wicket.get("kind") in BOWLER_CREDITED_KINDS:
                            s.wickets_taken += 1

                for wicket in wickets:
                    dismissed_name = wicket.get("player_out")
                    if dismissed_name in stats and wicket.get("kind") not in NOT_OUT_KINDS:
                        stats[dismissed_name].dismissals += 1

                # Only the first wicket on a ball is stored. Two dismissals off
                # one delivery is possible (a run out on a no-ball that is also
                # a stumping is not, but run-out plus retired is) and vanishingly
                # rare; the aggregate counters above still see every one.
                first_wicket = wickets[0] if wickets else {}
                deliveries.append(
                    Delivery(
                        innings=innings_number,
                        seq=seq,
                        over=over_number,
                        ball=ball_number,
                        batting_team=batting_team,
                        batter=batter_name,
                        bowler=bowler_name,
                        non_striker=delivery.get("non_striker"),
                        runs_batter=batter_runs,
                        runs_extras=runs.get("extras", 0),
                        runs_total=runs.get("total", 0),
                        non_boundary=bool(runs.get("non_boundary")),
                        wides=extras.get("wides", 0),
                        noballs=extras.get("noballs", 0),
                        byes=extras.get("byes", 0),
                        legbyes=extras.get("legbyes", 0),
                        wicket_kind=first_wicket.get("kind"),
                        player_out=first_wicket.get("player_out"),
                    )
                )
                seq += 1

    match.player_match_stats = list(stats.values())
    match.deliveries = deliveries
    return match
