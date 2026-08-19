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
    -- Cricsheet's event.stage and event.group. Both sparse (stage on ~5% of
    -- matches, group on ~11%), and both worth having anyway: stage is what
    -- names a Final, and without it a tournament's winner would have to be
    -- inferred from "the last match of the event", which is wrong wherever a
    -- third-place play-off follows the final or coverage is partial.
    event_stage TEXT,                 -- 'Final' | 'Semi Final' | 'Quarter Final' | ...
    event_group TEXT,                 -- 'A' | 'B' | '1' | ...; text, as Cricsheet types it both ways
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
    -- Who took a TIED match on a tiebreak: super over, boundary count, bowl-out.
    -- Cricsheet reports this as outcome.eliminator and NOT as outcome.winner,
    -- so a tied match has winner_team_id NULL however it was actually settled.
    -- The 2019 World Cup final is exactly this: {"result": "tie",
    -- "eliminator": "England"}. England won that World Cup, and a tournament
    -- page reading only winner_team_id would show its final as won by nobody.
    -- Kept SEPARATE from winner_team_id rather than folded into it, because
    -- the two are different facts: one side did not win the match, they won
    -- the tiebreak, and every existing aggregate that counts wins is right to
    -- keep excluding it.
    eliminator_team_id INTEGER REFERENCES teams(team_id),
    player_of_match TEXT,
    -- Which feed this match's figures came from.
    --
    -- 'cricsheet' is the default and the only one that carries ball-by-ball,
    -- so only those matches have `deliveries` rows and only they can appear in
    -- the phase/splits analytics.
    --
    -- 'icc' rows come from ICC's per-match scorecard endpoint. They exist for
    -- two reasons: Cricsheet publishes in bulk every few days, so recent
    -- matches would otherwise be missing entirely; and Cricsheet has withheld
    -- ALL Afghanistan matches since 2024-11-14 in protest at the ICC's
    -- treatment of Afghan women's cricket, so this is the only route to
    -- Afghanistan cricket at all. These are ICC's computed figures, not ones
    -- derived here, which is why the column exists rather than the rows being
    -- quietly appended.
    source TEXT NOT NULL DEFAULT 'cricsheet' CHECK (source IN ('cricsheet', 'icc')),
    -- Identifies the same real-world match across sources, so a Cricsheet
    -- publication can supersede the ICC stand-in instead of double-counting
    -- every player's career. Format: gender|competition|date|teamA|teamB with
    -- the team names sorted, so it does not depend on which side is listed
    -- first (the two feeds disagree about that).
    natural_key TEXT
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
-- Ball-by-ball records (Phase 1.5).
--
-- The single largest table by far: ~4.9M rows against player_match_stats' 221k.
-- Everything §5 lists as Tier B unblocks from here -- phase splits need `over`,
-- dot-ball rates need `runs_batter`, batting position needs the order within an
-- innings, and chasing needs `innings`.
--
-- Column choices are storage decisions at this row count:
--   * `seq` is the 0-based position within the innings and is what makes the
--     primary key work. Ball-within-over cannot: a wide or no-ball adds a
--     delivery to the over, so (over, ball) is not unique.
--   * Players are stored as Cricsheet identifiers rather than names, which are
--     both smaller and stable across the spelling variants `players` reconciles.
--   * Extras are four small columns rather than a kind string, because a single
--     delivery can be both a no-ball and carry byes, and because 0 costs less
--     than a repeated label 4.9M times.
--   * `non_boundary` carries Cricsheet's own flag so a four can be told from
--     four runs run -- the same distinction the aggregate parser now honours.
CREATE TABLE IF NOT EXISTS deliveries (
    match_id TEXT NOT NULL REFERENCES matches(match_id),
    innings INTEGER NOT NULL,          -- 1-based; gives batting-first vs chasing
    seq INTEGER NOT NULL,              -- 0-based order within the innings
    over INTEGER NOT NULL,             -- 0-based; gives powerplay/middle/death
    ball INTEGER NOT NULL,             -- 1-based within the over, extras included
    batting_team_id INTEGER REFERENCES teams(team_id),
    batter TEXT REFERENCES players(identifier),
    bowler TEXT REFERENCES players(identifier),
    non_striker TEXT REFERENCES players(identifier),
    runs_batter INTEGER NOT NULL DEFAULT 0,
    runs_extras INTEGER NOT NULL DEFAULT 0,
    runs_total INTEGER NOT NULL DEFAULT 0,
    non_boundary INTEGER NOT NULL DEFAULT 0,   -- 1 => a 4/6 that was run, not hit
    wides INTEGER NOT NULL DEFAULT 0,
    noballs INTEGER NOT NULL DEFAULT 0,
    byes INTEGER NOT NULL DEFAULT 0,
    legbyes INTEGER NOT NULL DEFAULT 0,
    wicket_kind TEXT,                  -- NULL on the overwhelming majority of balls
    player_out TEXT REFERENCES players(identifier),
    -- Who effected the dismissal. Only the FIRST fielder is kept: a catch has
    -- one, and the rare two-fielder run out does not change any question we
    -- ask. This is what identifies a wicketkeeper -- only a keeper can stump,
    -- and a keeper takes far more catches than any other fielder. §5 called
    -- keeper identification impossible, which was true of player_match_stats
    -- and not of Cricsheet, which carries fielders on 65% of wickets.
    fielder TEXT REFERENCES players(identifier),
    PRIMARY KEY (match_id, innings, seq)
) WITHOUT ROWID;

-- Deliveries are always read by match, or by player within a scope. A covering
-- index on either is what keeps a phase split off a full scan of 4.9M rows.
CREATE INDEX IF NOT EXISTS idx_deliveries_batter ON deliveries(batter, match_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_bowler ON deliveries(bowler, match_id);

-- Announced squads per fixture, from the ICC scorecard feed.
--
-- This table is the answer to §34 #1 and #2 at once. The feed carries, for each
-- named player: a sourced ROLE (including wicketkeeper), batting handedness,
-- bowling style, and an availability status. Every one of those was listed as
-- Tier C on the assumption no source had them -- true of Cricsheet and
-- Wikidata, not of the feed this project already consumes for fixtures.
--
-- Kept SEPARATE from `players` rather than merged into it, for the same reason
-- ICC rankings are: this is ICC's claim about their own squad lists, and a
-- player's role here is a fact about a fixture, not a permanent property. A
-- player can be picked as a keeper in one squad and a batter in another.
--
-- `player_identifier` is populated only where the name resolves confidently to
-- one of our players; an unresolved row is still stored, because the squad is
-- real whether or not we can link it.
CREATE TABLE IF NOT EXISTS fixture_squads (
    icc_match_id TEXT NOT NULL REFERENCES fixtures(icc_match_id),
    icc_team_id TEXT NOT NULL,
    team_name TEXT,
    player_name TEXT NOT NULL,        -- as ICC spells it
    player_identifier TEXT REFERENCES players(identifier),  -- null => unmatched
    position INTEGER,
    is_captain INTEGER NOT NULL DEFAULT 0,
    role TEXT,                        -- Batter | Bowler | All-Rounder | Wicket Keeper
    batting_style TEXT,               -- RHB | LHB
    bowling_style TEXT,               -- RM, RFM, OB, SLO, LB ...
    status TEXT,                      -- ICC's own availability wording
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (icc_match_id, icc_team_id, player_name)
);

CREATE INDEX IF NOT EXISTS idx_fixture_squads_player ON fixture_squads(player_identifier);
CREATE INDEX IF NOT EXISTS idx_fixture_squads_match ON fixture_squads(icc_match_id);

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
-- The tournaments list groups by exactly this, and the detail page filters on
-- the first two columns.
CREATE INDEX IF NOT EXISTS idx_matches_event
    ON matches(event_name, gender, season_label);

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

-- ===========================================================================
-- Sports news
-- ===========================================================================
--
-- A fourth source family beside Cricsheet, the ICC feeds and Wikidata, and
-- kept as visibly separate from them as those three are from each other.
-- Nothing in here ever feeds a derived cricket figure: an article is editorial
-- copy, and letting a headline influence an average would be the same mistake
-- as merging ICC's published ratings into the ratings this project computes.
--
-- The split across three groups of tables is deliberate and is what the rest
-- of the pipeline leans on:
--
--   content    news_articles and its satellites -- what was published
--   seo        news_article_metadata           -- the publisher's marketing
--                                                 surface, which drifts
--                                                 independently of the body
--   ingestion  news_ingestions                 -- our record of the attempt,
--                                                 which must exist even when
--                                                 no article does

-- One row per publisher. The runtime registry (strategy, rate limits, robots
-- rules) lives in ingestion/news_sources.py because it is code configuration;
-- this table is the publisher ENTITY that articles hang off, plus the licence
-- terms we are obliged to honour when displaying them.
CREATE TABLE IF NOT EXISTS news_publishers (
    publisher_id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,        -- 'guardian' | 'icc' | 'skysports' | ...
    name TEXT NOT NULL,
    home_url TEXT,
    strategy TEXT NOT NULL,          -- 'api' | 'sitemap' | 'rss' | 'feed_only'
    -- What we are entitled to keep and show, NOT what we were able to fetch.
    -- 'full'          body stored and servable
    -- 'extract'       body stored for entity extraction and search; the API
    --                 returns a capped snippet and a link out
    -- 'metadata_only' headline, standfirst and hero image; there is no body
    content_policy TEXT NOT NULL
        CHECK (content_policy IN ('full', 'extract', 'metadata_only')),
    attribution TEXT,                -- credit line the UI must render
    policy_note TEXT,                -- why this source is read the way it is
    enabled INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT
);

-- The article itself.
--
-- url_fingerprint (SHA-256 of the canonicalised URL) is UNIQUE and is what
-- stops one article being filed twice after a slug rewrite or a tracking
-- parameter. (publisher_id, source_article_id) is UNIQUE for the same reason
-- one level deeper: Sky's RSS links /cricket/news/12040/13574220/... while
-- their own rel=canonical says /cricket/news/12175/... -- the 5-digit section
-- id varies, the 8-digit article id does not, so the id catches the duplicate
-- that even a canonicalised URL would miss.
--
-- content_hash is the SHA-256 of everything extracted, mixed with
-- news_sources.EXTRACTOR_VERSION. Same contract as matches.content_hash: an
-- unchanged article is a no-op, and bumping the extractor version forces a
-- genuine re-process instead of a clean skip that reports success.
--
-- text_simhash detects SYNDICATION -- the same body republished elsewhere. It
-- is deliberately NOT used to merge different articles about the same event:
-- three publishers covering one squad announcement wrote three articles, and
-- collapsing them would delete two mastheads' work and misreport coverage.
CREATE TABLE IF NOT EXISTS news_articles (
    article_id INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_id INTEGER NOT NULL REFERENCES news_publishers(publisher_id),
    source_key TEXT NOT NULL,        -- denormalised, as matches.source is
    source_article_id TEXT,          -- the publisher's own stable id
    canonical_url TEXT NOT NULL,
    url_fingerprint TEXT NOT NULL UNIQUE,
    discovered_url TEXT,             -- where we found it, when it differs

    title TEXT NOT NULL,
    standfirst TEXT,                 -- summary / trail text / description
    body_html TEXT,                  -- null for a metadata_only publisher
    body_text TEXT,
    word_count INTEGER NOT NULL DEFAULT 0,
    -- The publisher's own count where they state one. Kept because it is the
    -- only independent check that a body arrived whole rather than truncated
    -- by a consent wall, and a truncated body is the failure this pipeline is
    -- most likely to record as a success.
    declared_word_count INTEGER,

    published_at TEXT,               -- ISO-8601 UTC
    updated_at TEXT,
    section TEXT,
    language TEXT,
    sport TEXT NOT NULL DEFAULT 'cricket',

    content_hash TEXT NOT NULL,
    text_simhash TEXT,               -- 64-bit SimHash, stored as a hex string
    -- Set when this body is a near-duplicate of an article already stored.
    -- The row is still kept: knowing a wire story ran in three places is
    -- information, and deleting the copy would lose the second publisher.
    syndication_of_article_id INTEGER REFERENCES news_articles(article_id),

    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (publisher_id, source_article_id)
);

-- SEO and structured metadata, 1:1 with an article and separate from it.
-- Separate because these are the publisher's distribution surface: og:title
-- is frequently not the headline, and the raw JSON-LD is worth keeping whole
-- so that a future extractor can re-derive fields from it without refetching
-- a page that may by then be behind a wall.
CREATE TABLE IF NOT EXISTS news_article_metadata (
    article_id INTEGER PRIMARY KEY REFERENCES news_articles(article_id) ON DELETE CASCADE,
    meta_title TEXT,
    meta_description TEXT,
    og_json TEXT,                    -- all og:* properties, as JSON
    twitter_json TEXT,               -- all twitter:* properties, as JSON
    json_ld TEXT,                    -- the selected schema.org article node
    schema_type TEXT                 -- 'NewsArticle' | 'Article' | ...
);

CREATE TABLE IF NOT EXISTS news_authors (
    author_id INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_id INTEGER NOT NULL REFERENCES news_publishers(publisher_id),
    name TEXT NOT NULL,
    -- A byline is not always a person: "Guardian sport" and "ICC" are desks.
    -- Recorded as-is rather than dropped, because dropping them would leave
    -- the article unattributed, and guessed personhood would be a claim no
    -- source made.
    UNIQUE (publisher_id, name)
);

CREATE TABLE IF NOT EXISTS news_article_authors (
    article_id INTEGER NOT NULL REFERENCES news_articles(article_id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES news_authors(author_id),
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (article_id, author_id)
);

-- Tags keep their kind because the kinds mean different things: an 'entity'
-- tag is a candidate link to a row in `players`, a 'keyword' is free text,
-- and a 'section' is the publisher's own desk.
CREATE TABLE IF NOT EXISTS news_tags (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- 'keyword' | 'entity' | 'section' | 'series' | 'type'
    value TEXT NOT NULL,
    slug TEXT NOT NULL,
    UNIQUE (kind, slug)
);

CREATE TABLE IF NOT EXISTS news_article_tags (
    article_id INTEGER NOT NULL REFERENCES news_articles(article_id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES news_tags(tag_id),
    PRIMARY KEY (article_id, tag_id)
);

-- Images are REFERENCED, never re-hosted. Every hero on these four sources is
-- licensed agency photography (Getty, Alamy, PA, Reuters); the RSS and API
-- grants cover reading the metadata, not redistributing the file. This is the
-- same call already made for players.image_url, except that one is a freely
-- licensed Wikimedia asset and these are not, so the reasoning is stronger
-- here rather than weaker.
--
-- fingerprint identifies the ASSET, not a rendition of it, so one photograph
-- served at 365x205 and at 1400x933 is one row. How that identity is
-- recovered is per-CDN and lives in news_sources.image_identity: an
-- ESPNcricinfo numeric id, a Sky 365dm asset id, a Cloudinary public id, a
-- Guardian mediaId.
CREATE TABLE IF NOT EXISTS news_images (
    image_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    provider TEXT,                   -- 'imgci' | '365dm' | 'cloudinary' | 'guim'
    cdn_url TEXT NOT NULL,           -- the largest rendition we know of
    -- A list-sized rendition of the same asset, for rows and cards. Stored
    -- rather than derived at render time because the per-CDN rules for it are
    -- ingestion's knowledge, and because two of the four CDNs whitelist their
    -- sizes: media.guim.co.uk serves /140 and /500 and returns 403 for /300,
    -- and the ICC's Cloudinary account returns 401 for any transform outside
    -- its named list. Null means the CDN is unknown and callers show cdn_url.
    thumb_url TEXT,
    origin_url TEXT,                 -- as the source gave it, before upgrade
    width INTEGER,
    height INTEGER,
    mime_type TEXT,
    byte_size INTEGER,
    -- Populated only when NEWS_IMAGE_PROBE is on: dimensions read from the
    -- file's own header for a source that declares none. Never a stored copy
    -- of the image -- the bytes are read and discarded.
    probed_at TEXT,
    probe_status TEXT
);

CREATE TABLE IF NOT EXISTS news_article_images (
    article_id INTEGER NOT NULL REFERENCES news_articles(article_id) ON DELETE CASCADE,
    image_id INTEGER NOT NULL REFERENCES news_images(image_id),
    role TEXT NOT NULL DEFAULT 'hero'   -- 'hero' | 'inline' | 'thumbnail'
        CHECK (role IN ('hero', 'inline', 'thumbnail')),
    position INTEGER NOT NULL DEFAULT 0,
    -- Caption, credit and alt text hang off the ARTICLE-image pair, not off
    -- the image: the same photograph is re-used across articles with a
    -- different caption each time, and storing it on the asset would have the
    -- last article to run overwrite every earlier one's caption.
    alt_text TEXT,
    caption TEXT,
    credit TEXT,
    image_type TEXT,                 -- 'Photograph' | 'Illustration' | ...
    PRIMARY KEY (article_id, image_id, role)
);

-- Links from an article to the cricket entities this project already models.
-- Nullable-by-omission rather than nullable-by-column: a row exists only when
-- something was actually resolved, and an article that mentions a player we
-- cannot identify confidently simply has no row, exactly as an unmatched ICC
-- ranking entry stays unlinked rather than being attached to the wrong person.
--
-- `confidence` records HOW it was resolved so a reader can weigh it:
--   'tag_dob'   publisher entity tag carrying a date of birth that matches
--               players.date_of_birth. Effectively exact.
--   'tag_name'  publisher entity tag, name resolved through the same
--               (surname, initial) index the ICC rankings use.
--   'body_name' a team or competition name found in the title or body, with
--               the article's gender established from explicit markers.
--   'body_name_men_default'
--               the same, but nothing in the text established a gender, so
--               the men's side was taken. Recorded distinctly rather than
--               merged into 'body_name' because it IS a default, and a reader
--               weighing a women's-cricket query needs to see that.
CREATE TABLE IF NOT EXISTS news_article_entities (
    article_id INTEGER NOT NULL REFERENCES news_articles(article_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('player', 'team', 'competition')),
    player_identifier TEXT REFERENCES players(identifier),
    team_id INTEGER REFERENCES teams(team_id),
    competition_id INTEGER REFERENCES competitions(competition_id),
    mention TEXT NOT NULL,           -- the text that produced the link
    confidence TEXT NOT NULL,
    PRIMARY KEY (article_id, entity_type, mention)
);

-- The ingestion ledger. Keyed on url_fingerprint and NOT on article_id, which
-- is the point: a URL that failed to extract has a row here and no article
-- row anywhere, so a partial or failed scrape can never be mistaken for a
-- stored article. It is also the retry state, the circuit-breaker input and
-- the conditional-request cache in one place.
CREATE TABLE IF NOT EXISTS news_ingestions (
    url_fingerprint TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    url TEXT NOT NULL,
    article_id INTEGER REFERENCES news_articles(article_id),
    -- 'pending'   discovered, not yet fetched
    -- 'stored'    fetched, extracted, validated, written
    -- 'unchanged' content_hash matched; nothing rewritten
    -- 'invalid'   fetched and parsed, but validate() objected. NOT an error:
    --             the page was served, it just wasn't an article.
    -- 'failed'    transport or parse failure; eligible for retry
    -- 'skipped'   deliberately not fetched (robots, policy, unsupported)
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'stored', 'unchanged', 'invalid', 'failed', 'skipped')),
    extractor_version INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    etag TEXT,                       -- for the next conditional request
    last_modified TEXT,
    content_hash TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    problems TEXT,                   -- validate()'s reasons, JSON array
    first_attempt_at TEXT,
    last_attempt_at TEXT,
    next_attempt_after TEXT          -- exponential backoff, honoured on retry
);

-- Per-feed conditional-request state, so a discovery pass that finds nothing
-- new costs one 304 and no body. The same trick download_archive already uses
-- against Cricsheet's Last-Modified, applied per feed URL rather than per
-- competition.
CREATE TABLE IF NOT EXISTS news_feed_state (
    feed_url TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    etag TEXT,
    last_modified TEXT,
    last_fetched_at TEXT,
    last_status INTEGER,
    -- Consecutive failures. The circuit breaker in news_activities opens on
    -- this rather than on a per-run counter, so a source that is down stays
    -- skipped across runs instead of being retried from scratch every time.
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    items_last_seen INTEGER NOT NULL DEFAULT 0
);

-- news ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_news_articles_published ON news_articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_articles_source_published
    ON news_articles(source_key, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_articles_simhash ON news_articles(text_simhash);
CREATE INDEX IF NOT EXISTS idx_news_articles_syndication
    ON news_articles(syndication_of_article_id);
CREATE INDEX IF NOT EXISTS idx_news_article_tags_tag ON news_article_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_news_article_images_image ON news_article_images(image_id);
CREATE INDEX IF NOT EXISTS idx_news_article_entities_player
    ON news_article_entities(player_identifier);
CREATE INDEX IF NOT EXISTS idx_news_article_entities_team ON news_article_entities(team_id);
CREATE INDEX IF NOT EXISTS idx_news_article_authors_author
    ON news_article_authors(author_id);
-- The retry sweep's exact filter: what is due, oldest first.
CREATE INDEX IF NOT EXISTS idx_news_ingestions_retry
    ON news_ingestions(status, next_attempt_after);
CREATE INDEX IF NOT EXISTS idx_news_ingestions_source ON news_ingestions(source_key, status);
