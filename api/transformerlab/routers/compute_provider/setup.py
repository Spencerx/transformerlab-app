import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from transformerlab.shared.models.user_model import get_async_session
from transformerlab.routers.auth import get_user_and_team
from transformerlab.services.provider_service import get_team_provider, get_provider_instance
from transformerlab.shared.models.models import ProviderType
from transformerlab.compute_providers.local import _get_install_log_path
from lab.dirs import get_local_provider_root
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])


def _get_provider_setup_status_path(team_id: str, provider_id: str) -> str:
    """Return path to the transient local-provider-setup status file for this team/provider.

    This is only used for LOCAL providers, so it should always live on the local filesystem
    (not in workspace storage, which may be backed by S3).
    """
    # Sanitize user-derived identifiers before using them in a file name
    safe_team = secure_filename(str(team_id).replace("/", "_")) or "team"
    safe_provider = secure_filename(str(provider_id).replace("/", "_")) or "provider"
    return os.path.join(
        get_local_provider_root(),
        "team_setup_logs",
        f"local_provider_setup_status_{safe_team}_{safe_provider}.json",
    )


def _read_install_log_tail(max_lines: int = 60) -> Optional[str]:
    try:
        log_path = _get_install_log_path()
        if not os.path.exists(log_path):
            return None
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        tail = "".join(lines[-max_lines:]).strip()
        return tail or None
    except Exception:
        logger.exception("Failed to read local provider install log")
        return None


async def _run_local_provider_setup_background(
    provider_instance: Any,
    status_path: str,
    force_refresh: bool = False,
) -> None:
    """
    Run LocalProvider.setup in the background and write progress snapshots to a status file.

    The status file is deleted when setup completes (success or failure).
    """

    def write_status(phase: str, percent: int, message: str, done: bool = False, error: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {
            "phase": phase,
            "percent": percent,
            "message": message,
            "done": done,
            "error": error,
            "timestamp": time.time(),
        }
        try:
            with open(status_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload))
        except Exception:
            # Best-effort only – avoid crashing on I/O errors.
            logger.exception("Failed to write provider setup status to %s", status_path)

    def progress_callback(phase: str, percent: int, message: str) -> None:
        write_status(phase, percent, message, done=False, error=None)

    try:
        loop = asyncio.get_running_loop()
        # Run the blocking setup() in a thread executor.
        await loop.run_in_executor(
            None, lambda: provider_instance.setup(progress_callback=progress_callback, force_refresh=force_refresh)
        )
        write_status("provider_setup_done", 100, "Local provider setup completed successfully.", done=True, error=None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to run provider setup in background")
        write_status("provider_setup_failed", 100, f"Local provider setup failed: {exc}", done=True, error=str(exc))
    finally:
        # Delete the status file after completion so subsequent status checks see an idle state.
        try:
            if os.path.exists(status_path):
                os.unlink(status_path)
        except Exception:
            logger.exception("Failed to delete provider setup status file %s", status_path)


@router.post("/")
async def setup_provider(
    provider_id: str,
    refresh: bool = False,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """
    Start provider-level setup for a compute provider in the background.

    Currently this is only meaningful for LOCAL providers, where we create
    and populate the shared base uv virtual environment and generate a
    local machine metrics snapshot. For remote providers this endpoint is a
    fast no-op and simply returns {"status": "skipped"}.

    Args:
      refresh: When true, force a refresh of the shared local-provider base
      environment even if it was already prepared by another org.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # For non-local providers, there is no provider-level setup today.
    if provider.type != ProviderType.LOCAL.value:
        return {
            "status": "skipped",
            "provider_type": provider.type,
            "message": "Provider setup is only required for local providers.",
        }

    # Resolve provider instance for this user/team.
    user_id_str = str(user_and_team["user"].id)
    provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

    status_path = _get_provider_setup_status_path(team_id, provider_id)
    try:
        os.makedirs(os.path.dirname(status_path), exist_ok=True)
    except Exception:
        # Parent should already exist, but log and continue if it doesn't.
        logger.exception("Failed to ensure parent directory for provider setup status %s", status_path)

    # Seed initial status so the status endpoint can report that setup has started.
    try:
        with open(status_path, "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "phase": "provider_setup_start",
                        "percent": 0,
                        "message": "Refreshing local provider setup..."
                        if refresh
                        else "Starting local provider setup...",
                        "done": False,
                        "error": None,
                        "timestamp": time.time(),
                    }
                )
            )
    except Exception:
        logger.exception("Failed to write initial provider setup status to %s", status_path)

    # Kick off background setup and return immediately.
    asyncio.create_task(_run_local_provider_setup_background(provider_instance, status_path, force_refresh=refresh))

    return {
        "status": "started",
        "provider_id": provider_id,
        "provider_type": provider.type,
        "refresh": refresh,
        "message": "Local provider refresh started." if refresh else "Local provider setup started.",
    }


@router.post("/refresh")
async def refresh_provider_setup(
    provider_id: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """
    Force-refresh local provider setup for a provider.

    This explicitly re-runs local provider base setup even when an existing
    shared base environment is already marked ready.
    """
    return await setup_provider(
        provider_id=provider_id,
        refresh=True,
        user_and_team=user_and_team,
        session=session,
    )


@router.get("/status")
async def get_setup_status(
    provider_id: str,
    user_and_team=Depends(get_user_and_team),
) -> Dict[str, Any]:
    """
    Get the latest status of a provider-level setup run.

    Returns an "idle" state when no setup is currently running (status file
    does not exist).
    """
    team_id = user_and_team["team_id"]
    status_path = _get_provider_setup_status_path(team_id, provider_id)
    if not os.path.exists(status_path):
        return {
            "status": "idle",
            "provider_id": provider_id,
            "done": True,
            "message": "No active provider setup.",
        }

    try:
        with open(status_path, "r", encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
    except Exception:
        logger.exception("Failed to read provider setup status from %s", status_path)
        raise HTTPException(status_code=500, detail="Failed to read provider setup status")

    data.setdefault("status", "running" if not data.get("done") else "completed")
    data.setdefault("provider_id", provider_id)
    log_tail = _read_install_log_tail()
    if log_tail:
        data["log_tail"] = log_tail
    return data
