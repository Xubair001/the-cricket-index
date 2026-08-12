import os
from dataclasses import dataclass, field
from typing import Optional

TASK_QUEUE = "cricket-ingestion-queue"

CRICSHEET_URLS = {
    "tests": "https://cricsheet.org/downloads/tests_json.zip",
    "odis": "https://cricsheet.org/downloads/odis_json.zip",
    "t20is": "https://cricsheet.org/downloads/t20s_json.zip",
}

# Archive key -> (competition display name, competition type). All three
# current sources are international; a later PSL addition would map to
# ("Pakistan Super League", "domestic_league").
COMPETITION_META = {
    "tests": ("Test", "international"),
    "odis": ("ODI", "international"),
    "t20is": ("T20I", "international"),
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
