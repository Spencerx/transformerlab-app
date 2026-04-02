import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from pydantic import BaseModel

from transformerlab.compute_providers.models import ClusterConfig
from transformerlab.services import job_service, quota_service
from transformerlab.services.provider_service import get_provider_by_id, get_provider_instance
from transformerlab.db.session import async_session
from lab import Experiment, dirs as lab_dirs
from lab.dirs import set_organization_id as lab_set_org_id
from lab.job_status import JobStatus

logger = logging.getLogger(__name__)


class LocalLaunchWorkItem(BaseModel):
    """Work item for launching a local provider job in the background."""

    job_id: str
    experiment_id: str
    provider_id: str
    team_id: str
    cluster_name: str
    cluster_config: ClusterConfig
    quota_hold_id: Optional[str] = None
    initial_status: str  # e.g. "LAUNCHING" or "INTERACTIVE"


_worker_lock = asyncio.Lock()

# Dedicated thread pool for launch_cluster operations so long-running subprocess
# calls (uv pip install can take 15+ min) don't starve the default executor used
# by the rest of the server for DB queries, file I/O, etc.
_LAUNCH_MAX_WORKERS = int(os.environ.get("TFL_LAUNCH_MAX_WORKERS", "2"))
_launch_executor = ThreadPoolExecutor(max_workers=_LAUNCH_MAX_WORKERS, thread_name_prefix="local-launch")

_LOCAL_QUEUE_POLL_INTERVAL = float(os.environ.get("TFL_LOCAL_QUEUE_POLL_INTERVAL", "2"))

_local_job_queue_worker_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# Public API - called by launch_template.py
# ---------------------------------------------------------------------------


async def enqueue_local_launch(
    job_id: str,
    experiment_id: str,
    provider_id: str,
    team_id: str,
    cluster_name: str,
    cluster_config: ClusterConfig,
    quota_hold_id: Optional[str],
    initial_status: str,
) -> None:
    """Mark a local provider launch job as QUEUED_LOCAL in the DB.

    The leader's background worker will pick it up and process it.
    """
    await job_service.job_update_status(
        str(job_id),
        JobStatus.QUEUED_LOCAL,
        experiment_id=str(experiment_id),
    )
    print(f"[local_provider_queue] Enqueued job {job_id} (cluster={cluster_name}, status=QUEUED_LOCAL)")


# ---------------------------------------------------------------------------
# Background worker - started only by the leader process
# ---------------------------------------------------------------------------


def _set_org_context(org_id: Optional[str]) -> None:
    lab_set_org_id(org_id)


def _clear_org_context() -> None:
    _set_org_context(None)


async def _list_all_org_ids():
    from transformerlab.services import team_service

    try:
        return await team_service.get_all_team_ids()
    except Exception as exc:
        logger.warning(f"Local job queue worker: failed listing orgs: {exc}")
        return []


async def _list_experiment_ids_for_current_org():
    try:
        experiments_data = await Experiment.get_all()
    except Exception as exc:
        logger.warning(f"Local job queue worker: failed listing experiments: {exc}")
        return []
    return [str(exp.get("id")) for exp in experiments_data if exp.get("id")]


async def _poll_queued_local_jobs() -> list[dict]:
    """Find all QUEUED_LOCAL jobs across all orgs and experiments, oldest first."""
    all_jobs: list[dict] = []
    org_ids = await _list_all_org_ids()
    for org_id in org_ids:
        try:
            _set_org_context(org_id)
            experiment_ids = await _list_experiment_ids_for_current_org()
            for exp_id in experiment_ids:
                try:
                    jobs = await job_service.jobs_get_all(exp_id, type="", status=JobStatus.QUEUED_LOCAL)
                    all_jobs.extend(jobs)
                except Exception:
                    logger.exception(
                        "Local job queue worker: error listing QUEUED_LOCAL jobs for experiment=%s", exp_id
                    )
        finally:
            _clear_org_context()
    # Sort oldest-first (FIFO).
    all_jobs.sort(key=job_service._sort_key_job_recency)
    return all_jobs


def _reconstruct_work_item(job: dict) -> Optional[LocalLaunchWorkItem]:
    """Reconstruct a LocalLaunchWorkItem from stored job data."""
    import json as _json

    job_data = job.get("job_data") or {}
    if isinstance(job_data, str):
        try:
            job_data = _json.loads(job_data)
        except Exception:
            job_data = {}

    job_id = str(job.get("id", ""))
    experiment_id = str(job.get("experiment_id", ""))
    provider_id = job_data.get("provider_id")
    team_id = job_data.get("team_id")
    cluster_name = job_data.get("cluster_name")
    subtype = job_data.get("subtype")

    if not provider_id or not team_id or not cluster_name:
        logger.error(
            "Local job queue worker: job %s missing required fields (provider_id=%s, team_id=%s, cluster_name=%s)",
            job_id,
            provider_id,
            team_id,
            cluster_name,
        )
        return None

    # Reconstruct ClusterConfig from stored cluster_config_dict.
    cluster_config_raw = job_data.get("cluster_config")
    if not cluster_config_raw or not isinstance(cluster_config_raw, dict):
        logger.error("Local job queue worker: job %s missing cluster_config in job_data", job_id)
        return None

    try:
        cluster_config = ClusterConfig.model_validate(cluster_config_raw)
    except Exception as exc:
        logger.error("Local job queue worker: job %s failed to parse cluster_config: %s", job_id, exc)
        return None

    initial_status = job_data.get("initial_status")
    if not initial_status:
        initial_status = JobStatus.INTERACTIVE if subtype == "interactive" else JobStatus.LAUNCHING

    quota_hold_id = job_data.get("quota_hold_id")

    return LocalLaunchWorkItem(
        job_id=job_id,
        experiment_id=experiment_id,
        provider_id=str(provider_id),
        team_id=str(team_id),
        cluster_name=cluster_name,
        cluster_config=cluster_config,
        quota_hold_id=quota_hold_id,
        initial_status=str(initial_status),
    )


async def _local_job_queue_worker_loop() -> None:
    """Long-running worker that polls DB for QUEUED_LOCAL jobs and processes them serially."""
    logger.info("Local job queue worker: started")
    try:
        while True:
            try:
                queued_jobs = await _poll_queued_local_jobs()
                if not queued_jobs:
                    await asyncio.sleep(_LOCAL_QUEUE_POLL_INTERVAL)
                    continue

                for job in queued_jobs:
                    job_id = str(job.get("id", ""))
                    experiment_id = str(job.get("experiment_id", ""))
                    item = _reconstruct_work_item(job)
                    if item is None:
                        await job_service.job_update_status(
                            job_id,
                            JobStatus.FAILED,
                            experiment_id=experiment_id,
                            error_msg="Failed to reconstruct launch work item from job data - "
                            "required fields (provider_id, team_id, cluster_name, cluster_config) may be missing.",
                        )
                        continue

                    print(f"[local_provider_queue] Picked up job {item.job_id} (cluster={item.cluster_name})")
                    try:
                        await _process_launch_item(item)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[local_provider_queue] Job {item.job_id}: unexpected error: {exc}")
                # After processing all found jobs, loop immediately to check for more.
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"Local job queue worker: unhandled error in cycle, continuing: {exc}")
                await asyncio.sleep(_LOCAL_QUEUE_POLL_INTERVAL)
    except asyncio.CancelledError:
        logger.info("Local job queue worker: stopping")
        raise
    finally:
        _clear_org_context()


async def start_local_job_queue_worker() -> None:
    """Start the background local job queue worker (idempotent)."""
    global _local_job_queue_worker_task

    if _local_job_queue_worker_task and not _local_job_queue_worker_task.done():
        return

    _local_job_queue_worker_task = asyncio.create_task(_local_job_queue_worker_loop(), name="local-job-queue-worker")


async def stop_local_job_queue_worker() -> None:
    """Cancel the background local job queue worker."""
    global _local_job_queue_worker_task

    if _local_job_queue_worker_task and not _local_job_queue_worker_task.done():
        _local_job_queue_worker_task.cancel()
        try:
            await _local_job_queue_worker_task
        except asyncio.CancelledError:
            pass
    _local_job_queue_worker_task = None


# ---------------------------------------------------------------------------
# Launch logic (unchanged from original)
# ---------------------------------------------------------------------------


async def _process_launch_item(item: LocalLaunchWorkItem) -> None:
    """Process a single local launch work item."""
    async with async_session() as session:
        lab_dirs.set_organization_id(item.team_id)
        try:
            # Initial progress update - make it clear we're preparing the local environment.
            await job_service.job_update_launch_progress(
                item.job_id,
                item.experiment_id,
                phase="starting",
                percent=5,
                message="Preparing local environment (this may take a few minutes)...",
            )
            provider = await get_provider_by_id(session, item.provider_id)
            if not provider:
                print(f"[local_provider_queue] Provider {item.provider_id} not found, job {item.job_id} FAILED")
                await job_service.job_update_status(
                    item.job_id,
                    JobStatus.FAILED,
                    experiment_id=item.experiment_id,
                    error_msg="Provider not found for local launch",
                    session=session,
                )
                if item.quota_hold_id:
                    await quota_service.release_quota_hold(session, hold_id=item.quota_hold_id)
                    await session.commit()
                return

            provider_instance = await get_provider_instance(provider)

            # Transition from QUEUED_LOCAL -> initial_status (LAUNCHING / INTERACTIVE)
            print(f"[local_provider_queue] Job {item.job_id}: transitioning to {item.initial_status}")
            await job_service.job_update_status(
                item.job_id,
                item.initial_status,
                experiment_id=item.experiment_id,
                session=session,
            )
            await session.commit()

            # Indicate we're about to launch the local cluster
            await job_service.job_update_launch_progress(
                item.job_id,
                item.experiment_id,
                phase="launching_cluster",
                percent=50,
                message="Setting up local provider and starting cluster...",
            )

            loop = asyncio.get_running_loop()

            # Capture the team_id so the callback can restore the org context
            # on the coroutine it schedules (contextvars don't propagate via
            # run_coroutine_threadsafe).
            team_id = item.team_id

            async def _update_live_status(status: str) -> None:
                lab_dirs.set_organization_id(team_id)
                try:
                    await job_service.job_update_job_data_insert_key_value(
                        item.job_id, "live_status", status, item.experiment_id
                    )
                finally:
                    lab_dirs.set_organization_id(None)

            def _on_status(status: str) -> None:
                """Callback invoked from the executor thread to update live_status."""
                future = asyncio.run_coroutine_threadsafe(_update_live_status(status), loop)
                try:
                    future.result(timeout=5)
                except Exception:
                    pass

            try:
                # Ensure only one local launch runs at a time
                def _launch_with_org_context():
                    lab_dirs.set_organization_id(item.team_id)
                    return provider_instance.launch_cluster(
                        item.cluster_name, item.cluster_config, on_status=_on_status
                    )

                async with _worker_lock:
                    launch_result = await loop.run_in_executor(_launch_executor, _launch_with_org_context)
            except Exception as exc:  # noqa: BLE001
                print(f"[local_provider_queue] Job {item.job_id}: launch_cluster failed: {exc}")
                # Release quota hold and mark job failed
                if item.quota_hold_id:
                    await quota_service.release_quota_hold(session, hold_id=item.quota_hold_id)
                    await session.commit()

                await job_service.job_update_status(
                    item.job_id,
                    JobStatus.FAILED,
                    experiment_id=item.experiment_id,
                    error_msg=str(exc),
                    session=session,
                )
                await session.commit()
                return

            print(f"[local_provider_queue] Job {item.job_id}: cluster started successfully - {launch_result}")
            # On success, we keep the job in LAUNCHING/INTERACTIVE; status checks will
            # complete it when the local process exits. We just bump progress.
            await job_service.job_update_launch_progress(
                item.job_id,
                item.experiment_id,
                phase="cluster_running",
                percent=100,
                message="Local cluster started",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[local_provider_queue] Job {item.job_id}: unexpected error while processing launch item: {exc}")
            if item.quota_hold_id:
                await quota_service.release_quota_hold(session, hold_id=item.quota_hold_id)
                await session.commit()

            await job_service.job_update_status(
                item.job_id,
                JobStatus.FAILED,
                experiment_id=item.experiment_id,
                error_msg=str(exc),
                session=session,
            )
            await session.commit()
        finally:
            lab_dirs.set_organization_id(None)
