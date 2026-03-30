import logging
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from transformerlab.shared.models.user_model import get_async_session
from transformerlab.routers.auth import get_user_and_team
from transformerlab.services.provider_service import get_team_provider
from transformerlab.shared.models.models import ProviderType

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/org-ssh-public-key")
async def get_org_ssh_public_key_endpoint(
    user_and_team=Depends(get_user_and_team),
):
    """
    Get the organization's SSH public key for users to add to their SLURM account.
    Requires X-Team-Id header and team membership.
    """
    from transformerlab.services.ssh_key_service import get_org_ssh_public_key

    team_id = user_and_team["team_id"]

    try:
        public_key = await get_org_ssh_public_key(team_id)
        return {
            "public_key": public_key,
            "instructions": "Add this public key to ~/.ssh/authorized_keys on your SLURM login node for the user account you specify in Provider Settings.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get SSH public key: {str(e)}")


@router.get("/{provider_id}")
async def get_user_provider_settings(
    provider_id: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get user-specific settings for a provider (e.g., SLURM username, SSH key status).
    Requires X-Team-Id header and team membership.
    """
    import transformerlab.db.db as db
    from transformerlab.services.user_slurm_key_service import user_slurm_key_exists

    team_id = user_and_team["team_id"]
    user_id = str(user_and_team["user"].id)

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    slurm_user_key = f"provider:{provider_id}:slurm_user"
    slurm_user = await db.config_get(key=slurm_user_key, user_id=user_id, team_id=team_id)

    custom_flags_key = f"provider:{provider_id}:slurm_custom_sbatch_flags"
    custom_sbatch_flags = await db.config_get(key=custom_flags_key, user_id=user_id, team_id=team_id)

    has_ssh_key = False
    if provider.type == ProviderType.SLURM.value:
        has_ssh_key = await user_slurm_key_exists(team_id, provider_id, user_id)

    return {
        "provider_id": provider_id,
        "slurm_user": slurm_user,
        "custom_sbatch_flags": custom_sbatch_flags,
        "has_ssh_key": has_ssh_key,
    }


@router.put("/{provider_id}")
async def set_user_provider_settings(
    provider_id: str,
    body: Optional[dict] = Body(None),
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Set user-specific settings for a provider (e.g., SLURM username).
    Requires X-Team-Id header and team membership.
    """
    import transformerlab.db.db as db

    team_id = user_and_team["team_id"]
    user_id = str(user_and_team["user"].id)

    # Verify provider exists and user has access
    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Only allow SLURM providers to have user-specific SLURM settings
    if provider.type != ProviderType.SLURM.value:
        raise HTTPException(
            status_code=400,
            detail="User-specific SLURM settings are only available for SLURM providers",
        )

    # Read slurm_user from request body (frontend sends JSON body)
    slurm_user = (body or {}).get("slurm_user")
    if isinstance(slurm_user, str):
        slurm_user = slurm_user.strip() or None
    elif slurm_user is not None and not isinstance(slurm_user, str):
        slurm_user = str(slurm_user).strip() or None

    # Read custom SBATCH flags from request body (optional, free-form string)
    raw_flags = (body or {}).get("custom_sbatch_flags")
    if isinstance(raw_flags, str):
        custom_sbatch_flags = raw_flags.strip() or None
    elif raw_flags is None:
        custom_sbatch_flags = None
    else:
        # Coerce non-string values to string for robustness
        custom_sbatch_flags = str(raw_flags).strip() or None

    # Set user-specific slurm_user setting
    slurm_user_key = f"provider:{provider_id}:slurm_user"
    if slurm_user:
        await db.config_set(key=slurm_user_key, value=slurm_user, user_id=user_id, team_id=team_id)
    else:
        await db.config_set(key=slurm_user_key, value="", user_id=user_id, team_id=team_id)

    # Set user-specific custom SBATCH flags
    custom_flags_key = f"provider:{provider_id}:slurm_custom_sbatch_flags"
    if custom_sbatch_flags:
        await db.config_set(
            key=custom_flags_key,
            value=custom_sbatch_flags,
            user_id=user_id,
            team_id=team_id,
        )
    else:
        # Store as empty string when cleared
        await db.config_set(
            key=custom_flags_key,
            value="",
            user_id=user_id,
            team_id=team_id,
        )

    has_ssh_key = False
    if provider.type == ProviderType.SLURM.value:
        from transformerlab.services.user_slurm_key_service import user_slurm_key_exists

        has_ssh_key = await user_slurm_key_exists(team_id, provider_id, user_id)

    return {
        "provider_id": provider_id,
        "slurm_user": slurm_user,
        "custom_sbatch_flags": custom_sbatch_flags,
        "has_ssh_key": has_ssh_key,
    }


@router.post("/{provider_id}/ssh-key")
async def upload_user_slurm_ssh_key(
    provider_id: str,
    body: dict = Body(...),
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Upload a user's SLURM SSH private key for a provider.
    Requires X-Team-Id header and team membership.
    """
    from transformerlab.services.user_slurm_key_service import save_user_slurm_key

    team_id = user_and_team["team_id"]
    user_id = str(user_and_team["user"].id)

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if provider.type != ProviderType.SLURM.value:
        raise HTTPException(
            status_code=400,
            detail="SSH key upload is only available for SLURM providers",
        )

    private_key = body.get("private_key")
    if not private_key or not isinstance(private_key, str):
        raise HTTPException(status_code=400, detail="private_key is required and must be a string")
    private_key = private_key.strip()
    if not private_key:
        raise HTTPException(status_code=400, detail="private_key cannot be empty")
    if not (private_key.startswith("-----BEGIN") or "PRIVATE KEY" in private_key or "BEGIN RSA" in private_key):
        raise HTTPException(
            status_code=400,
            detail="Invalid private key format. Expected PEM or OpenSSH format starting with '-----BEGIN'",
        )

    try:
        await save_user_slurm_key(team_id, provider_id, user_id, private_key)
        return {
            "status": "success",
            "provider_id": provider_id,
            "message": "SSH private key uploaded successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save SSH key: {str(e)}")


@router.delete("/{provider_id}/ssh-key")
async def delete_user_slurm_ssh_key(
    provider_id: str,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Delete a user's SLURM SSH private key for a provider.
    Requires X-Team-Id header and team membership.
    """
    from transformerlab.services.user_slurm_key_service import delete_user_slurm_key

    team_id = user_and_team["team_id"]
    user_id = str(user_and_team["user"].id)

    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if provider.type != ProviderType.SLURM.value:
        raise HTTPException(
            status_code=400,
            detail="SSH key deletion is only available for SLURM providers",
        )

    try:
        await delete_user_slurm_key(team_id, provider_id, user_id)
        return {
            "status": "success",
            "provider_id": provider_id,
            "message": "SSH private key deleted successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete SSH key: {str(e)}")
