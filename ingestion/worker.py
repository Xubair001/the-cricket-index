import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from db import init_db
from shared import TASK_QUEUE
from ingestion_workflow import CricsheetIngestionWorkflow
from enrichment_workflow import (
    IccDailySyncWorkflow,
    IccFixturesWorkflow,
    IccRankingsWorkflow,
    PlayerEnrichmentWorkflow,
)
from activities import (
    download_archive,
    enrich_from_wikidata,
    fetch_icc_feed,
    fetch_icc_fixtures,
    ingest_match,
    record_progress,
    sync_people_register,
)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    client = await Client.connect("localhost:7233")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            CricsheetIngestionWorkflow,
            IccRankingsWorkflow,
            IccFixturesWorkflow,
            IccDailySyncWorkflow,
            PlayerEnrichmentWorkflow,
        ],
        activities=[
            download_archive,
            ingest_match,
            record_progress,
            sync_people_register,
            enrich_from_wikidata,
            fetch_icc_feed,
            fetch_icc_fixtures,
        ],
        max_concurrent_activities=10,
    )

    print(f"Worker started, polling task queue '{TASK_QUEUE}'... (Ctrl+C to stop)")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
