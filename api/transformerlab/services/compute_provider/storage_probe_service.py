"""Launch a minimal probe job and check whether its sentinel file reached shared storage."""

from sqlalchemy.ext.asyncio import AsyncSession

from lab import storage
from lab.dirs import get_workspace_dir, set_organization_id
from transformerlab.schemas.compute_providers import ProviderTemplateLaunchRequest
from transformerlab.services.compute_provider.launch_template import launch_template_on_provider

PROBE_EXPERIMENT_ID = "__storage_probe__"


async def launch_storage_probe(
    provider_id: str,
    user_and_team: dict,
    session: AsyncSession,
) -> dict:
    """Launch a probe job that writes a sentinel file to shared storage.

    Returns {"job_id": <int>, "experiment_id": PROBE_EXPERIMENT_ID}.
    """
    request = ProviderTemplateLaunchRequest(
        experiment_id=PROBE_EXPERIMENT_ID,
        task_name="Storage Probe",
        run="python -m lab.probe",
        cpus="1",
        accelerators=None,
        memory=None,
        env_vars={},
    )

    result = await launch_template_on_provider(
        provider_id=provider_id,
        request=request,
        user_and_team=user_and_team,
        session=session,
    )

    job_id = result.get("job_id")
    if job_id is None:
        raise ValueError(f"launch_template_on_provider did not return a job_id: {result}")
    return {"job_id": job_id, "experiment_id": PROBE_EXPERIMENT_ID}


async def check_storage_probe(job_id: str, team_id: str) -> dict:
    """Check whether the sentinel file written by probe job *job_id* exists.

    The controller resolves the workspace using the same org context that the
    launch template used when constructing TFL_STORAGE_URI for the worker.

    Returns {"found": bool, "path": str}.
    """
    # set_organization_id writes to a contextvars.ContextVar — safe for concurrent requests
    set_organization_id(team_id)
    try:
        workspace = await get_workspace_dir()
        sentinel_path = storage.join(workspace, "debug", f"storage-probe-{job_id}.txt")
        found = await storage.exists(sentinel_path)
    finally:
        set_organization_id(None)
    return {"found": found, "path": sentinel_path}
