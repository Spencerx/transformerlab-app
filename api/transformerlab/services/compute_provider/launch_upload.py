"""Upload a file for provider-backed task file mounts."""

import logging
import uuid
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from transformerlab.schemas.compute_providers import ProviderTemplateFileUploadResponse
from transformerlab.services.provider_service import get_team_provider
from transformerlab.services.upload_service import (
    get_assembled_path,
    get_filename,
    delete_upload,
)
from lab import storage
from lab.dirs import get_workspace_dir
from lab.storage import copy_file

logger = logging.getLogger(__name__)


async def upload_task_file_for_provider(
    session: AsyncSession,
    team_id: str,
    provider_id: str,
    task_id: str,
    file: Optional[UploadFile],
    upload_id: Optional[str] = None,
) -> ProviderTemplateFileUploadResponse:
    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if file is None and upload_id is None:
        raise HTTPException(status_code=400, detail="Provide either a file or upload_id")

    try:
        workspace_dir = await get_workspace_dir()
        if not workspace_dir:
            raise RuntimeError("Workspace directory is not configured")

        uploads_root = storage.join(workspace_dir, "uploads", "task")
        await storage.makedirs(uploads_root, exist_ok=True)

        task_dir = storage.join(uploads_root, str(task_id))
        await storage.makedirs(task_dir, exist_ok=True)

        if upload_id is not None:
            try:
                assembled_path = await get_assembled_path(upload_id)
                original_name = await get_filename(upload_id)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
        else:
            original_name = file.filename or "uploaded_file"
            assembled_path = None

        suffix = uuid.uuid4().hex[:8]
        safe_name = original_name.split("/")[-1].split("\\")[-1]
        stored_filename = f"{safe_name}.{suffix}"
        stored_path = storage.join(task_dir, stored_filename)

        if assembled_path is not None:
            await copy_file(assembled_path, stored_path)
            await delete_upload(upload_id)
        else:
            await file.seek(0)
            content = await file.read()
            async with await storage.open(stored_path, "wb") as f_out:
                await f_out.write(content)

        return ProviderTemplateFileUploadResponse(
            status="success",
            stored_path=stored_path,
            message="File uploaded successfully",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Template file upload error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to upload template file") from exc
