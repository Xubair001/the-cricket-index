"""Tunable constants for the analytics layer.

Every threshold and weight the analytics layer applies lives here, not inline at
its point of use. This is what makes the methodology configurable rather than
merely documented: changing how "in form" is defined is a change to this file,
and nothing downstream -- API, UI, or explanation text -- needs to know.

Nothing in here is a cricket fact. The cricket facts (what a par strike rate is,
what a wicket is worth) are *measured from the dataset* in `impact.py`, because
they differ by format, by gender, and by era, and hardcoding them would bake in
whichever competition happened to be in mind when the line was written.
"""

# --------------------------------------------------------------------------
# Form windows
# --------------------------------------------------------------------------

# The recent window the form verdict is based on, when the caller doesn't say.
DEFAULT_RECENT_MATCHES = 10

# How far back the player's own baseline is drawn from. The baseline is what
# recent form is measured *against*, so it must be long enough to represent the
# player's normal level rather than another streak.
DEFAULT_BASELINE_DAYS = 365

# The baseline deliberately EXCLUDES the matches in the recent window. Including
# them dilutes the comparison towards zero -- for a player with 12 matches in a
# year, a 10-match recent window would be 83% of its own baseline and could
# never register as a change. "Above their baseline" therefore means above the
# level they were at *before* this run of form.
BASELINE_EXCLUDES_RECENT = True

# Below these counts the comparison is noise. The verdict becomes
# "insufficient data" rather than a confident-looking classification drawn
# from three innings.
MIN_RECENT_MATCHES = 3
MIN_BASELINE_MATCHES = 5

# --------------------------------------------------------------------------
# Form classification
# --------------------------------------------------------------------------

# Match-level impact is heavily right-skewed -- most innings are small and a few
# are enormous -- so the mean of a short recent window is a noisy estimate of a
# player's true current level, and noise alone would push players into the
# extreme bands. The recent mean is therefore shrunk towards the baseline as if
# the player had this many additional matches at their established level. A
# 10-match window with K=6 keeps 10/16 of the observed move; a 30-match window
# keeps 30/36 and is trusted almost fully.
FORM_SHRINKAGE_MATCHES = 6

# Change in mean per-match impact versus baseline, as a proportion. Ordered
# best-first; the first band whose threshold is met wins.
#
# CALIBRATED, NOT CHOSEN. These come from the observed distribution of shrunk
# deltas across every player with 20+ matches (see scripts/calibrate_form.py),
# targeting roughly 15/15/40/15/15 across the five bands. They are asymmetric
# because the distribution is: a short window of a right-skewed variable sits
# below the long-run mean more often than above it, so a symmetric band would
# report a permanent majority as declining. Re-run the script after a
# significant change to the impact model or a large ingest.
FORM_BANDS: list[tuple[str, float]] = [
    ("in_form", 0.41),
    ("improving", 0.11),
    ("stable", -0.24),
    ("declining", -0.36),
    ("out_of_form", float("-inf")),
]

FORM_LABELS = {
    "in_form": "In Form",
    "improving": "Improving",
    "stable": "Stable",
    "declining": "Declining",
    "out_of_form": "Out of Form",
    "insufficient_data": "Not enough recent cricket",
}

# A percentage change against a baseline near zero is meaningless -- a player
# averaging 0.04 of a par performance who moves to 0.2 is "+400%" and has done
# nothing of note. Below this baseline magnitude the verdict is banded on the
# absolute move instead, and confidence is capped.
#
# In normalized units, where 1.0 is a par appearance in that competition, so
# this is "a quarter of what a typical appearance is worth".
MIN_MEANINGFUL_BASELINE = 0.25

# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------

# Sample sizes at which the recent window and the baseline are each considered
# fully informative. Below them, confidence scales down linearly. Confidence is
# reported alongside every verdict because a classification drawn from four
# innings and one from forty must not look alike in the UI.
CONFIDENCE_FULL_RECENT = 10
CONFIDENCE_FULL_BASELINE = 20

# Applied when the baseline is too small in magnitude for a ratio to mean much.
LOW_BASELINE_CONFIDENCE_CAP = 0.45

# --------------------------------------------------------------------------
# Impact scoring
# --------------------------------------------------------------------------

# Par figures are measured per (competition, gender) from the dataset, but a
# thin slice -- a competition with almost no cricket in it -- gives an unstable
# par. Below this many balls the competition falls back to the global par for
# its gender.
MIN_BALLS_FOR_PAR = 20_000

# A batter's impact combines volume (runs) and efficiency (runs above the rate a
# par batter would have scored off the same balls). Weighting is explicit so the
# trade-off between "scored a lot" and "scored quickly" is a decision, not an
# accident of the formula.
BATTING_VOLUME_WEIGHT = 1.0
BATTING_EFFICIENCY_WEIGHT = 1.0

# Bowling impact combines wickets (valued at what a wicket costs on average in
# that competition) and runs saved against par economy.
BOWLING_WICKET_WEIGHT = 1.0
BOWLING_ECONOMY_WEIGHT = 1.0

# --------------------------------------------------------------------------
# Discipline (crude playing role)
# --------------------------------------------------------------------------

# §5 puts "playing role" in Tier C because wicketkeeper and opener cannot be
# inferred from anything this dataset holds. It also says explicitly that a
# crude batter / bowler / all-rounder split *can* be inferred from balls faced
# versus balls bowled -- and that split is what stops a specialist batter
# appearing in a bowling leaderboard.
#
# The measure is a player's share of their own deliveries spent bowling:
#
#     bowling_share = balls_bowled / (balls_faced + balls_bowled)
#
# A volume floor alone does NOT do this job. Over a long career a top-order
# batter's occasional overs still clear any sane minimum: Virat Kohli has bowled
# 989 balls and Sachin Tendulkar 2,812, so both qualified for a bowling board
# that gated only on volume.
#
# THRESHOLDS ARE READ OFF THE DISTRIBUTION, not chosen. Over the 1,782 men's
# internationals with 20+ matches the share runs 0.00 at the 5th percentile to
# 0.94 at the 95th, and these two cuts sit either side of the crowded middle.
# They classify every well-known player correctly:
#   batter      Kohli .03  Rohit .04  Smith .09  Williamson .11  Root .19
#   all-rounder Maxwell .50  Stokes .52  Shakib .62  Flintoff .66  Afridi .76
#   bowler      Ashwin .83  Starc .85  Anderson .93  Bumrah .94  Muralitharan .96
#
# The middle band is deliberately WIDE. The error that matters is excluding a
# genuine all-rounder from a list they belong on; including a marginal one is
# cheap by comparison, so the cuts are permissive rather than tight.
BATTER_MAX_BOWLING_SHARE = 0.25
BOWLER_MIN_BOWLING_SHARE = 0.78

# --------------------------------------------------------------------------
# Match phases
# --------------------------------------------------------------------------

# Powerplay / middle / death, as (first_over, last_over) inclusive, 0-based.
#
# Per competition, because the phases are a property of the FORMAT, not of
# cricket: a T20 powerplay is six overs and an ODI's is ten. Applying one
# format's bands to another invents a split nobody plays to.
#
# Tests are deliberately ABSENT rather than given bands. There is no powerplay
# in a Test and no death overs; an innings ends when ten wickets fall or a
# captain declares. Slicing over 0-5 of a Test innings and calling it a
# powerplay would produce a figure that looks like the T20 one and means
# something entirely different. `phase_bands()` returns None for Tests and the
# API says the split does not apply, which is the honest answer.
PHASE_BANDS: dict[str, list[tuple[str, str, int, int]]] = {
    "t20is": [
        ("powerplay", "Powerplay (1-6)", 0, 5),
        ("middle", "Middle (7-16)", 6, 15),
        ("death", "Death (17-20)", 16, 99),
    ],
    "psl": [
        ("powerplay", "Powerplay (1-6)", 0, 5),
        ("middle", "Middle (7-16)", 6, 15),
        ("death", "Death (17-20)", 16, 99),
    ],
    "odis": [
        ("powerplay", "Powerplay (1-10)", 0, 9),
        ("middle", "Middle (11-40)", 10, 39),
        ("death", "Death (41-50)", 40, 99),
    ],
}

# --------------------------------------------------------------------------
# Opposition strength
# --------------------------------------------------------------------------

# Whether performances are scaled by the strength of the side they came
# against. Off, the form board ranks by weakness of opposition: a player whose
# recent cricket was against Norway, Portugal and Malta outranks one facing
# Australia and England, having done nothing harder. See `opposition.py`.
OPPOSITION_ADJUSTMENT_ENABLED = True

# A side's concession index is measured as its opponents' share of the impact in
# their shared matches, then pulled towards 1.0 (no adjustment) as though the
# side had this many extra matches at an exactly even split. Thin sides get
# almost no adjustment, which is the right default: absent evidence, assume
# average opposition rather than invent a correction.
OPPOSITION_SHRINKAGE_ROWS = 30

# Below this many matches, a (side, competition) slice doesn't get its own index
# and falls back to the side's figure across all competitions.
OPPOSITION_MIN_MATCHES_FOR_SLICE = 20

# Bradley-Terry is fitted per era, not once over the whole archive, because team
# strength moves materially across 25 years. Measured on own-share of match
# output: Bangladesh runs 0.387 in the early 2000s to 0.505 in the mid-2020s,
# Australia 0.570 down to 0.488. Bangladesh's swing alone is wider than the gap
# between many pairs of teams, so a single career rating credits a 2003 century
# against them exactly as much as a 2025 one -- which is what §14 means when it
# asks for opponent standing "at the time".
#
# Five years is a compromise: long enough that most sides have a usable fixture
# list inside a bucket, short enough to track a side rebuilding. Eras that are
# thin for a given side are shrunk towards that side's all-era figure, so a
# bucket with three matches in it contributes almost nothing.
OPPOSITION_ERA_YEARS = 5

# The stable core an era's reference is measured against: sides with this much
# volume in at least this many eras. Without it the 2019 expansion of T20I status
# to every ICC member drags each era's average opponent down and inflates every
# established side in the 2020s. See the note in `opposition.table`.
OPPOSITION_CORE_MIN_MATCHES_PER_ERA = 20
OPPOSITION_CORE_MIN_ERAS = 4

# How strongly an era's own fit is trusted against the side's all-era fit.
# Same empirical-Bayes shape as everywhere else in this layer.
OPPOSITION_ERA_SHRINKAGE_MATCHES = 20

# MM iterations for the Bradley-Terry fit. It converges monotonically and this
# many rounds is comfortably past the point where the powers stop moving.
OPPOSITION_FIT_ITERATIONS = 60

# Hard bounds on the multiplier. Even after shrinkage the tails are not to be
# trusted far enough to halve or double a performance.
OPPOSITION_MULTIPLIER_BOUNDS = (0.55, 1.60)

# --------------------------------------------------------------------------
# Performance Index
# --------------------------------------------------------------------------

# §14's weights, and which components are live in Phase 1, are declared in
# `performance_index.COMPONENTS` -- they belong beside the code that renormalises
# them. These two are the shape of the window that Index is measured over.

# How much recent cricket the Index is computed from. Longer than the form
# engine's 10-match window: form is asking "what changed", which wants a short
# window, while a rating is asking "how good are they", which wants the most
# evidence it can get that is still recent.
INDEX_WINDOW_MATCHES = 15

# Below this, the percentile of a component says more about sample size than
# about the player, so they are left off the board rather than rated badly.
INDEX_MIN_MATCHES = 8

# The situation component compares a player chasing with the same player
# batting first. Both sides need this many dismissals before the ratio is used
# at all, and it is then shrunk towards 1.0 on the thinner side.
#
# MEASURED, not chosen. Over men's internationals, at a 5-dismissal floor the
# ratio reached 14.19 -- nobody chases fourteen times better -- with a p10-p90
# spread of 0.55 to 1.77. At 10 the spread is 0.65 to 1.50 and 1,004 players
# still qualify, which is signal rather than sample size.
INDEX_SITUATION_MIN_DISMISSALS = 10
INDEX_SITUATION_SHRINKAGE = 10

# --------------------------------------------------------------------------
# Selection (Best XI / XV)
# --------------------------------------------------------------------------

# Identifying a wicketkeeper from dismissal credits.
#
# A STUMPING IS THE ONLY DEFINITIVE MARKER, and it is required. Catches were
# tried as a corroborating signal and are not one: they cannot be told apart
# from outfield catches, so any long-serving fielder clears a catch threshold.
# At 25 catches the selector picked Mohammad Hafeez -- an off-spinning
# all-rounder who has never kept -- as a PSL wicketkeeper, alongside Babar Azam
# on 58 catches and no stumpings.
#
# Catches still RANK confirmed keepers against each other, since among players
# who demonstrably keep, the one with more dismissals kept more often.
KEEPER_STUMPING_WEIGHT = 10
KEEPER_MIN_STUMPINGS = 1

# How often a player must have been one of the two batters on the first ball of
# an innings before they are called an opener.
OPENER_MIN_INNINGS = 5

# What a "best" side is scored on. All three are 0-100 within the scope, so the
# weights are directly comparable.
#
# CAREER STANDING DOMINATES, and it has to. The Performance Index measures a
# player's last 15 matches, so scoring on the Index plus form is recency counted
# twice with career record counted not at all -- which picked a PSL XI without
# Mohammad Rizwan (102 PSL matches, index 41 on a poor recent window) or Babar
# Azam. "Best XI" has to mean more than "hottest XI", while still moving for a
# player who is badly out of touch.
SELECTION_WEIGHTS = {
    "career": 0.55,   # whole record in this scope, opposition-adjusted
    "index": 0.30,    # Performance Index -- recent quality
    "form": 0.15,     # change against their own baseline
}

# --------------------------------------------------------------------------
# Form leaderboards
# --------------------------------------------------------------------------

# A form board only means anything for players who are still playing. Measured
# against the newest match in the dataset, not today.
LEADERBOARD_ACTIVE_WINDOW_DAYS = 540

# Verdicts below this confidence are left off the board entirely. Without it the
# top and bottom of a form table are populated by whoever has the fewest
# matches, since that is where the noise lives -- the board would rank sample
# size, not form.
LEADERBOARD_MIN_CONFIDENCE = 0.5
