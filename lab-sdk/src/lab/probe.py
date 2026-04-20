"""Storage probe: write a sentinel file to the configured storage root.

Run as: python -m lab.probe

Env vars (injected by launch_template.py):
  _TFL_JOB_ID          -- unique id for this probe run
  TFL_STORAGE_URI      -- org-scoped workspace path (localfs or cloud URI)
  TFL_STORAGE_PROVIDER -- storage provider type
"""

import asyncio
import json
import os
import time

from lab import lab as tfl, storage


_PROBE_SUBDIR = "debug"


async def _run() -> None:
    job_id = os.environ.get("_TFL_JOB_ID", "unknown")

    # TFL_STORAGE_URI is already the org-scoped workspace path on the worker.
    # Fall back to get_workspace_dir() only in environments without it (e.g. local testing).
    storage_uri = os.environ.get("TFL_STORAGE_URI")
    if storage_uri:
        workspace = storage_uri
    else:
        from lab.dirs import get_workspace_dir

        workspace = await get_workspace_dir()

    probe_dir = storage.join(workspace, _PROBE_SUBDIR)
    await storage.makedirs(probe_dir, exist_ok=True)

    sentinel_path = storage.join(probe_dir, f"storage-probe-{job_id}.txt")
    payload = json.dumps(
        {
            "job_id": job_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "storage_uri": workspace,
            "storage_provider": os.environ.get("TFL_STORAGE_PROVIDER", ""),
        }
    )

    async with await storage.open(sentinel_path, "w") as f:
        await f.write(payload)

    print(f"[storage-probe] sentinel written to: {sentinel_path}", flush=True)


def main() -> None:
    tfl.init()
    asyncio.run(_run())
    tfl.finish()


if __name__ == "__main__":
    main()
