import os
from dataclasses import dataclass, field
from typing import Optional

TASK_QUEUE = "cricket-ingestion-queue"

# Bump this whenever `parsing.py` changes what it derives from a match.
#
# Idempotency here is a SHA-256 of the raw match JSON, and Cricsheet's bytes do
# not change when our parser does -- so without this, fixing a parsing bug and
# re-running ingestion skips all 10,040 matches and reports success while
# inserting nothing. The scope calls this out as one of two traps in the
# deliveries migration, and it is not hypothetical: it is exactly what would
# have happened to the boundary-counting fix in v2.
#
#   v1  original parser
#   v2  fours/sixes honour Cricsheet's runs.non_boundary flag, so a boundary
#       count is boundaries rather than "deliveries worth four runs"
#       (validated: Joe Root 1,523 -> published 1,515 Test fours)
#   v3  ball-by-ball deliveries stored (Phase 1.5). Aggregates are unchanged;
#       this bump exists so the backfill actually re-parses rather than
#       skipping every match and reporting success.
#   v4  the fielder credited with each dismissal is stored, which is what makes
#       a wicketkeeper identifiable -- only a keeper stumps.
PARSER_VERSION = 4

CRICSHEET_URLS = {
    "tests": "https://cricsheet.org/downloads/tests_json.zip",
    "odis": "https://cricsheet.org/downloads/odis_json.zip",
    "t20is": "https://cricsheet.org/downloads/t20s_json.zip",
    "psl": "https://cricsheet.org/downloads/psl_json.zip",
}

# Archive key -> (competition display name, competition type).
COMPETITION_META = {
    "tests": ("Test", "international"),
    "odis": ("ODI", "international"),
    "t20is": ("T20I", "international"),
    "psl": ("Pakistan Super League", "domestic_league"),
}

# Competition type -> the team_type its sides are keyed under.
#
# Deliberately NOT taken from the source data: Cricsheet's own info.team_type
# says "club" for franchise leagues, which isn't in the schema's vocabulary
# ('international' | 'franchise'), so passing it through would fail the CHECK
# constraint. The competition already determines the answer, so derive it here
# and let info.team_type remain a display-only column on matches.
TEAM_TYPE_BY_COMPETITION_TYPE = {
    "international": "international",
    "domestic_league": "franchise",
}

# ingestion/ lives one level below the project root, where cricket.db and
# data/ are shared with the backend. Resolved from this file's own location
# so it works regardless of the process's current working directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "cricket.db")

# How many matches to fold into one Continue-As-New generation, and how many
# child MatchIngestionWorkflows to run concurrently within a generation.
BATCH_SIZE_PER_GENERATION = 100
MAX_CONCURRENT_CHILDREN = 10


@dataclass
class DownloadResult:
    competition: str
    archive_path: str
    match_ids: list[str] = field(default_factory=list)


@dataclass
class MatchIngestionInput:
    competition: str
    archive_path: str
    match_id: str


@dataclass
class MatchIngestionResult:
    match_id: str
    success: bool
    skipped: bool = False
    error: Optional[str] = None


@dataclass
class IngestionJobInput:
    competition: str
    archive_path: str
    match_ids: list[str]
    total_matches: int = 0
    processed_count: int = 0
    skipped_count: int = 0
    failed_match_ids: list[str] = field(default_factory=list)


@dataclass
class IngestionProgress:
    competition: str
    total: int
    processed: int
    skipped: int
    failed: int
    current_generation_started_at: str = ""


# --------------------------------------------------------------------------
# News ingestion
# --------------------------------------------------------------------------
#
# The same continue-as-new shape CricsheetIngestionWorkflow uses, for the same
# reason: a discovery pass over four sources returns a few hundred URLs and a
# backfill returns thousands, and folding them all into one workflow history
# is what makes a long run unreplayable.
#
# The batch is smaller than the Cricsheet one (100) because each item here is
# a network fetch against a third party under a politeness delay, not a read
# out of a local zip. At Sky's 2s floor, 40 articles is about 80 seconds of
# deliberate waiting per generation, which is a sensible amount of work to
# checkpoint at.
NEWS_BATCH_SIZE_PER_GENERATION = 40


@dataclass
class NewsJobInput:
    """One source's ingestion run, carried across continue-as-new generations.

    `pending` holds url_fingerprints rather than URLs: the fingerprint is the
    primary key of news_ingestions, so a resumed generation looks up the URL
    and every piece of retry state from the row rather than trusting a value
    carried through workflow history that may since have been superseded.
    """

    source_key: str
    pending: list[str] = field(default_factory=list)
    discovered: bool = False
    total: int = 0
    stored: int = 0
    unchanged: int = 0
    invalid: int = 0
    failed: int = 0
    skipped: int = 0
    # Set when discovery was refused because the source's circuit breaker is
    # open. Carried so the final summary can say so rather than reporting a
    # successful run that happened to find nothing.
    breaker_open: bool = False
    # Only look at articles published on or after this date (YYYY-MM-DD).
    # Empty means the source's own natural window, which for an RSS feed is
    # whatever it currently lists.
    since: str = ""


@dataclass
class NewsJobProgress:
    source_key: str
    total: int
    stored: int
    unchanged: int
    invalid: int
    failed: int
    remaining: int


@dataclass
class NewsBatchResult:
    stored: int = 0
    unchanged: int = 0
    invalid: int = 0
    failed: int = 0
    skipped: int = 0
