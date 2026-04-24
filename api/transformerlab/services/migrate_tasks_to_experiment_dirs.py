"""
One-time task template directory layout migration, executed automatically at API startup.

Goal:
  Move legacy task template directories from:
    {workspace}/task/{task_id}/
  into:
    {workspace}/experiments/{exp_id}/tasks/{task_id}/

This runs per org (team) with org-scoped storage roots.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from lab import storage
from lab.dirs import get_workspace_dir, set_organization_id as lab_set_org_id

from transformerlab.services import team_service
from transformerlab.services.cache_service import cache

logger = logging.getLogger(__name__)

_tasks_migration_worker_task: Optional[asyncio.Task] = None


def _set_org_context(org_id: Optional[str]) -> None:
    if lab_set_org_id is not None:
        lab_set_org_id(org_id)


def _clear_org_context() -> None:
    _set_org_context(None)


def _basename(path: str) -> str:
    return str(path).rstrip("/").split("/")[-1]


def _get_experiment_id_from_index(index_data: dict[str, Any]) -> Optional[str]:
    for key in ("experiment_id", "experimentId", "experiment_name", "experimentName", "experiment"):
        value = index_data.get(key)
        if value is None:
            continue
        value_str = str(value).strip()
        if value_str:
            return value_str
    return None


async def _read_json(path: str) -> dict[str, Any]:
    async with await storage.open(path, "r", encoding="utf-8") as f:
        return json.loads(await f.read())


async def _iter_dir_names(parent_dir: str) -> list[str]:
    try:
        entries = await storage.ls(parent_dir, detail=True)
    except Exception:
        return []

    dir_names: list[str] = []
    for entry in entries:
        full_path = ""
        entry_type: Optional[str] = None
        if isinstance(entry, dict):
            full_path = entry.get("name") or entry.get("path") or ""
            entry_type = entry.get("type")
        else:
            full_path = str(entry)

        if not full_path:
            continue

        try:
            is_dir = entry_type == "directory" or await storage.isdir(full_path)
        except Exception:
            is_dir = entry_type == "directory"

        if is_dir:
            dir_names.append(_basename(full_path))

    return dir_names


async def _org_needs_tasks_migration(org_id: str) -> bool:
    _set_org_context(org_id)
    try:
        workspace_dir = await get_workspace_dir()
        old_task_dir = storage.join(workspace_dir, "task")
        if not await storage.exists(old_task_dir):
            return False
        return len(await _iter_dir_names(old_task_dir)) > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Tasks migration: org {org_id} pre-check failed: {exc}")
        return False
    finally:
        _clear_org_context()


async def _migrate_org_tasks(org_id: str) -> dict[str, Any]:
    _set_org_context(org_id)
    moved_tasks = 0
    skipped_tasks = 0
    touched_experiment_ids: set[str] = set()

    try:
        workspace_dir = await get_workspace_dir()
        old_task_dir = storage.join(workspace_dir, "task")
        experiments_dir = storage.join(workspace_dir, "experiments")

        if not await storage.exists(old_task_dir):
            return {
                "org_id": org_id,
                "moved_tasks": 0,
                "skipped_tasks": 0,
                "status": "no_old_task_dir",
            }

        if not await storage.exists(experiments_dir):
            await storage.makedirs(experiments_dir, exist_ok=True)

        task_ids = await _iter_dir_names(old_task_dir)
        logger.info(f"Tasks migration: org {org_id}: {len(task_ids)} candidate task dir(s)")

        for task_id in sorted(task_ids):
            task_dir = storage.join(old_task_dir, task_id)
            index_path = storage.join(task_dir, "index.json")
            if not await storage.exists(index_path):
                logger.warning(f"Tasks migration: org {org_id}: {task_id} missing index.json, skipping")
                skipped_tasks += 1
                continue

            try:
                index_data = await _read_json(index_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Tasks migration: org {org_id}: {task_id} index.json read failed: {exc}")
                skipped_tasks += 1
                continue

            experiment_id = _get_experiment_id_from_index(index_data)
            if not experiment_id:
                logger.warning(f"Tasks migration: org {org_id}: {task_id} missing experiment_id, skipping")
                skipped_tasks += 1
                continue

            dest_dir = storage.join(experiments_dir, experiment_id, "tasks", task_id)
            dest_exists = await storage.exists(dest_dir)
            src_exists = await storage.exists(task_dir)

            if dest_exists and not src_exists:
                skipped_tasks += 1
                continue
            if dest_exists and src_exists:
                logger.warning(f"Tasks migration: org {org_id}: {task_id} src+dest exist; manual resolution required")
                skipped_tasks += 1
                continue

            logger.info(f"Tasks migration: org {org_id}: move {task_id} -> {dest_dir}")
            await storage.copy_dir(task_dir, dest_dir)
            await storage.rm_tree(task_dir)
            moved_tasks += 1
            touched_experiment_ids.add(str(experiment_id))

        # Invalidate task list/detail cache tags for affected experiments so
        # clients don't wait for TTL after migration.
        for experiment_id in sorted(touched_experiment_ids):
            try:
                await cache.invalidate(f"tasks:{experiment_id}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Tasks migration: org %s: cache invalidation failed for experiment %s: %s",
                    org_id,
                    experiment_id,
                    exc,
                )

        return {
            "org_id": org_id,
            "moved_tasks": moved_tasks,
            "skipped_tasks": skipped_tasks,
            "cache_invalidated_experiments": sorted(touched_experiment_ids),
            "status": "migrated",
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Tasks migration: org {org_id} failed: {exc}")
        return {
            "org_id": org_id,
            "moved_tasks": moved_tasks,
            "skipped_tasks": skipped_tasks,
            "status": "error",
            "error": str(exc),
        }
    finally:
        _clear_org_context()


async def _tasks_migration_worker() -> None:
    try:
        org_ids = await team_service.get_all_team_ids()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Tasks migration worker: failed listing org ids: {exc}")
        return

    if not org_ids:
        logger.info("Tasks migration worker: no orgs found; nothing to migrate")
        return

    for org_id in org_ids:
        if await _org_needs_tasks_migration(org_id):
            result = await _migrate_org_tasks(org_id)
            logger.info(f"Tasks migration worker: result for org {org_id}: {result}")
        else:
            logger.info(f"Tasks migration worker: org {org_id} has no legacy task dirs")


async def start_tasks_migration_worker() -> None:
    global _tasks_migration_worker_task
    if _tasks_migration_worker_task is not None and not _tasks_migration_worker_task.done():
        return
    _tasks_migration_worker_task = asyncio.create_task(_tasks_migration_worker())


async def stop_tasks_migration_worker() -> None:
    global _tasks_migration_worker_task
    if _tasks_migration_worker_task is None:
        return
    if _tasks_migration_worker_task.done():
        return

    _tasks_migration_worker_task.cancel()
    try:
        await _tasks_migration_worker_task
    except asyncio.CancelledError:
        pass
    finally:
        _tasks_migration_worker_task = None
