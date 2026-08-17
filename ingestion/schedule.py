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

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)

from shared import TASK_QUEUE
from enrichment_workflow import IccDailySyncWorkflow

SCHEDULE_ID = "icc-daily-sync"
# 06:00 local. ICC publishes new ratings roughly weekly and at no fixed hour, so
# the exact time matters little -- what matters is checking every day so a new
# publication is picked up within 24h.
RUN_HOUR = 6


async def main() -> None:
    client = await Client.connect("localhost:7233")
    handle = client.get_schedule_handle(SCHEDULE_ID)

    if "--delete" in sys.argv:
        try:
            await handle.delete()
            print(f"Deleted schedule '{SCHEDULE_ID}'")
        except Exception as e:
            print(f"Nothing to delete ({e})")
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

    try:
        await client.create_schedule(SCHEDULE_ID, schedule)
        print(f"Created schedule '{SCHEDULE_ID}' - runs daily at {RUN_HOUR:02d}:00")
    except ScheduleAlreadyRunningError:
        await handle.update(lambda _: schedule)
        print(f"Updated existing schedule '{SCHEDULE_ID}' - daily at {RUN_HOUR:02d}:00")

    desc = await handle.describe()
    print(f"  next run: {desc.info.next_action_times[:1]}")
    print(f"  view it at http://localhost:8233/namespaces/default/schedules/{SCHEDULE_ID}")


if __name__ == "__main__":
    asyncio.run(main())
