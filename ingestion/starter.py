import asyncio
import sys

from temporalio.client import Client

from shared import TASK_QUEUE, IngestionJobInput
from ingestion_workflow import CricsheetIngestionWorkflow


async def main() -> None:
    competition = sys.argv[1] if len(sys.argv) > 1 else "tests"

    client = await Client.connect("localhost:7233")

    handle = await client.start_workflow(
        CricsheetIngestionWorkflow.run,
        IngestionJobInput(competition=competition, archive_path="", match_ids=[]),
        id=f"cricsheet-ingest-{competition}",
        task_queue=TASK_QUEUE,
    )
    print(f"Started ingestion workflow: {handle.id}")
    print(f"View it at http://localhost:8233/namespaces/default/workflows/{handle.id}")

    result = await handle.result()
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
