"""Workflows for sports news ingestion.

Built on the infrastructure that already exists rather than beside it: the
same task queue (shared.TASK_QUEUE), the same worker, the same
`workflow.unsafe.imports_passed_through()` convention, the same RetryPolicy
and heartbeat shapes, and the same continue-as-new batching that keeps
CricsheetIngestionWorkflow's history bounded across 10,000 matches.

Two workflows, mirroring the split that already exists between
CricsheetIngestionWorkflow (one competition, batched) and IccDailySyncWorkflow
(the scheduled composite that fans out and isolates failures):

    NewsIngestionWorkflow   one source, discovery then batched fetch,
                            continue-as-new between generations
    NewsSyncWorkflow        every enabled source as a child workflow, then the
                            two post-passes that need the article rows to exist

Why children rather than one big workflow: a source is the unit that fails.
The Guardian's API being down must not stop the ICC sitemap, exactly as
IccDailySyncWorkflow already ensures a bad ICC feed cannot stop a Cricsheet
ingest. Children also give each source its own entry in the Web UI, so
"which publisher broke" is answerable without reading a log.
"""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from shared import (
        NEWS_BATCH_SIZE_PER_GENERATION,
        NewsJobInput,
        NewsJobProgress,
    )
    from news_sources import SOURCES
    from news_activities import (
        discover_news,
        fetch_news_batch,
        link_news_entities,
        news_health,
        news_retry_sweep,
        probe_news_images,
        record_news_progress,
    )

# Sources the scheduled sync covers. Read from the registry rather than
# repeated here, so enabling a publisher stays a one-line change in
# news_sources.py -- the same reasoning DAILY_COMPETITIONS uses for archives.
DAILY_NEWS_SOURCES = sorted(k for k, s in SOURCES.items() if s.enabled)

# Discovery is one activity that may walk several feeds under a politeness
# delay. The ICC's sitemap index at a 1s floor over 13 documents is the worst
# case measured, well inside this.
DISCOVERY_TIMEOUT = timedelta(minutes=10)

# A batch of 40 articles at Sky's 2s floor is 80 seconds of deliberate waiting
# plus fetch time. Fifteen minutes leaves room for a slow publisher without
# letting a wedged batch hold a generation open indefinitely.
FETCH_TIMEOUT = timedelta(minutes=15)
FETCH_HEARTBEAT = timedelta(minutes=2)


@workflow.defn
class NewsIngestionWorkflow:
    """One news source, discovered once then fetched in bounded generations.

    Discovery runs in the FIRST generation only; subsequent generations
    inherit the pending list through continue-as-new. Re-discovering each
    generation would re-walk every feed for no new URLs and would make a long
    run's cost quadratic in its own length.
    """

    def __init__(self) -> None:
        self._stop_requested = False
        self._input: NewsJobInput | None = None

    @workflow.run
    async def run(self, input: NewsJobInput) -> str:
        self._input = input

        if not input.discovered:
            try:
                found = await workflow.execute_activity(
                    discover_news,
                    args=[input.source_key, input.since],
                    start_to_close_timeout=DISCOVERY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except ActivityError as e:
                # Discovery failing is a source-level outage, not a bug in a
                # single article. Reported rather than raised so the parent's
                # other children still run and the schedule does not show a
                # failed workflow for a publisher having a bad afternoon.
                workflow.logger.warning(f"news discovery {input.source_key} failed: {e!r}")
                return f"{input.source_key}: discovery FAILED ({type(e.cause).__name__})"

            if not found.get("enabled", True):
                return f"{input.source_key}: disabled ({found.get('reason', 'no reason given')})"
            if found.get("breaker_open"):
                input.breaker_open = True
                return (
                    f"{input.source_key}: circuit breaker OPEN "
                    f"({found.get('reason')}); nothing fetched"
                )

            input.pending = found.get("pending") or []
            input.total = len(input.pending)
            input.discovered = True

        batch = input.pending[:NEWS_BATCH_SIZE_PER_GENERATION]
        remaining = input.pending[NEWS_BATCH_SIZE_PER_GENERATION:]

        if batch:
            try:
                result = await workflow.execute_activity(
                    fetch_news_batch,
                    args=[input.source_key, batch],
                    start_to_close_timeout=FETCH_TIMEOUT,
                    # Without this, a worker that dies mid-batch is only
                    # noticed when start_to_close expires, stalling the
                    # generation for the remaining fourteen minutes.
                    heartbeat_timeout=FETCH_HEARTBEAT,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                input.stored += result["stored"]
                input.unchanged += result["unchanged"]
                input.invalid += result["invalid"]
                input.failed += result["failed"]
                input.skipped += result["skipped"]
            except ActivityError as e:
                # The ledger already holds each URL's own status, so a lost
                # batch is recoverable work rather than lost work: those rows
                # are still 'pending' and the next run picks them up.
                workflow.logger.warning(
                    f"news batch {input.source_key} failed after retries: {e!r}"
                )
                input.failed += len(batch)

        await workflow.execute_activity(
            record_news_progress,
            args=[input.source_key, input.stored, input.unchanged,
                  input.invalid, input.failed],
            start_to_close_timeout=timedelta(seconds=30),
        )

        if remaining and not self._stop_requested:
            input.pending = remaining
            workflow.continue_as_new(input)

        return (
            f"{input.source_key}: {input.stored} stored, "
            f"{input.unchanged} unchanged, {input.invalid} invalid, "
            f"{input.failed} failed, {input.skipped} skipped "
            f"(of {input.total} discovered)"
            + (" [stopped early]" if self._stop_requested and remaining else "")
        )

    @workflow.signal
    def stop(self) -> None:
        """Finish the current generation and do not continue-as-new.

        Same signal CricsheetIngestionWorkflow exposes, and it matters more
        here: stopping a news run mid-way is how you stop hitting a publisher
        who has just asked you to.
        """
        self._stop_requested = True

    @workflow.query
    def progress(self) -> NewsJobProgress:
        assert self._input is not None
        return NewsJobProgress(
            source_key=self._input.source_key,
            total=self._input.total,
            stored=self._input.stored,
            unchanged=self._input.unchanged,
            invalid=self._input.invalid,
            failed=self._input.failed,
            remaining=len(self._input.pending),
        )


@workflow.defn
class NewsSyncWorkflow:
    """The scheduled news job: every enabled source, then the post-passes.

    Sources run CONCURRENTLY, unlike IccDailySyncWorkflow's Cricsheet leg
    which runs sequentially. The difference is what each is bounded by: a bulk
    archive ingest is bounded by writes to the one SQLite file and is worth
    not overlapping, whereas news fetching is bounded by four independent
    publishers' politeness delays, and serialising them would spend the whole
    run waiting on whichever source is slowest while the other three idle.
    Each source's own concurrency is capped inside its limiter regardless.

    The retry sweep runs FIRST, so anything that failed yesterday is back in
    the queue before today's discovery, and gets fetched in the same pass
    rather than a day later.
    """

    @workflow.run
    async def run(self, sources: list[str] | None = None, since: str = "") -> str:
        parts: list[str] = []

        try:
            sweep = await workflow.execute_activity(
                news_retry_sweep,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if sweep["requeued"] or sweep["abandoned"]:
                parts.append(
                    f"retries: {sweep['requeued']} re-queued, "
                    f"{sweep['abandoned']} abandoned"
                )
        except ActivityError as e:
            workflow.logger.warning(f"news retry sweep failed: {e!r}")
            parts.append("retries: FAILED")

        targets = sources if sources is not None else DAILY_NEWS_SOURCES
        results = await asyncio.gather(
            *[
                workflow.execute_child_workflow(
                    NewsIngestionWorkflow.run,
                    NewsJobInput(source_key=source, since=since),
                    id=f"{workflow.info().workflow_id}-{source}",
                )
                for source in targets
            ],
            # One publisher's outage must not fail the whole sync. This is the
            # same guard IccDailySyncWorkflow uses across its three legs.
            return_exceptions=True,
        )
        for source, outcome in zip(targets, results):
            parts.append(
                outcome if isinstance(outcome, str)
                else f"{source}: FAILED {type(outcome).__name__}"
            )

        # Entity linking and image measurement run AFTER every source, not
        # beside them: both read the rows the fetch legs have just written, so
        # running them concurrently would work off yesterday's articles. Same
        # ordering, and the same reason, as scorecards running after fixtures
        # in IccDailySyncWorkflow.
        try:
            entities = await workflow.execute_activity(
                link_news_entities,
                args=[ENTITY_LINK_LIMIT],
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            parts.append(
                f"entities: {entities['tag_dob']} by tag+DOB, "
                f"{entities['tag_name']} by name, {entities['body_name']} teams "
                f"(over {entities['considered']} articles)"
            )
        except ActivityError as e:
            workflow.logger.warning(f"news entity linking failed: {e!r}")
            parts.append("entities: FAILED")

        try:
            images = await workflow.execute_activity(
                probe_news_images,
                args=[IMAGE_PROBE_LIMIT],
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            if images.get("enabled"):
                parts.append(
                    f"images: {images['measured']} measured of {images['probed']} probed"
                )
        except ActivityError as e:
            workflow.logger.warning(f"news image probe failed: {e!r}")
            parts.append("images: FAILED")

        try:
            health = await workflow.execute_activity(
                news_health,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            if health.get("degraded_feeds"):
                names = ", ".join(
                    f"{f['source']}x{f['failures']}" for f in health["degraded_feeds"]
                )
                parts.append(f"DEGRADED FEEDS: {names}")
            parts.append(
                f"held: {sum(s['articles'] for s in health['sources'])} articles, "
                f"{health['syndicated']} syndicated"
            )
        except ActivityError:
            pass

        return " | ".join(parts)


# One post-pass covers a day's articles several times over across four
# sources, and linking is cheap once the name index is built. Bounded anyway
# so a first run over a backfill cannot hold the activity open indefinitely;
# the remainder is picked up by the next run, since the query selects only
# articles with no entity rows yet.
ENTITY_LINK_LIMIT = 500
IMAGE_PROBE_LIMIT = 200
