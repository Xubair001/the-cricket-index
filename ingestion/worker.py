import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from db import init_db
from shared import TASK_QUEUE
from ingestion_workflow import CricsheetIngestionWorkflow
from news_workflow import NewsIngestionWorkflow, NewsSyncWorkflow
from enrichment_workflow import (
    IccScorecardsWorkflow,
    IccDailySyncWorkflow,
    IccFixturesWorkflow,
    IccRankingsWorkflow,
    PlayerEnrichmentWorkflow,
)
from news_activities import (
    discover_news,
    fetch_news_batch,
    link_news_entities,
    news_health,
    news_retry_sweep,
    probe_news_images,
    record_news_progress,
)
from activities import (
    download_archive,
    enrich_from_wikidata,
    fetch_icc_feed,
    fetch_icc_fixtures,
    find_icc_scorecard_candidates,
    ingest_icc_scorecards,
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
            IccScorecardsWorkflow,
            IccDailySyncWorkflow,
            PlayerEnrichmentWorkflow,
            NewsIngestionWorkflow,
            NewsSyncWorkflow,
        ],
        activities=[
            download_archive,
            ingest_match,
            record_progress,
            sync_people_register,
            enrich_from_wikidata,
            fetch_icc_feed,
            fetch_icc_fixtures,
            find_icc_scorecard_candidates,
            ingest_icc_scorecards,
            discover_news,
            fetch_news_batch,
            link_news_entities,
            probe_news_images,
            news_retry_sweep,
            record_news_progress,
            news_health,
        ],
        # Unchanged. News activities are the opposite of CPU-bound - each one
        # spends most of its life inside a deliberate politeness delay - so
        # the real concurrency limit for news is per-source, and it lives in
        # news_activities._SourceLimiter rather than here. Raising this would
        # not fetch news any faster; it would only let more activities queue
        # up behind the same per-source floor.
        max_concurrent_activities=10,
    )

    print(f"Worker started, polling task queue '{TASK_QUEUE}'... (Ctrl+C to stop)")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
