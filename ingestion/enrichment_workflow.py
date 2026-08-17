"""Workflows for the non-Cricsheet sources, plus the daily job that ties all
three together.

The ICC and Wikidata workflows stay separate from CricsheetIngestionWorkflow:
they fail independently and neither can hold up or corrupt a match ingest.
IccDailySyncWorkflow is the scheduled entry point and composes them, calling
Cricsheet ingestion as a child workflow rather than duplicating it.

Wikidata is deliberately NOT in the daily job. It is the slowest source by an
order of magnitude (48 throttled SPARQL batches), and bios, names and photos
change on the scale of years -- running it daily would spend most of the
schedule's wall clock re-confirming dates of birth.
"""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from enrichment import icc_feeds
    from shared import CRICSHEET_URLS, IngestionJobInput
    from ingestion_workflow import CricsheetIngestionWorkflow
    from activities import (
        enrich_from_wikidata,
        fetch_icc_feed,
        fetch_icc_fixtures,
        sync_people_register,
    )

# How far either side of today the daily fixtures sync reaches. Backwards to
# pick up results that landed after a match finished; forwards for the schedule.
FIXTURE_WINDOW_PAST_DAYS = 120
FIXTURE_WINDOW_FUTURE_DAYS = 365

# Which Cricsheet archives the daily job refreshes. Every configured one --
# listing them from CRICSHEET_URLS rather than repeating the names means adding
# a league is still a one-line change in shared.py.
DAILY_COMPETITIONS = sorted(CRICSHEET_URLS)


@workflow.defn
class IccRankingsWorkflow:
    """Fetches every ICC ranking feed. Registered to run daily.

    ICC republishes ratings only every week or so, but rank_date is part of the
    primary key, so a daily run that finds nothing new simply rewrites the same
    snapshot -- idempotent, and it means a new publication is picked up within
    a day of appearing rather than whenever someone remembers to run it.
    """

    @workflow.run
    async def run(self) -> str:
        feeds = icc_feeds()
        results = await asyncio.gather(
            *[self._fetch_one(comp, typ) for comp, typ in feeds]
        )
        ok = [r for r in results if r is not None]
        stored = sum(r.get("stored", 0) for r in ok)
        linked = sum(r.get("linked", 0) for r in ok)
        failed = len(results) - len(ok)
        empty = [f"{r['comp_type']}/{r['type']}" for r in ok if not r.get("stored")]
        return (
            f"ICC rankings: {len(ok)}/{len(feeds)} feeds, {stored} rows stored, "
            f"{linked} linked to players, {failed} failed"
            + (f", empty: {', '.join(empty)}" if empty else "")
        )

    async def _fetch_one(self, comp_type: str, feed_type: str) -> dict | None:
        try:
            return await workflow.execute_activity(
                fetch_icc_feed,
                args=[comp_type, feed_type],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            workflow.logger.warning(f"icc feed {comp_type}/{feed_type} failed")
            return None


@workflow.defn
class IccFixturesWorkflow:
    """Syncs the fixtures window: recent results plus the upcoming schedule.

    Dates come from `workflow.now()` rather than datetime.now() so the workflow
    stays deterministic and replays identically.
    """

    @workflow.run
    async def run(self, past_days: int = FIXTURE_WINDOW_PAST_DAYS,
                  future_days: int = FIXTURE_WINDOW_FUTURE_DAYS) -> str:
        today = workflow.now().date()
        from_date = (today - timedelta(days=past_days)).strftime("%Y%m%d")
        to_date = (today + timedelta(days=future_days)).strftime("%Y%m%d")
        result = await workflow.execute_activity(
            fetch_icc_fixtures,
            args=[from_date, to_date],
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return (
            f"fixtures {from_date}–{to_date}: {result['stored']} written, "
            f"{result['skipped']} unchanged (of {result['feed_total']} in feed)"
        )


@workflow.defn
class IccDailySyncWorkflow:
    """The scheduled daily job: ICC rankings, ICC fixtures, and Cricsheet.

    One schedule rather than three, because they share a cadence; each part
    still fails independently (return_exceptions), so a bad ICC feed cannot
    stop match ingestion and vice versa.

    The three sources move at genuinely different speeds, and running them on
    one daily tick is what keeps that from mattering:

    * ICC fixtures change hourly during play (a scoreline landing).
    * ICC rankings republish roughly weekly.
    * Cricsheet publishes match archives in bulk every few days -- so the
      Cricsheet leg mostly gets a 304 and costs nothing. It is scheduled
      anyway because the alternative is noticing by hand, and a new archive
      then sits uningested for however long that takes.

    Cricsheet runs sequentially after the ICC legs rather than alongside them:
    the archives share one SQLite file with everything else, and a bulk ingest
    is the one job here heavy enough to be worth not overlapping.
    """

    @workflow.run
    async def run(self, competitions: list[str] | None = None) -> str:
        rankings, fixtures = await asyncio.gather(
            workflow.execute_child_workflow(
                IccRankingsWorkflow.run, id=f"{workflow.info().workflow_id}-rankings"
            ),
            workflow.execute_child_workflow(
                IccFixturesWorkflow.run, id=f"{workflow.info().workflow_id}-fixtures"
            ),
            return_exceptions=True,
        )
        parts = [
            r if isinstance(r, str) else f"FAILED: {type(r).__name__}"
            for r in (rankings, fixtures)
        ]

        for competition in competitions if competitions is not None else DAILY_COMPETITIONS:
            try:
                result = await workflow.execute_child_workflow(
                    CricsheetIngestionWorkflow.run,
                    IngestionJobInput(competition=competition, archive_path="", match_ids=[]),
                    id=f"{workflow.info().workflow_id}-{competition}",
                )
                parts.append(str(result))
            except Exception as e:  # noqa: BLE001 - one archive must not sink the rest
                workflow.logger.warning(f"cricsheet {competition} failed: {e!r}")
                parts.append(f"{competition}: FAILED {type(e).__name__}")

        return " | ".join(parts)


@workflow.defn
class PlayerEnrichmentWorkflow:
    """Crosswalk from Cricsheet's register, then bio fields from Wikidata.

    Ordered, not parallel: the Wikidata step joins on cricinfo_id, so it has
    nothing to query until the register step has populated it.
    """

    @workflow.run
    async def run(self) -> str:
        linked = await workflow.execute_activity(
            sync_people_register,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        stats = await workflow.execute_activity(
            enrich_from_wikidata,
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return (
            f"cricinfo_id set for {linked} players; "
            f"wikidata matched {stats['matched']}/{stats['queried']} "
            f"across {stats['batches']} batches "
            f"({stats['retirement_dates']} with a sourced retirement date)"
        )
