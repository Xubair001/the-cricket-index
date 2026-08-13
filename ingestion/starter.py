"""Triggers an ingestion job.

    python starter.py tests | odis | t20is | psl   # Cricsheet match archives
    python starter.py icc                          # ICC rankings, one-off
    python starter.py fixtures                     # ICC schedule: results + upcoming
    python starter.py daily                        # both of the above (what the schedule runs)
    python starter.py enrich                       # cricinfo crosswalk + Wikidata

`icc` normally runs from the daily schedule (see schedule.py); running it here
is for a manual refresh. `enrich` is not scheduled -- Wikidata bios change
rarely, and re-running it is only worthwhile after a new archive introduces
players the register didn't previously cover.
"""
import asyncio
import sys

from temporalio.client import Client

from shared import TASK_QUEUE, CRICSHEET_URLS, IngestionJobInput
from ingestion_workflow import CricsheetIngestionWorkflow
from enrichment_workflow import (
    IccDailySyncWorkflow,
    IccFixturesWorkflow,
    IccRankingsWorkflow,
    PlayerEnrichmentWorkflow,
)

SPECIAL_JOBS = {
    "icc": (IccRankingsWorkflow.run, "icc-rankings-manual"),
    "fixtures": (IccFixturesWorkflow.run, "icc-fixtures-manual"),
    "daily": (IccDailySyncWorkflow.run, "icc-daily-sync-manual"),
    "enrich": (PlayerEnrichmentWorkflow.run, "player-enrichment"),
}


async def main() -> None:
    job = sys.argv[1] if len(sys.argv) > 1 else "tests"

    if job not in SPECIAL_JOBS and job not in CRICSHEET_URLS:
        valid = ", ".join([*CRICSHEET_URLS, *SPECIAL_JOBS])
        raise SystemExit(f"unknown job '{job}'; expected one of: {valid}")

    client = await Client.connect("localhost:7233")

    if job in SPECIAL_JOBS:
        run_fn, workflow_id = SPECIAL_JOBS[job]
        handle = await client.start_workflow(run_fn, id=workflow_id, task_queue=TASK_QUEUE)
    else:
        handle = await client.start_workflow(
            CricsheetIngestionWorkflow.run,
            IngestionJobInput(competition=job, archive_path="", match_ids=[]),
            id=f"cricsheet-ingest-{job}",
            task_queue=TASK_QUEUE,
        )

    print(f"Started workflow: {handle.id}")
    print(f"View it at http://localhost:8233/namespaces/default/workflows/{handle.id}")

    result = await handle.result()
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
