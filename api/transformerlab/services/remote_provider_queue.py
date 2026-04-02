import asyncio
import logging
import os
from typing import Optional

from pydantic import BaseModel

from transformerlab.compute_providers.models import ClusterConfig
from transformerlab.db.session import async_session
from transformerlab.services import job_service, quota_service
from transformerlab.services.provider_service import get_provider_by_id, get_provider_instance
from lab import Experiment, dirs as lab_dirs
from lab.dirs import set_organization_id as lab_set_org_id
from lab.job_status import JobStatus

logger = logging.getLogger(__name__)


class RemoteLaunchWorkItem(BaseModel):
    """Work item for launching a non-local provider job in the background."""

    job_id: str
    experiment_id: str
    provider_id: str
    team_id: str
    user_id: str
    cluster_name: str
    cluster_config: ClusterConfig
    quota_hold_id: Optional[str] = None
    subtype: Optional[str] = None  # e.g. "interactive"


# Concurrency: remote launches should start immediately, but we still cap total parallelism
try:
    _MAX_CONCURRENT_REMOTE_LAUNCHES = int(os.getenv("TFL_MAX_CONCURRENT_REMOTE_LAUNCHES", "8"))
except Exception:  # noqa: BLE001
    _MAX_CONCURRENT_REMOTE_LAUNCHES = 8

_remote_launch_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REMOTE_LAUNCHES)

_REMOTE_QUEUE_POLL_INTERVAL = float(os.environ.get("TFL_REMOTE_QUEUE_POLL_INTERVAL", "2"))

_remote_job_queue_worker_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# Public API - called by launch_template.py
# ---------------------------------------------------------------------------


async def enqueue_remote_launch(
    job_id: str,
    experiment_id: str,
    provider_id: str,
    team_id: str,
    user_id: str,
    cluster_name: str,
    cluster_config: ClusterConfig,
    quota_hold_id: Optional[str],
    subtype: Optional[str],
) -> None:
    """Mark a remote provider launch job as QUEUED_REMOTE in the DB.

    The leader's background worker will pick it up and process it.
    """
    await job_service.job_update_status(
        str(job_id),
        JobStatus.QUEUED_REMOTE,
        experiment_id=str(experiment_id),
    )
    print(f"[remote_provider_queue] Enqueued job {job_id} (cluster={cluster_name}, status=QUEUED_REMOTE)")


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
        logger.warning(f"Remote job queue worker: failed listing orgs: {exc}")
        return []


async def _list_experiment_ids_for_current_org():
    try:
        experiments_data = await Experiment.get_all()
    except Exception as exc:
        logger.warning(f"Remote job queue worker: failed listing experiments: {exc}")
        return []
    return [str(exp.get("id")) for exp in experiments_data if exp.get("id")]


async def _poll_queued_remote_jobs() -> list[dict]:
    """Find all QUEUED_REMOTE jobs across all orgs and experiments, oldest first."""
    all_jobs: list[dict] = []
    org_ids = await _list_all_org_ids()
    for org_id in org_ids:
        try:
            _set_org_context(org_id)
            experiment_ids = await _list_experiment_ids_for_current_org()
            for exp_id in experiment_ids:
                try:
                    jobs = await job_service.jobs_get_all(exp_id, type="", status=JobStatus.QUEUED_REMOTE)
                    all_jobs.extend(jobs)
                except Exception:
                    logger.exception(
                        "Remote job queue worker: error listing QUEUED_REMOTE jobs for experiment=%s", exp_id
                    )
        finally:
            _clear_org_context()
    # Sort oldest-first (FIFO).
    all_jobs.sort(key=job_service._sort_key_job_recency)
    return all_jobs


def _reconstruct_work_item(job: dict) -> Optional[RemoteLaunchWorkItem]:
    """Reconstruct a RemoteLaunchWorkItem from stored job data."""
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
    user_id = job_data.get("created_by_user_id", "")
    cluster_name = job_data.get("cluster_name")
    subtype = job_data.get("subtype")

    if not provider_id or not team_id or not cluster_name:
        logger.error(
            "Remote job queue worker: job %s missing required fields "
            "(provider_id=%s, team_id=%s, cluster_name=%s)",
            job_id,
            provider_id,
            team_id,
            cluster_name,
        )
        return None

    # Reconstruct ClusterConfig from stored cluster_config_dict.
    cluster_config_raw = job_data.get("cluster_config")
    if not cluster_config_raw or not isinstance(cluster_config_raw, dict):
        logger.error("Remote job queue worker: job %s missing cluster_config in job_data", job_id)
        return None

    try:
        cluster_config = ClusterConfig.model_validate(cluster_config_raw)
    except Exception as exc:
        logger.error("Remote job queue worker: job %s failed to parse cluster_config: %s", job_id, exc)
        return None

    quota_hold_id = job_data.get("quota_hold_id")

    return RemoteLaunchWorkItem(
        job_id=job_id,
        experiment_id=experiment_id,
        provider_id=str(provider_id),
        team_id=str(team_id),
        user_id=str(user_id),
        cluster_name=cluster_name,
        cluster_config=cluster_config,
        quota_hold_id=quota_hold_id,
        subtype=subtype,
    )


def _log_task_exception(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001
        logger.exception("Remote launch task failed while retrieving exception")
        return

    if exc is not None:
        logger.exception("Remote launch task crashed", exc_info=exc)


async def _remote_job_queue_worker_loop() -> None:
    """Long-running worker that polls DB for QUEUED_REMOTE jobs and dispatches them concurrently."""
    logger.info("Remote job queue worker: started")
    try:
        while True:
            try:
                queued_jobs = await _poll_queued_remote_jobs()
                if not queued_jobs:
                    await asyncio.sleep(_REMOTE_QUEUE_POLL_INTERVAL)
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

                    # Fire concurrently, bounded by semaphore.
                    task = asyncio.create_task(_process_launch_item(item))
                    task.add_done_callback(_log_task_exception)

                # After dispatching all found jobs, loop immediately to check for more.
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"Remote job queue worker: unhandled error in cycle, continuing: {exc}")
                await asyncio.sleep(_REMOTE_QUEUE_POLL_INTERVAL)
    except asyncio.CancelledError:
        logger.info("Remote job queue worker: stopping")
        raise
    finally:
        _clear_org_context()


async def start_remote_job_queue_worker() -> None:
    """Start the background remote job queue worker (idempotent)."""
    global _remote_job_queue_worker_task

    if _remote_job_queue_worker_task and not _remote_job_queue_worker_task.done():
        return

    _remote_job_queue_worker_task = asyncio.create_task(
        _remote_job_queue_worker_loop(), name="remote-job-queue-worker"
    )


async def stop_remote_job_queue_worker() -> None:
    """Cancel the background remote job queue worker."""
    global _remote_job_queue_worker_task

    if _remote_job_queue_worker_task and not _remote_job_queue_worker_task.done():
        _remote_job_queue_worker_task.cancel()
        try:
            await _remote_job_queue_worker_task
        except asyncio.CancelledError:
            pass
    _remote_job_queue_worker_task = None


# ---------------------------------------------------------------------------
# Launch logic (unchanged from original)
# ---------------------------------------------------------------------------


async def _process_launch_item(item: RemoteLaunchWorkItem) -> None:
    """Process a single remote launch work item."""
    async with _remote_launch_semaphore:
        async with async_session() as session:
            lab_dirs.set_organization_id(item.team_id)
            try:
                await job_service.job_update_launch_progress(
                    item.job_id,
                    item.experiment_id,
                    phase="launching_cluster",
                    percent=70,
                    message="Launching cluster",
                )

                provider = await get_provider_by_id(session, item.provider_id)
                if not provider:
                    await job_service.job_update_status(
                        item.job_id,
                        JobStatus.FAILED,
                        experiment_id=item.experiment_id,
                        error_msg="Provider not found for remote launch",
                        session=session,
                    )
                    if item.quota_hold_id:
                        await quota_service.release_quota_hold(session, hold_id=item.quota_hold_id)
                        await session.commit()
                    return

                provider_instance = await get_provider_instance(provider, user_id=item.user_id, team_id=item.team_id)

                loop = asyncio.get_running_loop()

                def _launch_with_org_context():
                    lab_dirs.set_organization_id(item.team_id)
                    return provider_instance.launch_cluster(item.cluster_name, item.cluster_config)

                try:
                    launch_result = await loop.run_in_executor(None, _launch_with_org_context)
                except Exception as exc:  # noqa: BLE001
                    await job_service.job_update_launch_progress(
                        item.job_id,
                        item.experiment_id,
                        phase="failed",
                        percent=100,
                        message=f"Launch failed: {exc!s}",
                    )
                    if item.quota_hold_id:
                        await quota_service.release_quota_hold(session, hold_id=item.quota_hold_id)
                    await job_service.job_update_status(
                        item.job_id,
                        JobStatus.FAILED,
                        experiment_id=item.experiment_id,
                        error_msg=str(exc),
                        session=session,
                    )
                    await session.commit()
                    return

                await job_service.job_update_launch_progress(
                    item.job_id,
                    item.experiment_id,
                    phase="cluster_started",
                    percent=99,
                    message="Launch initiated",
                )

                if isinstance(launch_result, dict):
                    await job_service.job_update_job_data_insert_key_value(
                        item.job_id,
                        "provider_launch_result",
                        launch_result,
                        item.experiment_id,
                    )
                    request_id = launch_result.get("request_id")
                    if request_id:
                        await job_service.job_update_job_data_insert_key_value(
                            item.job_id,
                            "orchestrator_request_id",
                            request_id,
                            item.experiment_id,
                        )

                # Keep the job in LAUNCHING/INTERACTIVE; status polling will advance it later.
                next_status = JobStatus.INTERACTIVE if item.subtype == "interactive" else JobStatus.LAUNCHING
                await job_service.job_update_status(
                    item.job_id,
                    next_status,
                    experiment_id=item.experiment_id,
                    session=session,
                )
                await session.commit()
            finally:
                lab_dirs.set_organization_id(None)
