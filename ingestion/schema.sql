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
    bio_source TEXT                   -- e.g. 'wikidata'; null until enriched
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

CREATE INDEX IF NOT EXISTS idx_matches_competition ON matches(competition_id);
CREATE INDEX IF NOT EXISTS idx_matches_gender ON matches(gender);
CREATE INDEX IF NOT EXISTS idx_matches_team1 ON matches(team1_id);
CREATE INDEX IF NOT EXISTS idx_matches_team2 ON matches(team2_id);
CREATE INDEX IF NOT EXISTS idx_player_match_stats_player_name ON player_match_stats(player_name);
CREATE INDEX IF NOT EXISTS idx_player_match_stats_identifier ON player_match_stats(player_identifier);
CREATE INDEX IF NOT EXISTS idx_player_match_stats_team ON player_match_stats(team_id);
CREATE INDEX IF NOT EXISTS idx_players_gender ON players(gender);
