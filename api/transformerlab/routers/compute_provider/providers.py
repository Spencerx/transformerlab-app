import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from transformerlab.shared.models.user_model import get_async_session
from transformerlab.routers.auth import require_team_owner, get_user_and_team
from transformerlab.services.provider_service import (
    get_team_provider,
    list_team_providers,
    list_enabled_team_providers,
    create_team_provider,
    update_team_provider,
    delete_team_provider,
    get_provider_instance,
    _local_providers_disabled,
    detect_local_supported_accelerators,
)
from transformerlab.schemas.compute_providers import (
    ProviderCreate,
    ProviderUpdate,
    ProviderRead,
    mask_sensitive_config,
)
from transformerlab.shared.models.models import ProviderType, TeamRole
from transformerlab.services.cache_service import cache, cached
from transformerlab.routers.compute_provider.setup import (
    _get_provider_setup_status_path,
    _run_local_provider_setup_background,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/detect-accelerators")
async def detect_local_accelerators(user_and_team=Depends(get_user_and_team)) -> Dict[str, Any]:
    """
    Detect accelerators available on this server for the local compute provider.

    Returns a list of accelerator type strings (e.g. "cpu", "NVIDIA").
    """
    # Best-effort detection may call out to tools like `nvidia-smi` / `rocminfo`.
    # Run in a thread so we don't block the event loop.
    supported_accelerators = await asyncio.to_thread(detect_local_supported_accelerators)
    return {"supported_accelerators": supported_accelerators}


@router.get("/", response_model=List[ProviderRead])
@cached(
    key="providers:list:{include_disabled}",
    ttl="300s",
    tags=["providers", "providers:list"],
)
async def list_providers(
    include_disabled: bool = Query(False, description="Include disabled providers (admin view)"),
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    List all providers for the current team.
    Requires X-Team-Id header and team membership.
    By default, disabled providers are excluded. Pass include_disabled=true to see all.
    """
    team_id = user_and_team["team_id"]
    if include_disabled:
        if user_and_team.get("role") != TeamRole.OWNER.value:
            raise HTTPException(status_code=403, detail="Only team owners can view disabled providers")
        providers = await list_team_providers(session, team_id)
    else:
        providers = await list_enabled_team_providers(session, team_id)

    # Convert to response format with masked sensitive fields
    result = []
    for provider in providers:
        masked_config = mask_sensitive_config(provider.config or {}, provider.type)
        result.append(
            ProviderRead(
                id=provider.id,
                team_id=provider.team_id,
                name=provider.name,
                type=provider.type,
                config=masked_config,
                created_by_user_id=provider.created_by_user_id,
                created_at=provider.created_at,
                updated_at=provider.updated_at,
                disabled=provider.disabled,
            )
        )

    return result


@router.post("/", response_model=ProviderRead)
async def create_provider(
    provider_data: ProviderCreate,
    force_refresh: bool = False,
    owner_info=Depends(require_team_owner),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Create a new provider for the team.
    Requires X-Team-Id header and team owner role.
    """
    team_id = owner_info["team_id"]
    user = owner_info["user"]

    # Validate provider type
    if provider_data.type not in [ProviderType.SLURM, ProviderType.SKYPILOT, ProviderType.RUNPOD, ProviderType.LOCAL]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider type. Must be one of: {ProviderType.SLURM.value}, {ProviderType.SKYPILOT.value}, {ProviderType.RUNPOD.value}, {ProviderType.LOCAL.value}",
        )

    # Respect global disable flag for local providers
    if provider_data.type == ProviderType.LOCAL and _local_providers_disabled():
        raise HTTPException(status_code=400, detail="Local providers are disabled by server configuration.")

    # Check if provider name already exists for this team
    existing = await list_team_providers(session, team_id)
    for existing_provider in existing:
        if existing_provider.name == provider_data.name:
            raise HTTPException(
                status_code=400, detail=f"Provider with name '{provider_data.name}' already exists for this team"
            )

    # Convert Pydantic config to dict
    config_dict = provider_data.config.model_dump(exclude_none=True)

    # Create provider
    provider = await create_team_provider(
        session=session,
        team_id=team_id,
        name=provider_data.name,
        provider_type=provider_data.type.value
        if isinstance(provider_data.type, ProviderType)
        else str(provider_data.type),
        config=config_dict,
        created_by_user_id=str(user.id),
    )

    await cache.invalidate("providers")

    # For LOCAL providers, kick off background setup immediately so users see progress
    # (via /compute_provider/{id}/setup/status) without blocking provider creation.
    if provider.type == ProviderType.LOCAL.value:
        try:
            user_id_str = str(user.id)
            provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

            status_path = _get_provider_setup_status_path(team_id, str(provider.id))
            try:
                os.makedirs(os.path.dirname(status_path), exist_ok=True)
            except Exception:
                logger.exception("Failed to ensure parent directory for provider setup status %s", status_path)
            try:
                with open(status_path, "w", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "phase": "provider_setup_start",
                                "percent": 0,
                                "message": "Starting fresh local provider setup...",
                                "done": False,
                                "error": None,
                                "timestamp": time.time(),
                            }
                        )
                    )
            except Exception:
                logger.exception(
                    "Failed to seed provider setup status for newly created local provider %s", provider.id
                )

            asyncio.create_task(
                _run_local_provider_setup_background(provider_instance, status_path, force_refresh=force_refresh)
            )
        except Exception:
            # Non-fatal: provider was created successfully; setup can still be started manually.
            logger.exception("Failed to auto-start setup for newly created local provider %s", provider.id)

    # Return with masked sensitive fields
    masked_config = mask_sensitive_config(provider.config or {}, provider.type)
    return ProviderRead(
        id=provider.id,
        team_id=provider.team_id,
        name=provider.name,
        type=provider.type,
        config=masked_config,
        created_by_user_id=provider.created_by_user_id,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
        disabled=provider.disabled,
    )


@router.get("/{provider_id}", response_model=ProviderRead)
async def get_provider(
    provider_id: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get a specific provider by ID.
    Requires X-Team-Id header and team membership.
    """
    team_id = user_and_team["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Return with masked sensitive fields
    masked_config = mask_sensitive_config(provider.config or {}, provider.type)
    return ProviderRead(
        id=provider.id,
        team_id=provider.team_id,
        name=provider.name,
        type=provider.type,
        config=masked_config,
        created_by_user_id=provider.created_by_user_id,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
        disabled=provider.disabled,
    )


@router.patch("/{provider_id}", response_model=ProviderRead)
async def update_provider(
    provider_id: str,
    provider_data: ProviderUpdate,
    owner_info=Depends(require_team_owner),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Update a provider.
    Requires X-Team-Id header and team owner role.
    """
    team_id = owner_info["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Check if name is being changed and if new name already exists
    if provider_data.name and provider_data.name != provider.name:
        existing = await list_team_providers(session, team_id)
        for existing_provider in existing:
            if existing_provider.id != provider_id and existing_provider.name == provider_data.name:
                raise HTTPException(
                    status_code=400, detail=f"Provider with name '{provider_data.name}' already exists for this team"
                )

    # Prepare update data
    update_name = provider_data.name
    update_config = None

    if provider_data.config:
        # Merge existing config with updates
        existing_config = provider.config or {}
        new_config = provider_data.config.model_dump(exclude_none=True)
        # Merge dictionaries, with new_config taking precedence
        update_config = {**existing_config, **new_config}

    # Resolve disabled flag: only update if explicitly set (not the default False)
    update_disabled = provider_data.disabled if provider_data.disabled is not None else None

    # Update provider
    provider = await update_team_provider(
        session=session, provider=provider, name=update_name, config=update_config, disabled=update_disabled
    )

    await cache.invalidate("providers")

    # Return with masked sensitive fields
    masked_config = mask_sensitive_config(provider.config or {}, provider.type)
    return ProviderRead(
        id=provider.id,
        team_id=provider.team_id,
        name=provider.name,
        type=provider.type,
        config=masked_config,
        created_by_user_id=provider.created_by_user_id,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
        disabled=provider.disabled,
    )


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    owner_info=Depends(require_team_owner),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Delete a provider.
    Requires X-Team-Id header and team owner role.
    """
    team_id = owner_info["team_id"]

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    await delete_team_provider(session, provider)
    await cache.invalidate("providers")
    return {"message": "Provider deleted successfully"}


@router.get("/{provider_id}/check")
async def check_provider(
    provider_id: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Check if a compute provider is active and accessible.
    Requires X-Team-Id header and team membership.
    For SLURM providers, uses the current user's SLURM username if set in Provider Settings.

    Returns:
        {"status": True} if the provider is active, {"status": False} otherwise
    """
    team_id = user_and_team["team_id"]
    user_id_str = str(user_and_team["user"].id)

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

        # Call the check method
        is_active = await asyncio.to_thread(provider_instance.check)

        return {"status": is_active}
    except Exception as e:
        error_msg = str(e)
        print(f"Failed to check provider: {error_msg}")
        # If instantiation or check fails, provider is not active
        return {"status": False}
