import json
import os

from typing import Annotated

from fastapi import APIRouter, Body, Request, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

import transformerlab.services.experiment_service as experiment_service
from lab import Dataset, Experiment, storage
from transformerlab.shared import shared
from transformerlab.routers.experiment import (
    documents,
    jobs,
    task as task_router,
)
from transformerlab.routers.auth import get_user_and_team
from transformerlab.services.permission_service import check_permission, require_permission
from transformerlab.shared.models.user_model import get_async_session
from lab.dirs import get_workspace_dir

from werkzeug.utils import secure_filename

router = APIRouter(prefix="/experiment")

router.include_router(
    router=documents.router,
    prefix="/{experimentId}",
    tags=["documents"],
    dependencies=[Depends(require_permission("experiment", "read", id_param="experimentId"))],
)
router.include_router(
    router=jobs.router,
    prefix="/{experimentId}",
    tags=["jobs"],
    dependencies=[Depends(require_permission("experiment", "read", id_param="experimentId"))],
)
router.include_router(
    router=task_router.router,
    prefix="/{experimentId}",
    tags=["task"],
    dependencies=[Depends(require_permission("experiment", "read", id_param="experimentId"))],
)


@router.get("/", summary="Get all Experiments", tags=["experiment"])
async def experiments_get_all(
    session: AsyncSession = Depends(get_async_session),
    user_and_team: dict = Depends(get_user_and_team),
):
    """Get a list of all experiments"""
    experiments = await experiment_service.experiment_get_all()
    user = user_and_team["user"]
    team_id = user_and_team["team_id"]

    filtered_experiments = []
    for experiment in experiments:
        experiment_id = str(experiment.get("id"))
        if not experiment_id:
            continue
        allowed = await check_permission(
            session=session,
            user_id=str(user.id),
            team_id=team_id,
            resource_type="experiment",
            resource_id=experiment_id,
            action="read",
        )
        if allowed:
            filtered_experiments.append(experiment)
    return filtered_experiments


@router.get("/create", summary="Create Experiment", tags=["experiment"])
async def experiments_create(name: str):
    # Apply secure filename validation to the experiment name
    secure_name = secure_filename(name)

    newid = await experiment_service.experiment_create(secure_name, {})
    return newid


@router.get("/{id}", summary="Get Experiment by ID", tags=["experiment"])
async def experiment_get(
    id: str,
    _: None = Depends(require_permission("experiment", "read")),
):
    data = await experiment_service.experiment_get(id)

    if data is None:
        return {"status": "error", "message": f"Experiment {id} does not exist"}

    # config is already parsed as dict in experiment_get
    return data


@router.get("/{id}/delete", tags=["experiment"])
async def experiments_delete(
    id: str,
    _: None = Depends(require_permission("experiment", "delete")),
):
    await experiment_service.experiment_delete(id)
    return {"message": f"Experiment {id} deleted"}


@router.get("/{id}/update", tags=["experiment"])
async def experiments_update(
    id: str,
    name: str,
    _: None = Depends(require_permission("experiment", "write")),
):
    await experiment_service.experiment_update(id, name)
    return {"message": f"Experiment {id} updated to {name}"}


@router.get("/{id}/update_config", tags=["experiment"])
async def experiments_update_config(
    id: str,
    key: str,
    value: str,
    _: None = Depends(require_permission("experiment", "write")),
):
    await experiment_service.experiment_update_config(id, key, value)
    return {"message": f"Experiment {id} updated"}


@router.post("/{id}/update_configs", tags=["experiment"])
async def experiments_update_configs(
    id: str,
    updates: Annotated[dict, Body()],
    _: None = Depends(require_permission("experiment", "write")),
):
    await experiment_service.experiment_update_configs(id, updates)
    return {"message": f"Experiment {id} configs updated"}


@router.post("/{id}/prompt", tags=["experiment"])
async def experiments_save_prompt_template(
    id: str,
    template: Annotated[str, Body()],
    _: None = Depends(require_permission("experiment", "write")),
):
    await experiment_service.experiment_save_prompt_template(id, template)
    return {"message": f"Experiment {id} prompt template saved"}


@router.post("/{id}/save_file_contents", tags=["experiment"])
async def experiment_save_file_contents(
    id: str,
    filename: str,
    file_contents: Annotated[str, Body()],
    _: None = Depends(require_permission("experiment", "write")),
):
    filename = secure_filename(filename)

    # remove file extension from file:
    [filename, file_ext] = os.path.splitext(filename)

    if (file_ext != ".py") and (file_ext != ".ipynb") and (file_ext != ".md"):
        return {"message": f"File extension {file_ext} not supported"}

    # clean the file name:
    filename = shared.slugify(filename)

    exp_obj = await Experiment.get(id)
    experiment_dir = await exp_obj.get_dir()

    # For remote paths, use storage.join which handles remote URIs properly
    file_path = storage.join(experiment_dir, f"{filename}{file_ext}")
    # Basic path traversal check: ensure filename doesn't contain path separators
    if "/" in filename or "\\" in filename:
        return {"message": "Invalid file path - path traversal detected"}

    # Save the file contents securely
    async with await storage.open(file_path, "w", encoding="utf-8") as f:
        await f.write(file_contents)

    return {"message": f"{file_path} file contents saved"}


@router.get("/{id}/file_contents", tags=["experiment"])
async def experiment_get_file_contents(
    id: str,
    filename: str,
    _: None = Depends(require_permission("experiment", "read")),
):
    filename = secure_filename(filename)

    exp_obj = await Experiment.get(id)
    experiment_dir = await exp_obj.get_dir()

    # remove file extension from file:
    [filename, file_ext] = os.path.splitext(filename)

    allowed_extensions = [".py", ".ipynb", ".md", ".txt"]

    if file_ext not in allowed_extensions:
        return {"message": f"File extension {file_ext} for {filename} not supported"}

    # clean the file name:
    # filename = shared.slugify(filename)

    # For remote paths, use storage.join which handles remote URIs properly
    # Basic path traversal check: ensure filename doesn't contain path separators
    if "/" in filename or "\\" in filename:
        return {"message": "Invalid file path - path traversal detected"}
    final_path = storage.join(experiment_dir, filename + file_ext)

    print("Listing Contents of File: " + final_path)

    # now get the file contents
    try:
        async with await storage.open(final_path, "r") as f:
            file_contents = await f.read()
    except FileNotFoundError:
        return ""

    return file_contents


@router.get("/{id}/export_to_recipe", summary="Export experiment to recipe format", tags=["experiment"])
async def export_experiment_to_recipe(
    id: str,
    request: Request,
    _: None = Depends(require_permission("experiment", "read")),
):
    """Export an experiment to JSON format that matches the recipe gallery structure."""

    # Get experiment data
    data = await experiment_service.experiment_get(id)
    if data is None:
        return {"status": "error", "message": f"Experiment {id} does not exist"}

    # Get experiment config - now returns a dict directly
    config = data["config"]

    # Initialize the export structure
    export_data = {
        "title": data["name"],
        "description": config.get("description", ""),
        "notes": "",
        "dependencies": [],
        "tasks": [],
        "workflows": [],
    }

    # Get the notes content from readme.md if it exists
    exp_obj = await Experiment.get(id)
    experiment_dir = await exp_obj.get_dir()
    notes_path = storage.join(experiment_dir, "readme.md")
    try:
        async with await storage.open(notes_path, "r") as f:
            export_data["notes"] = await f.read()
    except FileNotFoundError:
        # If no notes file exists, leave it as empty string
        pass

    # Track unique dependencies to avoid duplicates
    added_dependencies = set()

    async def add_dependency(dep_type: str, dep_name: str):
        """Helper function to add a dependency if it's not already added"""
        dep_key = f"{dep_type}:{dep_name}"
        if dep_key not in added_dependencies and dep_name:
            # For datasets, check if it's generated and skip if it is
            if dep_type == "dataset":
                try:
                    dataset_info = await Dataset.get(dep_name)
                    if dataset_info:
                        json_data = await dataset_info.get_metadata()
                        json_data = json_data.get("json_data", {})
                        if not isinstance(json_data, dict):
                            json_data = json.loads(json_data)
                        if json_data.get("generated", False):
                            print(f"Skipping generated dataset dependency: {dep_name}")
                            return
                except Exception:
                    # If we can't determine if it's generated, proceed to add it
                    pass

            dependency_entry = {"type": dep_type, "name": dep_name}
            export_data["dependencies"].append(dependency_entry)
            added_dependencies.add(dep_key)

    # Get tasks for each type (TRAIN, EVAL, GENERATE)
    task_types = ["TRAIN", "EVAL", "GENERATE", "EXPORT"]
    for task_type in task_types:
        from transformerlab.services.tasks_service import tasks_service

        tasks = await tasks_service.tasks_get_by_type_in_experiment(task_type, id)
        for task in tasks:
            if not isinstance(task["config"], dict):
                task_config = json.loads(task["config"])
            else:
                task_config = task["config"]

            # Add model dependency from task
            if task_type == "EXPORT":
                # For EXPORT tasks, we assume the model is already set in the experiment config
                model_name = task_config.get("input_model_id")
            else:
                model_name = task_config.get("model_name")
            if model_name:
                await add_dependency("model", model_name)

            # Add dataset dependency from task
            dataset_name = task_config.get("dataset_name")
            if dataset_name:
                await add_dependency("dataset", dataset_name)

            # Add plugin dependency
            plugin_name = task_config.get("plugin_name")
            if plugin_name:
                await add_dependency("plugin", plugin_name)

            # Add task to tasks list with its configuration
            export_data["tasks"].append(
                {
                    "name": task["name"],
                    "task_type": task["type"],
                    "plugin": task["plugin"],
                    "config_json": task["config"],
                    "inputs_json": task["inputs"],
                }
            )

    # Add workflows - COMMENTED OUT as workflows are being removed
    # workflows = await workflows_get_from_experiment(id)
    # for workflow in workflows:
    #     if workflow["status"] != "DELETED":  # Only include active workflows
    #         export_data["workflows"].append({"name": workflow["name"], "config": json.loads(workflow["config"])})

    # For now, just ensure workflows is an empty list
    export_data["workflows"] = []

    # Write to file in the workspace directory (org-aware via request context)
    workspace_dir = await get_workspace_dir()
    output_file = storage.join(workspace_dir, f"{data['name']}_export.json")
    async with await storage.open(output_file, "w") as f:
        await f.write(json.dumps(export_data, indent=2))

    return FileResponse(output_file, filename=output_file)
