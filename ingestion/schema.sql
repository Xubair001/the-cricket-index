-- Men's and women's cricket are kept structurally separate, not just
-- UI-filtered: gender lives on teams, competitions, players, and matches,
-- and a team name alone is never a unique identity (men's and women's
-- "Pakistan" are different rows).

CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female')),
    team_type TEXT NOT NULL CHECK (team_type IN ('international', 'franchise')),
    UNIQUE (name, gender, team_type)
);

-- A format/tournament concept (Test, ODI, T20I, PSL, ...). Gendered because
-- participation, teams, and seasons differ by gender even for the same
-- format -- "Men's Test" and "Women's Test" are tracked as distinct
-- competitions so browsing/filtering never needs a cross-gender join.
CREATE TABLE IF NOT EXISTS competitions (
    competition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,               -- 'test' | 'odi' | 't20i' | 'psl' | ...
    display_name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('international', 'domestic_league')),
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female')),
    UNIQUE (key, gender)
);

-- General-purpose grouping under a competition (a Test "season" like
-- "2016/17", or a numbered league season like "PSL 2024"). Applies to any
-- competition, not just leagues, so future competitions need no schema
-- change to gain season grouping.
CREATE TABLE IF NOT EXISTS seasons (
    season_id INTEGER PRIMARY KEY AUTOINCREMENT,
    competition_id INTEGER NOT NULL REFERENCES competitions(competition_id),
    label TEXT NOT NULL,
    UNIQUE (competition_id, label)
);

CREATE TABLE IF NOT EXISTS players (
    identifier TEXT PRIMARY KEY,      -- Cricsheet registry ID, e.g. "18e6906e"
    name TEXT NOT NULL,
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female')),
    -- Bio fields are nullable by design: Cricsheet has none of this. Populated
    -- in a later phase from Wikidata (DOB/birthplace/nationality only -- style
    -- and playing role aren't reliably available there and are left null).
    date_of_birth TEXT,
    birth_place TEXT,
    nationality TEXT,
    cricinfo_id TEXT,                 -- crosswalk key for Wikidata's P2697
    bio_source TEXT,                  -- e.g. 'wikidata'; null until enriched
    -- Career-end signals. Both are sourced, never inferred: Wikidata's P570
    -- (death) and P2032 (work period end). P2032 is almost unpopulated for
    -- cricketers (21 of ~31,700 have it), so most players will have neither,
    -- and the API reports them as active/inactive from their last appearance
    -- rather than claiming a retirement that no source backs.
    date_of_death TEXT,
    retirement_date TEXT,
    -- Cricsheet's `name` follows the standard scorecard convention: all
    -- initials then surname ("JE Root" = Joseph Edward Root). That's correct,
    -- not stale -- Wisden, CricketArchive and ESPNcricinfo's own scorecard
    -- guidelines use it. It just isn't how a reader says the name, so the
    -- Wikidata label is stored alongside it for display. Nullable: only ~43%
    -- of players resolve in Wikidata, and the rest keep the scorecard form
    -- rather than getting a fabricated "full" name.
    display_name TEXT,
    image_url TEXT                    -- Wikimedia Commons (P18); freely licensed
);

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    competition_id INTEGER NOT NULL REFERENCES competitions(competition_id),
    season_id INTEGER REFERENCES seasons(season_id),
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female')),  -- denormalized for fast filtering without a join
    -- 'full': per-player performance available (player_match_stats populated).
    -- 'result_only': result/metadata known but no per-player breakdown -- the
    -- shape a future pre-2001 Wikipedia-sourced match would have. Nothing
    -- produces 'result_only' yet; the column exists so that phase doesn't
    -- require another migration.
    data_granularity TEXT NOT NULL DEFAULT 'full' CHECK (data_granularity IN ('full', 'result_only')),
    content_hash TEXT,                -- sha256 of the raw source JSON, for change detection; null for non-Cricsheet sources
    match_type TEXT,
    team_type TEXT,
    season_label TEXT,                 -- denormalized display copy of seasons.label
    event_name TEXT,
    match_number INTEGER,
    venue TEXT,
    city TEXT,
    match_date_start TEXT,
    match_date_end TEXT,
    overs_limit INTEGER,
    team1_id INTEGER REFERENCES teams(team_id),
    team2_id INTEGER REFERENCES teams(team_id),
    toss_winner_team_id INTEGER REFERENCES teams(team_id),
    toss_decision TEXT,
    winner_team_id INTEGER REFERENCES teams(team_id),
    win_by_runs INTEGER,
    win_by_wickets INTEGER,
    outcome_result TEXT,              -- e.g. 'tie', 'no result', 'draw'; null if decisive
    player_of_match TEXT
);

-- Who played in which match for which team, plus their batting/bowling
-- contribution for that match. These figures are derived in-memory from the
-- source ball-by-ball data at ingestion time, but the balls themselves are
-- never persisted. Only populated for data_granularity = 'full' matches.
CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id TEXT NOT NULL REFERENCES matches(match_id),
    player_identifier TEXT REFERENCES players(identifier),
    player_name TEXT NOT NULL,
    team_id INTEGER NOT NULL REFERENCES teams(team_id),
    runs_scored INTEGER NOT NULL DEFAULT 0,
    balls_faced INTEGER NOT NULL DEFAULT 0,
    fours INTEGER NOT NULL DEFAULT 0,
    sixes INTEGER NOT NULL DEFAULT 0,
    dismissals INTEGER NOT NULL DEFAULT 0,  -- times out in this match (Tests can have 2 innings/side); needed for a correct batting average
    wickets_taken INTEGER NOT NULL DEFAULT 0,
    balls_bowled INTEGER NOT NULL DEFAULT 0,
    runs_conceded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, player_name)
);

-- Aggregate-only career figures for a player/competition where we don't
-- (or can't) have per-match rows -- e.g. a future pre-2001 Wikipedia-sourced
-- player. Not populated yet. A player's true career total is: SUM over
-- player_match_stats (their 'full'-granularity matches) + any row here.
CREATE TABLE IF NOT EXISTS player_career_totals (
    player_identifier TEXT NOT NULL REFERENCES players(identifier),
    competition_id INTEGER NOT NULL REFERENCES competitions(competition_id),
    source TEXT NOT NULL,             -- e.g. 'wikipedia'
    matches INTEGER NOT NULL DEFAULT 0,
    runs_scored INTEGER NOT NULL DEFAULT 0,
    balls_faced INTEGER NOT NULL DEFAULT 0,
    dismissals INTEGER NOT NULL DEFAULT 0,
    wickets_taken INTEGER NOT NULL DEFAULT 0,
    balls_bowled INTEGER NOT NULL DEFAULT 0,
    runs_conceded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_identifier, competition_id)
);

-- Purely an internal observability aid (not read by the API/UI), so it's
-- intentionally kept at archive granularity rather than trying to attribute
-- counts per gender mid-batch from a source that mixes both in one file.
CREATE TABLE IF NOT EXISTS ingestion_progress (
    competition_key TEXT PRIMARY KEY,
    total_matches INTEGER NOT NULL,
    processed_matches INTEGER NOT NULL DEFAULT 0,
    skipped_matches INTEGER NOT NULL DEFAULT 0,
    failed_matches INTEGER NOT NULL DEFAULT 0
);

-- Official ICC rankings, fetched daily from ICC's own feed. Kept entirely
-- separate from the Cricsheet-derived tables: these are ICC's published
-- ratings, not anything this project computes, and the two must never be
-- conflated. Rows are keyed by (rank_type, rank_date, position) so each
-- publication is retained as a snapshot -- that history is what makes a
-- player's rank trend chartable.
--
-- player_identifier is a best-effort link back to a Cricsheet player and is
-- deliberately nullable: ICC names people as "Travis Head" where Cricsheet
-- says "TM Head", and near-collisions exist ("HC Brook"/"SSJ Brooks"). An
-- entry that can't be matched confidently stays unlinked rather than being
-- attached to the wrong person.
CREATE TABLE IF NOT EXISTS icc_player_rankings (
    rank_type TEXT NOT NULL,          -- e.g. 'test-batting', 't20w-bowling'
    rank_date TEXT NOT NULL,          -- ICC's own publication date
    position INTEGER NOT NULL,
    icc_player_id TEXT,
    player_name TEXT NOT NULL,        -- as ICC spells it
    country TEXT,
    points INTEGER,
    career_best TEXT,
    player_identifier TEXT REFERENCES players(identifier),
    fetched_at TEXT NOT NULL,
    -- player_name is part of the key because ICC ties share a position: the
    -- top 100 Test batters routinely occupy fewer than 100 distinct ranks.
    PRIMARY KEY (rank_type, rank_date, position, player_name)
);

-- Fixtures from ICC's schedule feed: completed, live and upcoming matches.
--
-- Kept separate from `matches` on purpose. `matches` holds Cricsheet records
-- with per-player figures derived from ball-by-ball; a fixture is a calendar
-- entry with a scoreline, and an upcoming one has no result at all. Merging
-- them would put rows into `matches` that every aggregate query would then
-- have to learn to exclude.
--
-- content_hash is the SHA-256 of the raw feed object, so a daily re-run
-- rewrites only genuinely changed fixtures instead of every row.
CREATE TABLE IF NOT EXISTS fixtures (
    icc_match_id TEXT PRIMARY KEY,
    series_id TEXT,
    series_name TEXT,
    tour_name TEXT,
    comp_type TEXT,                   -- e.g. 'ODI International - w'
    match_type TEXT,                  -- 'Test' | 'ODI' | 'T20' | 'Youth ODI' | ...
    gender TEXT CHECK (gender IN ('male', 'female')),
    match_number TEXT,
    match_status TEXT,
    is_upcoming INTEGER NOT NULL DEFAULT 0,
    is_live INTEGER NOT NULL DEFAULT 0,
    start_date TEXT,                  -- ISO; the feed ships US M/D/YYYY
    end_date TEXT,
    start_time_gmt TEXT,
    venue TEXT,
    country TEXT,
    team_a_name TEXT,
    team_a_short TEXT,
    team_b_name TEXT,
    team_b_short TEXT,
    team_a_id INTEGER REFERENCES teams(team_id),   -- nullable link to our teams
    team_b_id INTEGER REFERENCES teams(team_id),
    match_result TEXT,
    winning_team_name TEXT,
    toss_won_by TEXT,
    toss_elected_to TEXT,
    content_hash TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS icc_team_rankings (
    rank_type TEXT NOT NULL,          -- e.g. 'test-team', 'odiw-team'
    rank_date TEXT NOT NULL,
    position INTEGER NOT NULL,
    icc_team_id TEXT,
    team_name TEXT NOT NULL,
    points INTEGER,
    team_id INTEGER REFERENCES teams(team_id),   -- nullable, same caution
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (rank_type, rank_date, position, team_name)
);

-- Indexes are here because a query plan asked for them, not by guesswork.
-- Each one below names the read path it serves; if a path stops existing, the
-- index should go with it. Every extra index is paid for on every write, and
-- ingestion writes ~221k player_match_stats rows.

-- matches ------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_matches_competition ON matches(competition_id);
-- Date alone, NOT (gender, match_date_start). Measured interleaved so page
-- cache can't flatter either arm:
--   * (gender, date) makes the ordered browse 0.18ms vs 2.92ms, but the planner
--     then also picks it for the big player aggregate and reorders that join
--     badly -- 712ms against 293ms. A 2.7ms saving for a 419ms cost.
--   * date alone gives the same browse win (0.33ms vs 4.45ms) with no effect on
--     the aggregate, because there's no gender prefix to tempt the planner.
-- A bare matches.gender index is simply inert here: gender='male' selects 73%
-- of the table, so the planner ignores it. Left out rather than paid for on
-- every write. Re-measure before adding any gender-prefixed index back.
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date_start);
CREATE INDEX IF NOT EXISTS idx_matches_team1 ON matches(team1_id);
CREATE INDEX IF NOT EXISTS idx_matches_team2 ON matches(team2_id);
-- Without this, counting a team's wins is a full scan of matches -- and the
-- teams list asked for that once per team (110 scans of 10k rows per request).
CREATE INDEX IF NOT EXISTS idx_matches_winner ON matches(winner_team_id);

-- player_match_stats -------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_player_match_stats_player_name ON player_match_stats(player_name);
-- (player_identifier, match_id): the aggregates group by identifier and take
-- COUNT(DISTINCT match_id), so carrying match_id in the index lets that run off
-- the index. Subsumes a bare player_identifier index for prefix lookups.
CREATE INDEX IF NOT EXISTS idx_player_match_stats_identifier_match
    ON player_match_stats(player_identifier, match_id);
-- Team pages scope the same aggregates to one team.
CREATE INDEX IF NOT EXISTS idx_player_match_stats_team_player
    ON player_match_stats(team_id, player_identifier);

-- players ------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_players_gender ON players(gender);
CREATE INDEX IF NOT EXISTS idx_players_cricinfo ON players(cricinfo_id);

-- icc + fixtures -----------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_icc_player_rankings_type_date ON icc_player_rankings(rank_type, rank_date);
CREATE INDEX IF NOT EXISTS idx_icc_player_rankings_player ON icc_player_rankings(player_identifier);
CREATE INDEX IF NOT EXISTS idx_icc_team_rankings_type_date ON icc_team_rankings(rank_type, rank_date);
CREATE INDEX IF NOT EXISTS idx_fixtures_start ON fixtures(start_date);
-- Matches the fixtures list query's filter order exactly.
CREATE INDEX IF NOT EXISTS idx_fixtures_gender_window ON fixtures(gender, is_upcoming, start_date);
CREATE INDEX IF NOT EXISTS idx_fixtures_live ON fixtures(is_live, start_date);
