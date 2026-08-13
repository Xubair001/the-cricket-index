"""Workflows for the two non-Cricsheet data sources.

Both are separate from CricsheetIngestionWorkflow on purpose: they run on their
own cadence (ICC daily, Wikidata rarely), they fail independently, and neither
should be able to hold up or corrupt a match ingest.
"""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from enrichment import icc_feeds
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
    """The scheduled daily job: rankings and fixtures together.

    One schedule rather than two, because they share a cadence and a source;
    each half still fails independently.
    """

    @workflow.run
    async def run(self) -> str:
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
