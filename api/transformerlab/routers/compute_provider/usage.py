"""Usage reporting routes for compute providers."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from transformerlab.shared.models.user_model import get_async_session
from transformerlab.routers.auth import require_team_owner
from transformerlab.services.provider_service import list_team_providers
from transformerlab.services import job_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/report")
async def get_usage_report(
    owner_info=Depends(require_team_owner),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get usage report for REMOTE jobs in the team.
    Aggregates usage data by user, provider, and resources.
    Only accessible to team owners.
    """
    from lab import Experiment

    team_id = owner_info["team_id"]

    # Get all current team providers to check which ones still exist
    existing_provider_ids = set()
    existing_provider_names = set()
    try:
        current_providers = await list_team_providers(session, team_id)
        if current_providers:
            existing_provider_ids = {str(provider.id) for provider in current_providers if provider.id}
            existing_provider_names = {provider.name for provider in current_providers if provider.name}
    except Exception as e:
        print(f"Error getting current providers for team {team_id}: {e}")
        import traceback

        traceback.print_exc()
        # Continue with empty sets - we'll just mark all providers as deleted
        pass

    # Get all experiments in the current workspace
    try:
        experiments_data = await Experiment.get_all()
        experiments = [exp.get("id") for exp in experiments_data if exp.get("id")]
    except Exception as e:
        print(f"Error getting experiments: {e}")
        experiments = []

    # Collect all REMOTE jobs
    remote_jobs = []

    for experiment_id in experiments:
        try:
            jobs = await job_service.jobs_get_all(experiment_id=experiment_id, type="REMOTE")
            for job in jobs:
                job_data = job.get("job_data", {}) or {}

                # Parse job_data if it's a string
                if isinstance(job_data, str):
                    try:
                        job_data = json.loads(job_data)
                    except (json.JSONDecodeError, TypeError):
                        job_data = {}

                # Only include jobs with provider info (actual remote jobs)
                if job_data.get("provider_id") or job_data.get("provider_name"):
                    # Calculate duration if we have start and end times
                    duration_seconds = None
                    start_time = job_data.get("start_time")
                    end_time = job_data.get("end_time")

                    if start_time and end_time:
                        try:
                            # Handle both string and datetime formats
                            if isinstance(start_time, str):
                                start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                            else:
                                start = start_time
                            if isinstance(end_time, str):
                                end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                            else:
                                end = end_time
                            duration_seconds = (end - start).total_seconds()
                        except Exception as e:
                            print(f"Error calculating duration for job {job.get('id')}: {e}")
                            pass

                    # Only include jobs that have both start_time and end_time AND duration > 0
                    if not (start_time and end_time and duration_seconds is not None and duration_seconds > 0):
                        continue

                    # Get user info
                    user_info = job_data.get("user_info", {}) or {}
                    user_email = user_info.get("email") or "Unknown"
                    user_name = user_info.get("name") or user_email

                    # Check if provider still exists
                    provider_id = job_data.get("provider_id")
                    provider_name = job_data.get("provider_name") or "Unknown"
                    provider_exists = False

                    # Only check existence if we have provider_id or provider_name and the sets aren't empty
                    # Convert provider_id to string for comparison
                    provider_id_str = str(provider_id) if provider_id else None
                    if existing_provider_ids or existing_provider_names:
                        if provider_id_str and provider_id_str in existing_provider_ids:
                            provider_exists = True
                        elif provider_name and provider_name in existing_provider_names:
                            provider_exists = True

                    # Mark provider as deleted if it no longer exists
                    # Only mark as deleted if we had a provider_id to check against and we have existing providers
                    if not provider_exists and (existing_provider_ids or existing_provider_names):
                        if provider_id_str or (provider_name and provider_name != "Unknown"):
                            if provider_name and not provider_name.endswith("(Deleted)"):
                                provider_name = f"{provider_name} (Deleted)"

                    remote_jobs.append(
                        {
                            "job_id": job.get("id"),
                            "experiment_id": job.get("experiment_id"),
                            "status": job.get("status"),
                            "provider_id": provider_id,
                            "provider_name": provider_name,
                            "provider_type": job_data.get("provider_type"),
                            "provider_exists": provider_exists,
                            "user_email": user_email,
                            "user_name": user_name,
                            "start_time": start_time,
                            "end_time": end_time,
                            "duration_seconds": duration_seconds,
                            "resources": {
                                "cpus": job_data.get("cpus"),
                                "memory": job_data.get("memory"),
                                "disk_space": job_data.get("disk_space"),
                                "accelerators": job_data.get("accelerators"),
                                "num_nodes": job_data.get("num_nodes", 1),
                            },
                            "cluster_name": job_data.get("cluster_name"),
                            "task_name": job_data.get("task_name"),
                        }
                    )
        except Exception as e:
            print(f"Error processing jobs for experiment {experiment_id}: {e}")
            continue

    # Aggregate usage by user
    usage_by_user = {}
    for job in remote_jobs:
        user_email = job["user_email"]
        if user_email not in usage_by_user:
            usage_by_user[user_email] = {
                "user_email": user_email,
                "user_name": job["user_name"],
                "total_jobs": 0,
                "total_duration_seconds": 0,
                "jobs": [],
            }

        usage_by_user[user_email]["total_jobs"] += 1
        if job["duration_seconds"]:
            usage_by_user[user_email]["total_duration_seconds"] += job["duration_seconds"]
        usage_by_user[user_email]["jobs"].append(job)

    # Aggregate usage by provider
    usage_by_provider = {}
    for job in remote_jobs:
        provider_name = job["provider_name"]
        # Use provider_id as key if available to properly group deleted providers
        # But display name will show "(Deleted)" marker
        provider_key = job.get("provider_id") or provider_name

        if provider_key not in usage_by_provider:
            usage_by_provider[provider_key] = {
                "provider_name": provider_name,
                "provider_type": job["provider_type"],
                "provider_exists": job.get("provider_exists", True),
                "total_jobs": 0,
                "total_duration_seconds": 0,
                "jobs": [],
            }

        usage_by_provider[provider_key]["total_jobs"] += 1
        if job["duration_seconds"]:
            usage_by_provider[provider_key]["total_duration_seconds"] += job["duration_seconds"]
        usage_by_provider[provider_key]["jobs"].append(job)

    # Sort users by total duration (descending)
    sorted_users = sorted(usage_by_user.values(), key=lambda x: x["total_duration_seconds"], reverse=True)

    # Sort providers by total duration (descending)
    sorted_providers = sorted(usage_by_provider.values(), key=lambda x: x["total_duration_seconds"], reverse=True)

    return {
        "summary": {
            "total_jobs": len(remote_jobs),
            "total_users": len(usage_by_user),
            "total_providers": len(usage_by_provider),
        },
        "by_user": sorted_users,
        "by_provider": sorted_providers,
        "all_jobs": remote_jobs,
    }
