"""Router for cluster management endpoints."""

import asyncio
import logging
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from transformerlab.shared.models.user_model import get_async_session
from transformerlab.routers.auth import get_user_and_team
from transformerlab.services.provider_service import get_team_provider, get_provider_instance
from transformerlab.shared.models.models import ProviderType
from transformerlab.compute_providers.models import (
    ClusterStatus,
    ResourceInfo,
    JobConfig,
    JobInfo,
    JobState,
)
from lab.dirs import get_local_provider_job_dir, resolve_local_provider_job_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("/")
async def list_clusters_detailed(
    provider_id: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get detailed list of clusters for a provider, including nodes and resources.
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # Get detailed clusters
        clusters = await asyncio.to_thread(provider_instance.get_clusters_detailed)

        return clusters
    except Exception as e:
        print(f"Failed to list clusters: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list clusters")


@router.get("/{cluster_name}/status", response_model=ClusterStatus)
async def get_cluster_status(
    provider_id: str,
    cluster_name: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get the status of a cluster.
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # Get cluster status
        status = await asyncio.to_thread(provider_instance.get_cluster_status, cluster_name)

        return status
    except Exception as e:
        print(f"Failed to get cluster status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get cluster status")


@router.get("/{cluster_name}/resources", response_model=ResourceInfo)
async def get_cluster_resources(
    provider_id: str,
    cluster_name: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get resource information for a cluster (GPUs, CPUs, memory, etc.).
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # Get cluster resources
        resources = await asyncio.to_thread(provider_instance.get_cluster_resources, cluster_name)

        return resources
    except Exception as e:
        print(f"Failed to get cluster resources: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get cluster resources")


@router.post("/{cluster_name}/stop")
async def stop_cluster(
    provider_id: str,
    cluster_name: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Stop a running cluster (but don't tear it down).
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # Local provider needs workspace_dir (job dir) to stop the correct process tree.
        # Cluster names include a short id suffix ("-job-<short_id>"), while local
        # provider run directories use the full job id. Resolve by exact/unique prefix
        # without creating new directories.
        if provider.type == ProviderType.LOCAL.value and hasattr(provider_instance, "extra_config"):
            job_id_segment = None
            if "-job-" in cluster_name:
                job_id_segment = cluster_name.rsplit("-job-", 1)[-1] or None
            if job_id_segment is not None:
                job_dir = await asyncio.to_thread(resolve_local_provider_job_dir, job_id_segment, org_id=team_id)
                if job_dir:
                    provider_instance.extra_config["workspace_dir"] = job_dir

        # Stop cluster
        result = await asyncio.to_thread(provider_instance.stop_cluster, cluster_name)

        # Return the result directly from the provider
        return result
    except Exception as e:
        print(f"Failed to stop cluster: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to stop cluster")


@router.post("/{cluster_name}/jobs")
async def submit_job(
    provider_id: str,
    cluster_name: str,
    job_config: JobConfig,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Submit a job to an existing cluster.
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # Submit job
        result = await asyncio.to_thread(provider_instance.submit_job, cluster_name, job_config)

        # Extract job_id from result
        job_id = result.get("job_id") or result.get("request_id")

        return {
            "status": "success",
            "message": "Job submitted successfully",
            "job_id": job_id,
            "cluster_name": cluster_name,
            "result": result,
        }
    except NotImplementedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Failed to submit job: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to submit job")


@router.get("/{cluster_name}/jobs", response_model=List[JobInfo])
async def list_jobs(
    provider_id: str,
    cluster_name: str,
    state: Optional[JobState] = Query(None, description="Filter jobs by state"),
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    List all jobs for a cluster.
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # List jobs
        jobs = await asyncio.to_thread(provider_instance.list_jobs, cluster_name)

        # Filter by state if provided
        if state:
            jobs = [job for job in jobs if job.state == state]

        return jobs
    except NotImplementedError:
        # Provider doesn't support listing jobs (e.g., Runpod)
        return []
    except Exception as e:
        print(f"Failed to list jobs: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list jobs")


@router.get("/{cluster_name}/jobs/{job_id}", response_model=JobInfo)
async def get_job_info(
    provider_id: str,
    cluster_name: str,
    job_id: Union[str, int],
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get information about a specific job.
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # List jobs and find the specific one
        try:
            jobs = await asyncio.to_thread(provider_instance.list_jobs, cluster_name)
        except NotImplementedError:
            # Provider doesn't support listing jobs (e.g., Runpod)
            raise HTTPException(
                status_code=400,
                detail="This provider does not support job listing. Runpod uses pod-based execution, not a job queue.",
            )

        # Convert job_id to appropriate type for comparison
        job_id_str = str(job_id)
        job_id_int = int(job_id) if isinstance(job_id, str) and job_id.isdigit() else job_id

        # Find job by ID (try both string and int comparison)
        job = None
        for j in jobs:
            if str(j.job_id) == job_id_str or j.job_id == job_id_int:
                job = j
                break

        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

        return job
    except HTTPException:
        raise
    except Exception as e:
        print(f"Failed to get job info: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get job info")


@router.get("/{cluster_name}/jobs/{job_id}/logs")
async def get_job_logs(
    provider_id: str,
    cluster_name: str,
    job_id: Union[str, int],
    tail_lines: Optional[int] = Query(None, description="Number of lines to retrieve from the end"),
    follow: bool = Query(False, description="Whether to stream/follow logs"),
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get logs for a job.
    Requires X-Team-Id header and team membership.

    If follow=true, returns a streaming response (Server-Sent Events).
    Otherwise, returns the full log content as text.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # Local provider needs workspace_dir (job dir) to read logs
        if provider.type == ProviderType.LOCAL.value and hasattr(provider_instance, "extra_config"):
            job_dir = await asyncio.to_thread(get_local_provider_job_dir, job_id, org_id=team_id)
            provider_instance.extra_config["workspace_dir"] = job_dir

        # Get job logs
        try:
            logs = await asyncio.to_thread(
                provider_instance.get_job_logs,
                cluster_name,
                job_id,
                tail_lines=tail_lines,
                follow=follow,
            )
        except NotImplementedError:
            # Provider doesn't support job logs (though Runpod returns a string message, not NotImplementedError)
            logs = "Logs not available for this provider type."

        if follow:
            # Return streaming response
            # If logs is already an iterator/stream, use it directly
            if hasattr(logs, "__iter__") and not isinstance(logs, (str, bytes)):

                async def generate():
                    try:
                        for line in logs:
                            if isinstance(line, bytes):
                                text = line.decode("utf-8", errors="replace")
                            else:
                                text = str(line) + "\n"

                            if text.startswith("Error reading logs:"):
                                yield "Failed to retrieve logs.\n"
                                break
                            elif text and not text.startswith("Error reading logs:"):
                                yield text
                    except Exception as e:
                        print(f"Error streaming logs: {str(e)}")
                        yield "\n[Error streaming logs]\n"

                return StreamingResponse(
                    generate(),
                    media_type="text/plain",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            else:
                # Fallback: convert to string and stream line by line
                log_str = str(logs) if logs else ""

                async def generate():
                    for line in log_str.split("\n"):
                        if line.startswith("Error reading logs:"):
                            yield "Failed to retrieve logs.\n"
                            break
                        elif line:
                            yield line + "\n"

                return StreamingResponse(
                    generate(),
                    media_type="text/plain",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
        else:
            # Return full log content as text
            log_content = str(logs) if logs else ""
            # Suppress internal error details from provider
            if log_content.startswith("Error reading logs:"):
                # Optionally log or record the internal error here server-side.
                return "Failed to retrieve logs."

            return log_content
    except Exception as e:
        print(f"Failed to get job logs: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get job logs")


@router.delete("/{cluster_name}/jobs/{job_id}")
async def cancel_job(
    provider_id: str,
    cluster_name: str,
    job_id: Union[str, int],
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Cancel a running or queued job.
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        user_id_str = str(user_and_team["user"].id)
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # Local provider needs workspace_dir (job dir) to cancel the correct process
        if provider.type == ProviderType.LOCAL.value and hasattr(provider_instance, "extra_config"):
            job_dir = await asyncio.to_thread(get_local_provider_job_dir, job_id, org_id=team_id)
            provider_instance.extra_config["workspace_dir"] = job_dir

        # Cancel job
        result = await asyncio.to_thread(provider_instance.cancel_job, cluster_name, job_id)

        return {
            "status": "success",
            "message": "Job cancelled successfully",
            "job_id": job_id,
            "cluster_name": cluster_name,
            "result": result,
        }
    except NotImplementedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Failed to cancel job: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to cancel job")
