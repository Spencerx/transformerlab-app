"""Sub-router for compute provider launch logic, including sweep dispatch."""

import asyncio
import configparser
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from transformerlab.shared.models.user_model import get_async_session
from transformerlab.routers.auth import get_user_and_team
from transformerlab.services.provider_service import get_team_provider, get_provider_instance
from transformerlab.schemas.compute_providers import (
    ProviderTemplateLaunchRequest,
    ProviderTemplateFileUploadResponse,
)
from transformerlab.shared.models.models import ProviderType
from transformerlab.compute_providers.models import ClusterConfig
from transformerlab.services import job_service, quota_service
from transformerlab.services.task_service import task_service
from transformerlab.services.local_provider_queue import enqueue_local_launch
from transformerlab.services.remote_provider_queue import enqueue_remote_launch
from lab import storage
from lab.storage import STORAGE_PROVIDER
from lab.dirs import (
    get_workspace_dir,
    get_local_provider_job_dir,
    get_job_dir,
    set_organization_id,
    get_task_dir,
)
from lab.job_status import JobStatus
from transformerlab.shared.github_utils import (
    read_github_pat_from_workspace,
    generate_github_clone_setup,
)
from transformerlab.shared.secret_utils import (
    extract_secret_names_from_data,
    load_team_secrets,
    replace_secrets_in_dict,
    replace_secret_placeholders,
)
from werkzeug.utils import secure_filename
from transformerlab.shared import galleries
from transformerlab.shared.interactive_gallery_utils import (
    resolve_interactive_command,
    find_interactive_gallery_entry,
)
from transformerlab.schemas.secrets import SPECIAL_SECRET_TYPES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/launch", tags=["launch"])


_TASK_COPY_EXCLUDE = {"index.json"}


async def _copy_task_files_to_dir(task_src: str, dest_dir: str) -> None:
    """Copy task files from task_src into dest_dir, excluding internal metadata."""
    try:
        await storage.makedirs(dest_dir, exist_ok=True)
        entries = await storage.ls(task_src, detail=False)
    except Exception:
        logger.warning("Failed to prepare task file copy from %s to %s, skipping", task_src, dest_dir, exc_info=True)
        return
    for entry in entries:
        name = entry.rstrip("/").rsplit("/", 1)[-1]
        if name in _TASK_COPY_EXCLUDE:
            continue
        dest_path = storage.join(dest_dir, name)
        try:
            if await storage.isdir(entry):
                await storage.copy_dir(entry, dest_path)
            else:
                await storage.copy_file(entry, dest_path)
        except Exception:
            logger.warning("Failed to copy task file %s to %s, skipping", entry, dest_path, exc_info=True)


def _sanitize_cluster_basename(base_name: Optional[str]) -> str:
    """Return a filesystem-safe cluster base name."""
    if not base_name:
        return "remote-template"
    normalized = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in base_name.strip())
    normalized = normalized.strip("-_")
    return normalized or "remote-template"


def _get_aws_credentials_from_file(profile_name: str = "transformerlab-s3") -> Tuple[Optional[str], Optional[str]]:
    """
    Read AWS credentials from ~/.aws/credentials file for the specified profile.

    Args:
        profile_name: AWS profile name (default: "transformerlab-s3")

    Returns:
        Tuple of (aws_access_key_id, aws_secret_access_key) or (None, None) if not found
    """
    credentials_path = os.path.join(os.path.expanduser("~"), ".aws", "credentials")

    if not os.path.exists(credentials_path):
        return None, None

    try:
        config = configparser.ConfigParser()
        config.read(credentials_path)

        if profile_name in config:
            access_key = config[profile_name].get("aws_access_key_id")
            secret_key = config[profile_name].get("aws_secret_access_key")
            return access_key, secret_key
    except Exception:
        pass

    return None, None


# lab.init() not required; copy_file_mounts uses _TFL_JOB_ID and job_data only
COPY_FILE_MOUNTS_SETUP = 'pip install -q transformerlab && python -c "from lab import lab; lab.copy_file_mounts()"'


# RunPod (and similar) use /workspace as a writable persistent path; ~/.aws may be wrong user or not visible over SSH
RUNPOD_AWS_CREDENTIALS_DIR = "/workspace/.aws"


def _generate_aws_credentials_setup(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_profile: Optional[str] = None,
    aws_credentials_dir: Optional[str] = None,
) -> str:
    """
    Generate bash script to set up AWS credentials.

    Args:
        aws_access_key_id: AWS access key ID
        aws_secret_access_key: AWS secret access key
        aws_profile: AWS profile name (defaults to 'transformerlab-s3' if not provided)
        aws_credentials_dir: If set (e.g. /workspace/.aws), write credentials here instead of ~/.aws.
            Caller should set AWS_SHARED_CREDENTIALS_FILE to <dir>/credentials so processes use this file.

    Returns:
        Bash script to configure AWS credentials
    """
    profile_name = aws_profile or os.getenv("AWS_PROFILE", "transformerlab-s3")
    cred_dir = aws_credentials_dir if aws_credentials_dir else "~/.aws"
    cred_file = f"{cred_dir}/credentials" if aws_credentials_dir else "~/.aws/credentials"

    # Escape for bash: single quotes and special characters
    def escape_bash(s: str) -> str:
        return s.replace("'", "'\"'\"'").replace("\\", "\\\\").replace("$", "\\$")

    escaped_access_key = escape_bash(aws_access_key_id)
    escaped_secret_key = escape_bash(aws_secret_access_key)
    escaped_profile = escape_bash(profile_name).replace("[", "\\[").replace("]", "\\]")

    # Simple approach: create dir, remove old profile section directly, append new profile
    setup_script = (
        f"echo 'Setting up AWS credentials for profile: {profile_name}'; "
        f"mkdir -p {cred_dir}; "
        f"chmod 700 {cred_dir}; "
        f"if [ -f {cred_file} ]; then "
        f"  awk 'BEGIN{{in_profile=0}} /^\\[{escaped_profile}\\]/{{in_profile=1; next}} /^\\[/{{in_profile=0}} !in_profile{{print}}' {cred_file} > {cred_file}.new && mv {cred_file}.new {cred_file} || true; "
        f"fi; "
        f"echo '[{profile_name}]' >> {cred_file}; "
        f"echo 'aws_access_key_id={escaped_access_key}' >> {cred_file}; "
        f"echo 'aws_secret_access_key={escaped_secret_key}' >> {cred_file}; "
        f"chmod 600 {cred_file}; "
        f"echo 'AWS credentials configured successfully at {cred_file}';"
    )
    return setup_script


def _generate_gcp_credentials_setup(service_account_json: str, credentials_path: Optional[str] = None) -> str:
    """
    Generate bash script to set up GCP service account credentials on the remote host.

    This writes the provided service account JSON to a file and points
    GOOGLE_APPLICATION_CREDENTIALS at it so that google-cloud libraries and
    ADC can pick it up.

    Args:
        service_account_json: The service account JSON contents.
        credentials_path: Optional path on the remote host where the JSON
            should be written. Defaults to ~/.config/gcloud/tfl-service-account.json

    Returns:
        Bash script to configure GCP credentials.
    """
    target_path = credentials_path or "$HOME/.config/gcloud/tfl-service-account.json"

    def escape_bash_single_quoted(s: str) -> str:
        # Safely embed arbitrary JSON into a single-quoted string in bash:
        # close quote, escape single quote, reopen.
        return s.replace("'", "'\"'\"'")

    escaped_json = escape_bash_single_quoted(service_account_json)

    setup_script = (
        "echo 'Setting up GCP service account credentials...'; "
        'mkdir -p "$HOME/.config/gcloud"; '
        f"echo '{escaped_json}' > {target_path}; "
        f"chmod 600 {target_path}; "
        f"export GOOGLE_APPLICATION_CREDENTIALS={target_path}; "
        "echo 'GCP credentials configured successfully'"
    )
    return setup_script


def _generate_azure_credentials_setup(
    connection_string: Optional[str],
    account_name: Optional[str],
    account_key: Optional[str],
    sas_token: Optional[str],
) -> str:
    """
    Generate bash script to export Azure storage credentials on the remote host.

    This mirrors the pattern used for AWS/GCP: we materialise the minimal
    environment required for fsspec/adlfs to authenticate against Azure
    Blob Storage.
    """

    def escape_bash_single_quoted(s: str) -> str:
        # Safely embed arbitrary values into a single-quoted string in bash.
        return s.replace("'", "'\"'\"'")

    exports: list[str] = ["echo 'Setting up Azure storage credentials...'"]
    if connection_string:
        escaped = escape_bash_single_quoted(connection_string)
        exports.append(f"export AZURE_STORAGE_CONNECTION_STRING='{escaped}'")
    if account_name:
        escaped = escape_bash_single_quoted(account_name)
        exports.append(f"export AZURE_STORAGE_ACCOUNT='{escaped}'")
    if account_key:
        escaped = escape_bash_single_quoted(account_key)
        exports.append(f"export AZURE_STORAGE_KEY='{escaped}'")
    if sas_token:
        escaped = escape_bash_single_quoted(sas_token)
        exports.append(f"export AZURE_STORAGE_SAS_TOKEN='{escaped}'")

    exports.append("echo 'Azure storage credentials configured successfully'")
    return "; ".join(exports)


def _find_missing_secrets_for_template_launch(
    request: ProviderTemplateLaunchRequest, secrets: Dict[str, Any]
) -> set[str]:
    """
    Inspect the launch request for any {{secret.NAME}} / {{secrets.NAME}} placeholders
    and return the subset of referenced secret names that are not present in `secrets`.
    """
    referenced: set[str] = set()

    # Core task fields that may contain secrets
    referenced.update(extract_secret_names_from_data(request.run))
    if request.setup:
        referenced.update(extract_secret_names_from_data(request.setup))
    if request.env_vars:
        referenced.update(extract_secret_names_from_data(request.env_vars))
    if request.parameters:
        referenced.update(extract_secret_names_from_data(request.parameters))
    if request.config:
        referenced.update(extract_secret_names_from_data(request.config))
    if request.sweep_config:
        referenced.update(extract_secret_names_from_data(request.sweep_config))

    if not referenced:
        return set()

    return {name for name in referenced if name not in secrets}


async def _create_sweep_parent_job(
    provider_id: str,
    request: ProviderTemplateLaunchRequest,
    user_and_team: dict,
    session: AsyncSession,
    sweep_config: Dict[str, List[Any]],
    sweep_metric: str,
    lower_is_better: bool,
    total_configs: int,
) -> str:
    """
    Create the parent sweep job immediately and return its ID.
    This is fast and allows us to return a response quickly.
    """
    from itertools import product

    team_id = user_and_team["team_id"]
    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Generate all parameter combinations
    param_names = list(sweep_config.keys())
    param_values = [sweep_config[name] for name in param_names]
    configs = []
    for values in product(*param_values):
        config = dict(zip(param_names, values))
        configs.append(config)

    user_info = {}
    if getattr(user_and_team["user"], "first_name", None) or getattr(user_and_team["user"], "last_name", None):
        user_info["name"] = " ".join(
            part
            for part in [
                getattr(user_and_team["user"], "first_name", ""),
                getattr(user_and_team["user"], "last_name", ""),
            ]
            if part
        ).strip()
    if getattr(user_and_team["user"], "email", None):
        user_info["email"] = getattr(user_and_team["user"], "email")

    provider = await get_team_provider(session, user_and_team["team_id"], provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    provider_display_name = request.provider_name or provider.name

    parent_job_id = await job_service.job_create(
        type="SWEEP",
        status=JobStatus.RUNNING,
        experiment_id=request.experiment_id,
    )

    # Store parent job metadata
    parent_job_data = {
        "sweep_parent": True,
        "sweep_total": total_configs,
        "sweep_completed": 0,
        "sweep_running": 0,
        "sweep_failed": 0,
        "sweep_job_ids": [],
        "sweep_config": sweep_config,
        "sweep_metric": sweep_metric,
        "lower_is_better": lower_is_better,
        "task_name": request.task_name,
        "subtype": request.subtype,
        "provider_id": provider.id,
        "provider_type": provider.type,
        "provider_name": provider_display_name,
        "user_info": user_info or None,
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    }

    parent_job_updates = {key: value for key, value in parent_job_data.items() if value is not None}
    if parent_job_updates:
        await job_service.job_update_job_data_insert_key_values(
            parent_job_id, parent_job_updates, request.experiment_id
        )

    return parent_job_id


async def _launch_sweep_jobs(
    provider_id: str,
    request: ProviderTemplateLaunchRequest,
    user_and_team: dict,
    base_parameters: Dict[str, Any],
    sweep_config: Dict[str, List[Any]],
    sweep_metric: str,
    lower_is_better: bool,
    parent_job_id: str,
):
    """
    Launch child jobs for a sweep in the background.
    This is called asynchronously after the parent job is created.
    Creates its own database session and sets org context since it runs in a background task.
    """
    from itertools import product
    from transformerlab.db.session import async_session
    from lab.dirs import set_organization_id as lab_set_org_id

    # Set org context explicitly since background tasks don't inherit request context
    team_id = user_and_team["team_id"]
    if lab_set_org_id is not None:
        lab_set_org_id(team_id)

    try:
        # Create a new session for the background task
        async with async_session() as session:
            team_id = user_and_team["team_id"]
            user = user_and_team["user"]
            provider = await get_team_provider(session, team_id, provider_id)
            if not provider:
                print(f"Provider {provider_id} not found for sweep job {parent_job_id}")
                return

            # Get provider instance (resolves user's slurm_user for SLURM when user_id/team_id set)
            user_id_str = str(user.id)
            provider_instance = await get_provider_instance(provider, user_id=user_id_str, team_id=team_id)

            # Generate user_info
            user_info = {}
            if getattr(user, "first_name", None) or getattr(user, "last_name", None):
                user_info["name"] = " ".join(
                    part for part in [getattr(user, "first_name", ""), getattr(user, "last_name", "")] if part
                ).strip()
            if getattr(user, "email", None):
                user_info["email"] = getattr(user, "email")

            provider_display_name = request.provider_name or provider.name

            # Load team secrets and user secrets for template replacement (user secrets override team secrets)
            user_id = str(user_and_team["user"].id)
            team_secrets = await load_team_secrets(user_id=user_id)

            # Generate all parameter combinations
            param_names = list(sweep_config.keys())
            param_values = [sweep_config[name] for name in param_names]
            configs = []
            for values in product(*param_values):
                config = dict(zip(param_names, values))
                configs.append(config)

            total_configs = len(configs)
            print(f"Launching {total_configs} child jobs for sweep {parent_job_id}")

            base_name = request.cluster_name or request.task_name or provider.name
            child_job_ids = []
            for i, config_params in enumerate(configs):
                # Merge base parameters with sweep parameters
                merged_params = {**(base_parameters or {}), **config_params}

                # Create unique cluster name for this run
                run_suffix = f"sweep-{i + 1}"
                parent_job_short_id = job_service.get_short_job_id(parent_job_id)
                formatted_cluster_name = (
                    f"{_sanitize_cluster_basename(base_name)}-{run_suffix}-job-{parent_job_short_id}"
                )

                # Create child job
                child_job_id = await job_service.job_create(
                    type="REMOTE",
                    status=JobStatus.QUEUED,
                    experiment_id=request.experiment_id,
                )

                # Prepare environment variables
                env_vars = request.env_vars.copy() if request.env_vars else {}

                # Replace {{secret.<name>}} patterns in env_vars
                if env_vars and team_secrets:
                    env_vars = replace_secrets_in_dict(env_vars, team_secrets)

                env_vars["_TFL_JOB_ID"] = str(child_job_id)
                env_vars["_TFL_EXPERIMENT_ID"] = request.experiment_id
                env_vars["_TFL_USER_ID"] = user_id

                # Get TFL_STORAGE_URI
                tfl_storage_uri = None
                try:
                    storage_root = await storage.root_uri()
                    if storage_root:
                        if storage.is_remote_path(storage_root):
                            # Remote cloud storage (S3/GCS/etc.)
                            tfl_storage_uri = storage_root
                        elif STORAGE_PROVIDER == "localfs":
                            # localfs: expose the local mount path to the remote worker
                            tfl_storage_uri = storage_root
                except Exception:
                    pass

                if tfl_storage_uri:
                    env_vars["TFL_STORAGE_URI"] = tfl_storage_uri

                # For RunPod providers, ensure uv is available and configured to use
                # the system Python so sweep runs can call `uv` directly.
                if provider.type == ProviderType.RUNPOD.value:
                    env_vars["UV_SYSTEM_PYTHON"] = "1"

                # For local provider, set TFL_WORKSPACE_DIR so the lab SDK in the subprocess finds the job dir
                if provider.type == ProviderType.LOCAL.value and team_id:
                    set_organization_id(team_id)
                    try:
                        workspace_dir = await get_workspace_dir()
                        if workspace_dir and not storage.is_remote_path(workspace_dir):
                            env_vars["TFL_WORKSPACE_DIR"] = workspace_dir
                    finally:
                        set_organization_id(None)

                # Build setup script (add copy_file_mounts when file_mounts is True, after cloud credentials)
                setup_commands = []

                # Cloud credentials setup:
                # - For AWS (TFL_STORAGE_PROVIDER=aws), inject ~/.aws/credentials profile if available.
                # - For GCP (TFL_STORAGE_PROVIDER=gcp), optionally inject a service account JSON if provided.
                # - For Azure (TFL_STORAGE_PROVIDER=azure), export Azure storage env vars if configured.
                if os.getenv("TFL_REMOTE_STORAGE_ENABLED", "false").lower() == "true":
                    if STORAGE_PROVIDER == "aws":
                        aws_profile = "transformerlab-s3"
                        aws_access_key_id, aws_secret_access_key = await asyncio.to_thread(
                            _get_aws_credentials_from_file, aws_profile
                        )
                        if aws_access_key_id and aws_secret_access_key:
                            aws_credentials_dir = (
                                RUNPOD_AWS_CREDENTIALS_DIR if provider.type == ProviderType.RUNPOD.value else None
                            )
                            aws_setup = _generate_aws_credentials_setup(
                                aws_access_key_id,
                                aws_secret_access_key,
                                aws_profile,
                                aws_credentials_dir=aws_credentials_dir,
                            )
                            setup_commands.append(aws_setup)
                            env_vars["AWS_PROFILE"] = aws_profile
                            if aws_credentials_dir:
                                env_vars["AWS_SHARED_CREDENTIALS_FILE"] = f"{aws_credentials_dir}/credentials"
                    elif STORAGE_PROVIDER == "gcp":
                        # If a GCP service account JSON is provided via env, write it on the remote host
                        # and set GOOGLE_APPLICATION_CREDENTIALS so ADC can find it.
                        gcp_sa_json = os.getenv("TFL_GCP_SERVICE_ACCOUNT_JSON")
                        if gcp_sa_json:
                            gcp_setup = _generate_gcp_credentials_setup(gcp_sa_json)
                            setup_commands.append(gcp_setup)
                    elif STORAGE_PROVIDER == "azure":
                        azure_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
                        azure_account = os.getenv("AZURE_STORAGE_ACCOUNT")
                        azure_key = os.getenv("AZURE_STORAGE_KEY")
                        azure_sas = os.getenv("AZURE_STORAGE_SAS_TOKEN")
                        if azure_connection_string or azure_account:
                            azure_setup = _generate_azure_credentials_setup(
                                azure_connection_string, azure_account, azure_key, azure_sas
                            )
                            setup_commands.append(azure_setup)
                            if azure_connection_string:
                                env_vars["AZURE_STORAGE_CONNECTION_STRING"] = azure_connection_string
                            if azure_account:
                                env_vars["AZURE_STORAGE_ACCOUNT"] = azure_account
                            if azure_key:
                                env_vars["AZURE_STORAGE_KEY"] = azure_key
                            if azure_sas:
                                env_vars["AZURE_STORAGE_SAS_TOKEN"] = azure_sas

                if request.file_mounts is True and request.task_id:
                    setup_commands.append(COPY_FILE_MOUNTS_SETUP)

                # Ensure uv is installed on RunPod sweeps as well so the run
                # command can rely on it being present.
                if provider.type == ProviderType.RUNPOD.value:
                    setup_commands.append("curl -LsSf https://astral.sh/uv/install.sh | sh")

                if request.github_repo_url:
                    workspace_dir = await get_workspace_dir()
                    github_pat = await read_github_pat_from_workspace(workspace_dir, user_id=user_id)
                    directory = request.github_repo_dir or request.github_directory
                    branch = request.github_repo_branch or request.github_branch
                    github_setup = generate_github_clone_setup(
                        repo_url=request.github_repo_url,
                        directory=directory,
                        github_pat=github_pat,
                        branch=branch,
                    )
                    setup_commands.append(github_setup)

                # Add user-provided setup if any (replace secrets in setup)
                if request.setup:
                    setup_with_secrets = (
                        replace_secret_placeholders(request.setup, team_secrets) if team_secrets else request.setup
                    )
                    setup_commands.append(setup_with_secrets)

                final_setup = ";".join(setup_commands) if setup_commands else None

                # Replace secrets in run command
                run_with_secrets = (
                    replace_secret_placeholders(request.run, team_secrets) if team_secrets else request.run
                )

                # Replace secrets in parameters if present
                parameters_with_secrets = merged_params
                if merged_params and team_secrets:
                    parameters_with_secrets = replace_secrets_in_dict(merged_params, team_secrets)

                # Store child job data
                child_job_data = {
                    "parent_sweep_job_id": str(parent_job_id),
                    "sweep_run_index": i + 1,
                    "sweep_total": total_configs,
                    "sweep_params": config_params,
                    "task_name": f"{request.task_name or 'Task'} (Sweep {i + 1}/{total_configs})"
                    if request.task_name
                    else None,
                    "run": run_with_secrets,
                    "cluster_name": formatted_cluster_name,
                    "subtype": request.subtype,
                    "cpus": request.cpus,
                    "memory": request.memory,
                    "disk_space": request.disk_space,
                    "accelerators": request.accelerators,
                    "num_nodes": request.num_nodes,
                    "setup": final_setup,
                    "env_vars": env_vars if env_vars else None,
                    "file_mounts": request.file_mounts if request.file_mounts is not True else True,
                    "parameters": parameters_with_secrets or None,
                    "provider_id": provider.id,
                    "provider_type": provider.type,
                    "provider_name": provider_display_name,
                    "user_info": user_info or None,
                    "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                }
                if request.file_mounts is True and request.task_id:
                    child_job_data["task_id"] = request.task_id

                child_job_updates = {key: value for key, value in child_job_data.items() if value is not None}
                if child_job_updates:
                    await job_service.job_update_job_data_insert_key_values(
                        child_job_id, child_job_updates, request.experiment_id
                    )

                # Prepare cluster config
                disk_size = None
                if request.disk_space:
                    try:
                        disk_size = int(request.disk_space)
                    except (TypeError, ValueError):
                        disk_size = None

                # When file_mounts is True we use lab.copy_file_mounts() in setup; do not send to provider
                file_mounts_for_provider = request.file_mounts if isinstance(request.file_mounts, dict) else {}

                # Resolve SkyPilot-specific settings from provider config for sweep child jobs
                sweep_image_id: str | None = None
                sweep_region: str | None = None
                sweep_zone: str | None = None
                sweep_use_spot: bool = False
                if provider.type == ProviderType.SKYPILOT.value:
                    prov_cfg = provider.config or {}
                    sweep_image_id = prov_cfg.get("docker_image") or None
                    sweep_region = prov_cfg.get("default_region") or None
                    sweep_zone = prov_cfg.get("default_zone") or None
                    sweep_use_spot = prov_cfg.get("use_spot", False) is True
                    if request.config:
                        if request.config.get("docker_image"):
                            sweep_image_id = str(request.config["docker_image"]).strip()
                        if request.config.get("region"):
                            sweep_region = str(request.config["region"]).strip()
                        if request.config.get("use_spot"):
                            sweep_use_spot = True

                cluster_config = ClusterConfig(
                    cluster_name=formatted_cluster_name,
                    provider_name=provider_display_name,
                    provider_id=provider.id,
                    run=run_with_secrets,
                    setup=final_setup,
                    env_vars=env_vars,
                    cpus=request.cpus,
                    memory=request.memory,
                    accelerators=request.accelerators,
                    num_nodes=request.num_nodes,
                    disk_size=disk_size,
                    file_mounts=file_mounts_for_provider,
                    provider_config={"requested_disk_space": request.disk_space},
                    image_id=sweep_image_id,
                    region=sweep_region,
                    zone=sweep_zone,
                    use_spot=sweep_use_spot,
                )

                # Launch cluster for child job
                try:
                    launch_result = await asyncio.to_thread(
                        provider_instance.launch_cluster, formatted_cluster_name, cluster_config
                    )

                    if isinstance(launch_result, dict):
                        await job_service.job_update_job_data_insert_key_value(
                            child_job_id,
                            "provider_launch_result",
                            launch_result,
                            request.experiment_id,
                        )
                        request_id = launch_result.get("request_id")
                        if request_id:
                            await job_service.job_update_job_data_insert_key_value(
                                child_job_id,
                                "orchestrator_request_id",
                                request_id,
                                request.experiment_id,
                            )

                    # Update child job status to LAUNCHING
                    await job_service.job_update_status(child_job_id, JobStatus.LAUNCHING, request.experiment_id)
                    child_job_ids.append(str(child_job_id))
                    print(f"Launched sweep child job {i + 1}/{total_configs}: {child_job_id}")

                except Exception as exc:
                    print(f"Failed to launch cluster for sweep child {i + 1}: {exc}")
                    await job_service.job_update_status(
                        child_job_id,
                        JobStatus.FAILED,
                        request.experiment_id,
                        error_msg=str(exc),
                    )
                    child_job_ids.append(str(child_job_id))

            # Update parent job with child job IDs and running count
            await job_service.job_update_job_data_insert_key_value(
                parent_job_id, "sweep_job_ids", child_job_ids, request.experiment_id
            )
            await job_service.job_update_job_data_insert_key_value(
                parent_job_id, "sweep_running", len(child_job_ids), request.experiment_id
            )

            print(f"Completed launching {len(child_job_ids)} child jobs for sweep {parent_job_id}")
    finally:
        # Clear org context after background task completes
        if lab_set_org_id is not None:
            lab_set_org_id(None)


@router.post("/{task_id}/file-upload", response_model=ProviderTemplateFileUploadResponse)
async def upload_task_file_for_provider(
    provider_id: str,
    task_id: str,
    request: Request,
    file: UploadFile = File(...),
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Upload a single file for a provider-backed task.

    The file is stored under workspace_dir/uploads/task/{task_id}/ and the
    stored_path returned from this endpoint can be used as the local side of a
    file mount mapping: {<remote_path>: <stored_path>}.
    """

    # Ensure team can access provider (also validates team context)
    team_id = user_and_team["team_id"]
    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        workspace_dir = await get_workspace_dir()
        if not workspace_dir:
            raise RuntimeError("Workspace directory is not configured")

        # uploads/task/{task_id}/
        uploads_root = storage.join(workspace_dir, "uploads", "task")
        await storage.makedirs(uploads_root, exist_ok=True)

        import uuid

        task_dir = storage.join(uploads_root, str(task_id))
        await storage.makedirs(task_dir, exist_ok=True)

        # Use original filename with a random suffix to avoid collisions
        original_name = file.filename or "uploaded_file"
        suffix = uuid.uuid4().hex[:8]
        # Avoid path separators from filename
        safe_name = original_name.split("/")[-1].split("\\")[-1]
        stored_filename = f"{safe_name}.{suffix}"
        stored_path = storage.join(task_dir, stored_filename)

        # Persist file contents
        await file.seek(0)
        content = await file.read()
        async with await storage.open(stored_path, "wb") as f:
            await f.write(content)

        return ProviderTemplateFileUploadResponse(
            status="success",
            stored_path=stored_path,
            message="File uploaded successfully",
        )
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Template file upload error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to upload template file")


@router.post("/")
async def launch_template_on_provider(
    provider_id: str,
    request: ProviderTemplateLaunchRequest,
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Create a REMOTE job and launch a provider-backed cluster.
    Mirrors the legacy /remote/launch flow but routes through providers.

    If run_sweeps=True and sweep_config is provided, creates a parent SWEEP job
    and launches multiple child REMOTE jobs with different parameter combinations.
    """

    team_id = user_and_team["team_id"]
    user = user_and_team["user"]
    user_id = str(user.id)

    # Load team + user secrets once and validate that any referenced secrets exist
    team_secrets = await load_team_secrets(user_id=user_id)
    missing_secrets = _find_missing_secrets_for_template_launch(request, team_secrets)

    if missing_secrets:
        display_names = [SPECIAL_SECRET_TYPES.get(name, name) for name in sorted(missing_secrets)]
        missing_list = ", ".join(display_names)
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing secrets: "
                f"{missing_list}. Please define these secrets at the team or user level before launching."
            ),
        )

    # Check if the provider is disabled before any launch path
    provider = await get_team_provider(session, team_id, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if provider.disabled:
        raise HTTPException(status_code=403, detail="Provider is disabled and cannot be used to launch tasks")

    # Check if sweeps are enabled
    if request.run_sweeps and request.sweep_config:
        from itertools import product

        # Generate all parameter combinations to calculate total
        param_names = list(request.sweep_config.keys())
        param_values = [request.sweep_config[name] for name in param_names]
        configs = list(product(*param_values))
        total_configs = len(configs)

        # Create parent job immediately (fast operation)
        parent_job_id = await _create_sweep_parent_job(
            provider_id=provider_id,
            request=request,
            user_and_team=user_and_team,
            session=session,
            sweep_config=request.sweep_config,
            sweep_metric=request.sweep_metric or "eval/loss",
            lower_is_better=request.lower_is_better if request.lower_is_better is not None else True,
            total_configs=total_configs,
        )

        # Launch child jobs in the background using asyncio.create_task
        # This runs concurrently but still within the request context
        # Merge parameters (defaults) with config for sweep
        base_params_for_sweep = {}
        if request.parameters:
            base_params_for_sweep = request.parameters.copy()
        if request.config:
            base_params_for_sweep.update(request.config)

        asyncio.create_task(
            _launch_sweep_jobs(
                provider_id=provider_id,
                request=request,
                user_and_team=user_and_team,
                base_parameters=base_params_for_sweep,
                sweep_config=request.sweep_config,
                sweep_metric=request.sweep_metric or "eval/loss",
                lower_is_better=request.lower_is_better if request.lower_is_better is not None else True,
                parent_job_id=parent_job_id,
            )
        )

        return {
            "status": "success",
            "job_id": parent_job_id,
            "job_type": "SWEEP",
            "total_configs": total_configs,
            "message": f"Sweep created with {total_configs} configurations. Child jobs are being launched in the background.",
        }

    # Normal single job launch (existing logic)
    # (provider already fetched and validated above)

    # Quota checking and hold creation (only for REMOTE jobs)
    if request.minutes_requested is not None and request.minutes_requested > 0:
        has_quota, available, message = await quota_service.check_quota_available(
            session, user_id, team_id, request.minutes_requested
        )
        if not has_quota:
            raise HTTPException(status_code=403, detail=message)

    # NOTE: We no longer launch inline; provider instance is resolved in the remote launch worker.

    # Interactive templates should start directly in INTERACTIVE state instead of LAUNCHING,
    # except for LOCAL providers where we introduce a WAITING status while queued.
    initial_status = JobStatus.INTERACTIVE if request.subtype == "interactive" else JobStatus.LAUNCHING
    if provider.type == ProviderType.LOCAL.value:
        initial_status = JobStatus.WAITING

    job_id = await job_service.job_create(
        type="REMOTE",
        status=initial_status,
        experiment_id=request.experiment_id,
    )

    await job_service.job_update_launch_progress(
        job_id,
        request.experiment_id,
        phase="checking_quota",
        percent=10,
        message="Checking quota",
    )

    # Create quota hold if minutes_requested is provided
    quota_hold = None
    if request.minutes_requested is not None and request.minutes_requested > 0:
        user_id_str = str(user.id)
        # For task_id, use task_name as identifier (task might not have a persistent ID yet)
        # We'll use a format that allows us to look it up later: f"{experiment_id}:{task_name}"
        task_identifier = request.task_name or f"job-{job_id}"
        quota_hold = await quota_service.create_quota_hold(
            session=session,
            user_id=user_id_str,
            team_id=team_id,
            task_id=task_identifier,
            minutes_requested=request.minutes_requested,
            job_id=str(job_id),
        )
        # We return immediately after enqueuing remote launches, so persist the hold now.
        await session.commit()

    await job_service.job_update_launch_progress(
        job_id,
        request.experiment_id,
        phase="building_config",
        percent=30,
        message="Building cluster configuration",
    )

    base_name = request.cluster_name or request.task_name or provider.name
    job_short_id = job_service.get_short_job_id(job_id)
    formatted_cluster_name = f"{_sanitize_cluster_basename(base_name)}-job-{job_short_id}"

    user_info = {}
    if getattr(user, "first_name", None) or getattr(user, "last_name", None):
        user_info["name"] = " ".join(
            part for part in [getattr(user, "first_name", ""), getattr(user, "last_name", "")] if part
        ).strip()
    if getattr(user, "email", None):
        user_info["email"] = getattr(user, "email")

    provider_display_name = request.provider_name or provider.name

    # Prepare environment variables - start with a copy of requested env_vars
    env_vars = request.env_vars.copy() if request.env_vars else {}

    # Replace {{secret.<name>}} patterns in env_vars
    if env_vars and team_secrets:
        env_vars = replace_secrets_in_dict(env_vars, team_secrets)

    # Build setup script - add cloud credential helpers first, then file_mounts and other setup.
    setup_commands: list[str] = []

    if os.getenv("TFL_REMOTE_STORAGE_ENABLED", "false").lower() == "true":
        if STORAGE_PROVIDER == "aws":
            # Get AWS credentials from stored credentials file (transformerlab-s3 profile)
            aws_profile = "transformerlab-s3"
            aws_access_key_id, aws_secret_access_key = await asyncio.to_thread(
                _get_aws_credentials_from_file, aws_profile
            )
            if aws_access_key_id and aws_secret_access_key:
                aws_credentials_dir = RUNPOD_AWS_CREDENTIALS_DIR if provider.type == ProviderType.RUNPOD.value else None
                aws_setup = _generate_aws_credentials_setup(
                    aws_access_key_id, aws_secret_access_key, aws_profile, aws_credentials_dir=aws_credentials_dir
                )
                setup_commands.append(aws_setup)
                if aws_credentials_dir:
                    env_vars["AWS_SHARED_CREDENTIALS_FILE"] = f"{aws_credentials_dir}/credentials"
        elif STORAGE_PROVIDER == "azure":
            azure_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            azure_account = os.getenv("AZURE_STORAGE_ACCOUNT")
            azure_key = os.getenv("AZURE_STORAGE_KEY")
            azure_sas = os.getenv("AZURE_STORAGE_SAS_TOKEN")
            if azure_connection_string or azure_account:
                azure_setup = _generate_azure_credentials_setup(
                    azure_connection_string, azure_account, azure_key, azure_sas
                )
                setup_commands.append(azure_setup)
                if azure_connection_string:
                    env_vars["AZURE_STORAGE_CONNECTION_STRING"] = azure_connection_string
                if azure_account:
                    env_vars["AZURE_STORAGE_ACCOUNT"] = azure_account
                if azure_key:
                    env_vars["AZURE_STORAGE_KEY"] = azure_key
                if azure_sas:
                    env_vars["AZURE_STORAGE_SAS_TOKEN"] = azure_sas

    if request.file_mounts is True and request.task_id:
        setup_commands.append(COPY_FILE_MOUNTS_SETUP)
    # Ensure transformerlab SDK is available on remote machines for live_status tracking and other helpers.
    # This runs after AWS credentials are configured so we have access to any remote storage if needed.
    if provider.type != ProviderType.LOCAL.value:
        setup_commands.append("pip install -q transformerlab")

        # Install torch as well if torch profiler is enabled
        if request.enable_profiling_torch:
            setup_commands.append("pip install -q torch")
    # For RunPod providers, ensure uv is available and configured to use the
    # system Python. This allows user commands to invoke `uv` directly.
    if provider.type == ProviderType.RUNPOD.value:
        env_vars["UV_SYSTEM_PYTHON"] = "1"
        setup_commands.append("curl -LsSf https://astral.sh/uv/install.sh | sh")

    # If GitHub repo fields are missing, fall back to the stored task's fields.
    # This handles GitHub-sourced interactive tasks where the CLI/TUI doesn't
    # send these fields and relies on the backend to resolve them from the task.
    if not request.github_repo_url and request.task_id:
        task_data = await task_service.task_get_by_id(request.task_id)
        if task_data:
            request.github_repo_url = task_data.get("github_repo_url", "") or ""
            # Task data may store the directory as either github_repo_dir or github_directory
            request.github_repo_dir = (
                task_data.get("github_repo_dir", "") or task_data.get("github_directory", "") or ""
            )
            request.github_repo_branch = task_data.get("github_branch", "") or ""

    # Add GitHub clone setup if enabled
    if request.github_repo_url:
        workspace_dir = await get_workspace_dir()
        github_pat = await read_github_pat_from_workspace(workspace_dir, user_id=user_id)
        directory = request.github_repo_dir or request.github_directory
        branch = request.github_repo_branch or request.github_branch
        github_setup = generate_github_clone_setup(
            repo_url=request.github_repo_url,
            directory=directory,
            github_pat=github_pat,
            branch=branch,
        )
        setup_commands.append(github_setup)

    # Add SSH public key setup for SSH interactive tasks and for RunPod (so we can read provider logs via SSH)
    if (
        request.subtype == "interactive" and request.interactive_type == "ssh"
    ) or provider.type == ProviderType.RUNPOD.value:
        from transformerlab.services.ssh_key_service import get_or_create_org_ssh_key_pair, get_org_ssh_public_key

        try:
            # Get or create SSH key pair for this organization
            await get_or_create_org_ssh_key_pair(team_id)
            public_key = await get_org_ssh_public_key(team_id)

            # Generate setup script to add public key to authorized_keys
            # Escape the public key for use in shell script - use single quotes to avoid shell expansion
            # Remove newlines from public key (should be single line anyway)
            public_key_clean = public_key.strip().replace("\n", "").replace("\r", "")
            # Escape single quotes in public key for use within single-quoted string
            public_key_escaped = public_key_clean.replace("'", "'\"'\"'")

            if provider.type == ProviderType.RUNPOD.value:
                # For RunPod: use RunPod's recommended SSH setup from their docs
                # Set SSH_PUBLIC_KEY environment variable (RunPod's override env var for SSH keys)
                # Reference: https://docs.runpod.io/pods/configuration/use-ssh
                env_vars["SSH_PUBLIC_KEY"] = public_key_clean
                ssh_setup = (
                    "apt-get update -qq && "
                    "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server >/dev/null 2>&1 && "
                    "mkdir -p ~/.ssh && "
                    "cd ~/.ssh && "
                    "chmod 700 ~/.ssh && "
                    'echo "$SSH_PUBLIC_KEY" >> authorized_keys && '
                    "chmod 600 authorized_keys && "
                    "service ssh start"
                )
            else:
                # For other providers (interactive SSH tasks): standard setup
                ssh_setup = f"mkdir -p ~/.ssh && chmod 700 ~/.ssh; if [ ! -f ~/.ssh/authorized_keys ]; then touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys; fi; if ! grep -qF '{public_key_escaped}' ~/.ssh/authorized_keys; then echo '{public_key_escaped}' >> ~/.ssh/authorized_keys; fi"

            setup_commands.append(ssh_setup)
        except Exception as e:
            # Log error but don't fail the launch - SSH key setup is optional
            print(f"Warning: Failed to set up SSH key for organization {team_id}: {e}")

    # Note: final_setup is assembled later, after we optionally inject
    # interactive remote setup based on the gallery entry.

    # Add default environment variables
    env_vars["_TFL_JOB_ID"] = str(job_id)
    env_vars["_TFL_EXPERIMENT_ID"] = request.experiment_id
    env_vars["_TFL_USER_ID"] = user_id

    # Enable Trackio auto-init for this job if requested. When set, the lab SDK
    # running inside the remote script can automatically initialize Trackio
    # and capture metrics for visualization in the Tasks UI. For shared projects,
    # pass project name and run name so the SDK can build trackio_runs/{experiment_id}/{project_name}/.
    trackio_project_name_for_job: Optional[str] = None
    trackio_run_name_for_job: Optional[str] = None
    if request.enable_trackio:
        env_vars["TLAB_TRACKIO_AUTO_INIT"] = "true"
        project_name = (request.trackio_project_name or "").strip() or str(request.experiment_id)
        trackio_run_name = f"{request.task_name or 'task'}-job-{job_short_id}"
        trackio_project_name_for_job = project_name
        trackio_run_name_for_job = trackio_run_name
        env_vars["TLAB_TRACKIO_PROJECT_NAME"] = project_name
        env_vars["TLAB_TRACKIO_RUN_NAME"] = trackio_run_name
        # Create shared project dir so the SDK can sync into it; path is derived by dashboard when needed.
        workspace_dir = await get_workspace_dir()
        shared_path = storage.join(
            workspace_dir,
            "trackio_runs",
            secure_filename(str(request.experiment_id)),
            secure_filename(project_name),
        )
        await storage.makedirs(shared_path, exist_ok=True)

    if request.enable_profiling:
        env_vars["_TFL_PROFILING"] = "1"
        if request.enable_profiling_torch:
            env_vars["_TFL_PROFILING_TORCH"] = "1"

    # Get TFL_STORAGE_URI from storage context
    tfl_storage_uri = None
    try:
        storage_root = await storage.root_uri()
        if storage_root:
            if storage.is_remote_path(storage_root):
                # Remote cloud storage (S3/GCS/etc.)
                tfl_storage_uri = storage_root
            elif STORAGE_PROVIDER == "localfs":
                # localfs: expose the local mount path to the remote worker
                tfl_storage_uri = storage_root
    except Exception:
        pass

    if tfl_storage_uri:
        env_vars["TFL_STORAGE_URI"] = tfl_storage_uri

    # For local provider, set TFL_WORKSPACE_DIR so the lab SDK in the subprocess can find
    # the job directory (workspace/jobs/<job_id>). The organization context for the API
    # request is already set by authentication middleware, so we can rely on
    # get_workspace_dir() without mutating the global org context here.
    if provider.type == ProviderType.LOCAL.value and team_id:
        workspace_dir = await get_workspace_dir()
        if workspace_dir and not storage.is_remote_path(workspace_dir):
            env_vars["TFL_WORKSPACE_DIR"] = workspace_dir

    # Resolve run command (and optional setup override) for interactive sessions from gallery
    base_command = request.run
    setup_override_from_gallery = None
    interactive_setup_added = False
    if request.subtype == "interactive" and request.interactive_gallery_id:
        gallery_list = await galleries.get_interactive_gallery()
        gallery_entry = find_interactive_gallery_entry(
            gallery_list,
            interactive_gallery_id=request.interactive_gallery_id,
        )
        if gallery_entry:
            environment = "local" if (provider.type == ProviderType.LOCAL.value or request.local) else "remote"
            # Run gallery/task setup for both local and remote interactive (SUDO prefix so $SUDO is defined).
            # Ngrok is installed only when tunnel logic runs (remote); setup has no ngrok.
            from transformerlab.shared.interactive_gallery_utils import INTERACTIVE_SUDO_PREFIX

            raw_setup = (gallery_entry.get("setup") or "").strip() or (request.setup or "").strip()
            if raw_setup:
                setup_commands.append(INTERACTIVE_SUDO_PREFIX + " " + raw_setup)
                interactive_setup_added = True

            resolved_cmd, setup_override_from_gallery = resolve_interactive_command(
                gallery_entry, environment, base_command=base_command
            )
            if resolved_cmd:
                base_command = INTERACTIVE_SUDO_PREFIX + " " + resolved_cmd
            if setup_override_from_gallery and team_secrets:
                setup_override_from_gallery = replace_secret_placeholders(setup_override_from_gallery, team_secrets)

    # If run command is still empty, fall back to the stored task's fields.
    # This handles GitHub-sourced interactive tasks where the command/setup
    # are in task.yaml and were stored in the task at import time.
    if not base_command.strip() and request.task_id:
        fallback_task = await task_service.task_get_by_id(request.task_id)
        if fallback_task:
            base_command = fallback_task.get("run", "") or fallback_task.get("command", "")
            # Also pick up setup from the task if not already added
            if not interactive_setup_added:
                fallback_setup = (fallback_task.get("setup", "") or "").strip()
                if fallback_setup:
                    from transformerlab.shared.interactive_gallery_utils import INTERACTIVE_SUDO_PREFIX

                    setup_commands.append(INTERACTIVE_SUDO_PREFIX + " " + fallback_setup)
                    interactive_setup_added = True

    # Add user-provided setup if any (replace secrets in setup).
    # For interactive tasks we already added gallery/task setup above (local and remote).
    if request.setup and not interactive_setup_added:
        setup_with_secrets = replace_secret_placeholders(request.setup, team_secrets) if team_secrets else request.setup
        setup_commands.append(setup_with_secrets)

    # Join setup commands, stripping trailing semicolons to avoid double semicolons
    if setup_commands:
        cleaned_commands = [cmd.rstrip(";").rstrip() for cmd in setup_commands if cmd.strip()]
        final_setup = ";".join(cleaned_commands) if cleaned_commands else None
    else:
        final_setup = None

    if setup_override_from_gallery is not None:
        final_setup = setup_override_from_gallery

    # Replace secrets in command
    command_with_secrets = replace_secret_placeholders(base_command, team_secrets) if team_secrets else base_command

    # Replace secrets in parameters if present
    # Merge parameters (defaults) with config (user's custom values for this run)
    merged_parameters = {}
    if request.parameters:
        merged_parameters = request.parameters.copy()
    if request.config:
        merged_parameters.update(request.config)

    # Extract any per-run custom SBATCH flags from config (used by SLURM provider)
    custom_sbatch_flags = None
    if request.config and "custom_sbatch_flags" in request.config:
        raw_flags = request.config.get("custom_sbatch_flags")
        if isinstance(raw_flags, str):
            custom_sbatch_flags = raw_flags.strip() or None
        elif raw_flags is not None:
            custom_sbatch_flags = str(raw_flags).strip() or None

    # Replace secrets in merged parameters
    parameters_with_secrets = None
    if merged_parameters and team_secrets:
        parameters_with_secrets = replace_secrets_in_dict(merged_parameters, team_secrets)
    else:
        parameters_with_secrets = merged_parameters if merged_parameters else None

    # For SkyPilot providers, resolve docker_image / region / use_spot.
    # Per-job overrides (from request.config) take precedence over provider-level defaults.
    skypilot_image_id: str | None = None
    skypilot_region: str | None = None
    skypilot_zone: str | None = None
    skypilot_use_spot: bool = False
    if provider.type == ProviderType.SKYPILOT.value:
        prov_cfg = provider.config or {}
        # Provider-level defaults
        skypilot_image_id = prov_cfg.get("docker_image") or None
        skypilot_region = prov_cfg.get("default_region") or None
        skypilot_zone = prov_cfg.get("default_zone") or None
        skypilot_use_spot = prov_cfg.get("use_spot", False) is True
        # Per-job overrides from the frontend config dict
        if request.config:
            if request.config.get("docker_image"):
                skypilot_image_id = str(request.config["docker_image"]).strip()
            if request.config.get("region"):
                skypilot_region = str(request.config["region"]).strip()
            if request.config.get("use_spot"):
                skypilot_use_spot = True

    # Build provider_config for cluster_config (and job_data for local provider)
    provider_config_dict = {"requested_disk_space": request.disk_space}
    # For SLURM, pass through any per-run custom SBATCH flags so the provider
    # can inject them into the generated SLURM script.
    if provider.type == ProviderType.SLURM.value and custom_sbatch_flags:
        provider_config_dict["custom_sbatch_flags"] = custom_sbatch_flags
    if provider.type == ProviderType.LOCAL.value:
        # Use a dedicated local-only job directory for the local provider.
        # This directory is always on the host filesystem and does not depend
        # on TFL_REMOTE_STORAGE_ENABLED / remote storage configuration.
        job_dir = await asyncio.to_thread(get_local_provider_job_dir, job_id, org_id=team_id)
        provider_config_dict["workspace_dir"] = job_dir

    # Copy task files (task.yaml and any attachments) into the job directory
    # so they are available to the running command on any provider.
    # index.json is excluded because the job system uses its own index.json
    # for metadata and overwriting it with the task's index.json would break
    # job status tracking.
    if request.task_id:
        task_dir_root = await get_task_dir()
        task_src = storage.join(task_dir_root, secure_filename(str(request.task_id)))
        if await storage.isdir(task_src):
            workspace_job_dir = await get_job_dir(job_id, request.experiment_id)
            await _copy_task_files_to_dir(task_src, workspace_job_dir)

    job_data = {
        "task_name": request.task_name,
        "run": command_with_secrets,
        "cluster_name": formatted_cluster_name,
        "subtype": request.subtype,
        "interactive_type": request.interactive_type,
        "interactive_gallery_id": request.interactive_gallery_id,
        "local": request.local,
        "cpus": request.cpus,
        "memory": request.memory,
        "disk_space": request.disk_space,
        "accelerators": request.accelerators,
        "num_nodes": request.num_nodes,
        "setup": final_setup,
        "env_vars": env_vars if env_vars else None,
        "file_mounts": request.file_mounts if request.file_mounts is not True else True,
        "parameters": parameters_with_secrets or None,
        "provider_id": provider.id,
        "provider_type": provider.type,
        "provider_name": provider_display_name,
        "user_info": user_info or None,
        "team_id": team_id,  # Store team_id for quota tracking
        "created_by_user_id": str(user.id) if user else None,
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    }
    if provider.type == ProviderType.LOCAL.value and provider_config_dict.get("workspace_dir"):
        job_data["workspace_dir"] = provider_config_dict["workspace_dir"]
    if request.file_mounts is True and request.task_id:
        job_data["task_id"] = request.task_id
    if trackio_project_name_for_job is not None:
        job_data["trackio_project_name"] = trackio_project_name_for_job
    if trackio_run_name_for_job is not None:
        job_data["trackio_run_name"] = trackio_run_name_for_job

    await job_service.job_update_job_data_insert_key_values(
        job_id, {k: v for k, v in job_data.items() if v is not None}, request.experiment_id
    )

    disk_size = None
    if request.disk_space:
        try:
            disk_size = int(request.disk_space)
        except (TypeError, ValueError):
            disk_size = None

    # When file_mounts is True we use lab.copy_file_mounts() in setup; do not send to provider
    file_mounts_for_provider = request.file_mounts if isinstance(request.file_mounts, dict) else {}

    # Validate that we have a non-empty command to run.
    if not command_with_secrets or not command_with_secrets.strip():
        raise HTTPException(
            status_code=400,
            detail="No run command resolved for this task. The task may be missing a 'run' or 'command' field.",
        )

    # Apply provider-level harness hooks (pre/post) around the task command.
    # Hooks are concatenated with ';' so the post hook always runs.
    from transformerlab.services.provider_harness_hook_service import build_hooked_command

    provider_config_for_hooks = provider.config or {}
    if isinstance(provider_config_for_hooks, str):
        try:
            provider_config_for_hooks = json.loads(provider_config_for_hooks)
        except Exception:
            provider_config_for_hooks = {}
    extra_config_for_hooks = (
        provider_config_for_hooks.get("extra_config", {}) if isinstance(provider_config_for_hooks, dict) else {}
    )
    if not isinstance(extra_config_for_hooks, dict):
        extra_config_for_hooks = {}

    pre_task_hook = extra_config_for_hooks.get("pre_task_hook")
    post_task_hook = extra_config_for_hooks.get("post_task_hook")
    command_with_hooks = build_hooked_command(
        command_with_secrets,
        pre_hook=str(pre_task_hook) if pre_task_hook is not None else None,
        post_hook=str(post_task_hook) if post_task_hook is not None else None,
    )

    # Apply provider-level setup hooks (pre/post) around the resolved setup script (if any).
    pre_setup_hook = extra_config_for_hooks.get("pre_setup_hook")
    post_setup_hook = extra_config_for_hooks.get("post_setup_hook")
    setup_with_hooks = final_setup
    if setup_with_hooks and str(setup_with_hooks).strip():
        setup_with_hooks = build_hooked_command(
            str(setup_with_hooks),
            pre_hook=str(pre_setup_hook) if pre_setup_hook is not None else None,
            post_hook=str(post_setup_hook) if post_setup_hook is not None else None,
        )

    # Wrap the user command with tfl-remote-trap so we can track live_status in job_data.
    # This uses the tfl-remote-trap helper from the transformerlab SDK, which:
    #   - sets job_data.live_status="started" when execution begins
    #   - sets job_data.live_status="finished" on success
    #   - sets job_data.live_status="crashed" on failure
    wrapped_run = f"tfl-remote-trap -- {command_with_hooks}"

    cluster_config = ClusterConfig(
        cluster_name=formatted_cluster_name,
        provider_name=provider_display_name,
        provider_id=provider.id,
        run=wrapped_run,
        setup=setup_with_hooks,
        env_vars=env_vars,
        cpus=request.cpus,
        memory=request.memory,
        accelerators=request.accelerators,
        num_nodes=request.num_nodes,
        disk_size=disk_size,
        file_mounts=file_mounts_for_provider,
        provider_config=provider_config_dict,
        image_id=skypilot_image_id,
        region=skypilot_region,
        zone=skypilot_zone,
        use_spot=skypilot_use_spot,
    )

    await job_service.job_update_launch_progress(
        job_id,
        request.experiment_id,
        phase="launching_cluster",
        percent=70,
        message="Launching cluster",
    )

    # For LOCAL provider, enqueue the launch and return immediately with WAITING status
    if provider.type == ProviderType.LOCAL.value:
        # Commit quota hold (if any) before enqueuing so the worker can see it
        if quota_hold:
            await session.commit()

        await job_service.job_update_launch_progress(
            job_id,
            request.experiment_id,
            phase="queued",
            percent=0,
            message="Queued for launch",
        )
        await enqueue_local_launch(
            job_id=str(job_id),
            experiment_id=request.experiment_id,
            provider_id=provider.id,
            team_id=team_id,
            cluster_name=formatted_cluster_name,
            cluster_config=cluster_config,
            quota_hold_id=str(quota_hold.id) if quota_hold else None,
            initial_status=JobStatus.INTERACTIVE if request.subtype == "interactive" else JobStatus.LAUNCHING,
        )

        return {
            "status": JobStatus.WAITING,
            "job_id": job_id,
            "cluster_name": formatted_cluster_name,
            "request_id": None,
            "message": "Local provider launch waiting in queue",
        }

    await enqueue_remote_launch(
        job_id=str(job_id),
        experiment_id=str(request.experiment_id),
        provider_id=str(provider.id),
        team_id=str(team_id),
        user_id=str(user.id),
        cluster_name=formatted_cluster_name,
        cluster_config=cluster_config,
        quota_hold_id=str(quota_hold.id) if quota_hold else None,
        subtype=request.subtype,
    )

    return {
        "status": "success",
        "job_id": job_id,
        "cluster_name": formatted_cluster_name,
        "request_id": None,
        "message": "Provider launch enqueued",
    }
