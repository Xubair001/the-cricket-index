"""Registers the daily ICC sync schedule (rankings + fixtures).

A Temporal Schedule rather than system cron: the worker and server are already
required to run anything here, schedule state is visible in the same Web UI as
every other workflow, and a missed window is recoverable rather than silently
lost. Run once (re-running is safe -- it updates the existing schedule):

    cd ingestion && python schedule.py            # create/update
    cd ingestion && python schedule.py --delete   # remove
"""
import asyncio
import sys

from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleCalendarSpec,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
    ScheduleUpdate,
)

from shared import TASK_QUEUE
from enrichment_workflow import IccDailySyncWorkflow
from news_workflow import NewsSyncWorkflow

SCHEDULE_ID = "icc-daily-sync"

# News is a SEPARATE schedule from the ICC/Cricsheet one, not another leg of
# it. Two reasons, and both are about cadence rather than tidiness:
#
#  * News moves hourly. Cricsheet republishes every few days and ICC ratings
#    weekly, so the 06:00 job is right for them and far too slow for a feed
#    whose whole value is being current.
#  * They must fail independently. A publisher blocking us should not put a
#    red mark on the workflow that ingests match data, and a Cricsheet
#    archive taking twenty minutes should not delay the news window.
NEWS_SCHEDULE_ID = "news-sync"
# Every three hours. The RSS windows hold 20 to 100 items and the busiest
# (ESPNcricinfo) turns over roughly daily, so three hours cannot miss an
# article, while eight daily passes across four publishers is a trivial load
# for any of them - and most of those passes cost one 304 per feed.
NEWS_INTERVAL_HOURS = 3
# 06:00 local. ICC publishes new ratings roughly weekly and at no fixed hour, so
# the exact time matters little -- what matters is checking every day so a new
# publication is picked up within 24h.
RUN_HOUR = 6


async def _upsert(client: Client, schedule_id: str, schedule: Schedule, label: str) -> None:
    handle = client.get_schedule_handle(schedule_id)
    try:
        await client.create_schedule(schedule_id, schedule)
        print(f"Created schedule '{schedule_id}' - {label}")
    except ScheduleAlreadyRunningError:
        # The callback must return a ScheduleUpdate, not a Schedule. Handing
        # it the Schedule directly raises an AssertionError deep in the SDK,
        # and only on the update path - so a first `python schedule.py` on a
        # clean server succeeds and every re-run after that fails, which the
        # docstring's "re-running is safe" promise depends on.
        await handle.update(lambda _: ScheduleUpdate(schedule=schedule))
        print(f"Updated existing schedule '{schedule_id}' - {label}")
    desc = await handle.describe()
    print(f"  next run: {desc.info.next_action_times[:1]}")
    print(f"  view it at http://localhost:8233/namespaces/default/schedules/{schedule_id}")


async def main() -> None:
    client = await Client.connect("localhost:7233")
    handle = client.get_schedule_handle(SCHEDULE_ID)

    if "--delete" in sys.argv:
        for schedule_id in (SCHEDULE_ID, NEWS_SCHEDULE_ID):
            try:
                await client.get_schedule_handle(schedule_id).delete()
                print(f"Deleted schedule '{schedule_id}'")
            except Exception as e:
                print(f"Nothing to delete for '{schedule_id}' ({e})")
        return

    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            IccDailySyncWorkflow.run,
            id="icc-daily-sync-scheduled",
            task_queue=TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    hour=[ScheduleRange(RUN_HOUR)],
                    minute=[ScheduleRange(0)],
                )
            ]
        ),
        # If yesterday's run is somehow still going, skip rather than stack up.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    await _upsert(client, SCHEDULE_ID, schedule, f"runs daily at {RUN_HOUR:02d}:00")

    news_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            NewsSyncWorkflow.run,
            id="news-sync-scheduled",
            task_queue=TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(hours=NEWS_INTERVAL_HOURS))]
        ),
        # SKIP rather than BUFFER_ONE: if a run is still going when the next
        # is due, the publishers have not produced three hours of new articles
        # in the meantime, and stacking runs would only mean two workflows
        # racing for the same pending ledger rows.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    await _upsert(
        client, NEWS_SCHEDULE_ID, news_schedule,
        f"runs every {NEWS_INTERVAL_HOURS}h",
    )


if __name__ == "__main__":
    asyncio.run(main())
