import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from shared import (
        BATCH_SIZE_PER_GENERATION,
        MAX_CONCURRENT_CHILDREN,
        IngestionJobInput,
        IngestionProgress,
        MatchIngestionInput,
    )
    from activities import download_archive, ingest_match, record_progress


@workflow.defn
class CricsheetIngestionWorkflow:
    def __init__(self) -> None:
        self._stop_requested = False
        self._input: IngestionJobInput | None = None

    @workflow.run
    async def run(self, input: IngestionJobInput) -> str:
        self._input = input

        if not input.archive_path:
            download_result = await workflow.execute_activity(
                download_archive,
                input.competition,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            input.archive_path = download_result.archive_path
            input.match_ids = download_result.match_ids
            input.total_matches = len(download_result.match_ids)

        batch = input.match_ids[:BATCH_SIZE_PER_GENERATION]
        remaining = input.match_ids[BATCH_SIZE_PER_GENERATION:]

        for i in range(0, len(batch), MAX_CONCURRENT_CHILDREN):
            chunk = batch[i : i + MAX_CONCURRENT_CHILDREN]
            results = await asyncio.gather(
                *[self._ingest_one(input.competition, input.archive_path, mid) for mid in chunk]
            )
            for match_id, success, skipped in results:
                if success and skipped:
                    input.skipped_count += 1
                elif success:
                    input.processed_count += 1
                else:
                    input.failed_match_ids.append(match_id)

        await workflow.execute_activity(
            record_progress,
            args=[
                input.competition,
                input.total_matches,
                input.processed_count,
                input.skipped_count,
                len(input.failed_match_ids),
            ],
            start_to_close_timeout=timedelta(seconds=10),
        )

        if remaining and not self._stop_requested:
            input.match_ids = remaining
            workflow.continue_as_new(input)

        return (
            f"{input.competition}: {input.processed_count} ingested, "
            f"{input.skipped_count} unchanged (skipped), "
            f"{len(input.failed_match_ids)} failed, "
            f"{len(remaining)} left unprocessed"
            + (" (stopped early)" if self._stop_requested and remaining else "")
        )

    async def _ingest_one(
        self, competition: str, archive_path: str, match_id: str
    ) -> tuple[str, bool, bool]:
        try:
            result = await workflow.execute_activity(
                ingest_match,
                MatchIngestionInput(
                    competition=competition, archive_path=archive_path, match_id=match_id
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return result.match_id, result.success, result.skipped
        except ActivityError:
            return match_id, False, False

    @workflow.signal
    def stop(self) -> None:
        self._stop_requested = True

    @workflow.query
    def progress(self) -> IngestionProgress:
        assert self._input is not None
        return IngestionProgress(
            competition=self._input.competition,
            total=self._input.total_matches,
            processed=self._input.processed_count,
            skipped=self._input.skipped_count,
            failed=len(self._input.failed_match_ids),
        )
