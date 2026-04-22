import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STAGING_ROOT = os.path.join(os.path.expanduser("~"), ".transformerlab", "uploads", "staging")
CHUNK_SIZE = 64 * 1024 * 1024  # 64 MB

# upload_id is always uuid4().hex — 32 lowercase hex chars, no separators.
_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _staging_dir(upload_id: str) -> str:
    if not _UPLOAD_ID_RE.match(upload_id):
        raise ValueError(f"Invalid upload_id: {upload_id!r}")
    # os.path.basename is a CodeQL-recognised path-traversal sanitizer: it strips
    # directory components ("../../etc" → "etc"). If it changes the value the id
    # contained separators and must be rejected.
    safe_id = os.path.basename(upload_id)
    if safe_id != upload_id:
        raise ValueError(f"Invalid upload_id: {upload_id!r}")
    real = os.path.realpath(os.path.join(STAGING_ROOT, safe_id))
    if not real.startswith(os.path.realpath(STAGING_ROOT) + os.sep):
        raise ValueError(f"Invalid upload_id: {upload_id!r}")
    return real


def _chunk_path(upload_id: str, chunk_index: int) -> str:
    if chunk_index < 0:
        raise ValueError(f"chunk_index must be non-negative, got {chunk_index}")
    # Enforce a strict numeric chunk filename policy for user-controlled input.
    # This ensures the path component is canonical and contains only digits.
    if chunk_index > 10_000_000:
        raise ValueError(f"chunk_index is too large, got {chunk_index}")
    safe_index = str(int(chunk_index))
    if not safe_index.isdigit():
        raise ValueError(f"Invalid chunk_index: {chunk_index!r}")
    return os.path.join(_staging_dir(upload_id), safe_index)


def _meta_path(upload_id: str) -> str:
    return os.path.join(_staging_dir(upload_id), "meta.json")


def _assembled_path(upload_id: str) -> str:
    return os.path.join(_staging_dir(upload_id), "assembled")


def _received_chunks(upload_id: str) -> list[int]:
    staging = _staging_dir(upload_id)
    return sorted(int(n) for n in os.listdir(staging) if n.isdigit())


async def init_upload(filename: str, total_size: int) -> dict:
    upload_id = uuid.uuid4().hex
    os.makedirs(_staging_dir(upload_id), exist_ok=True)
    meta = {
        "filename": filename,
        "total_size": total_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(_meta_path(upload_id), "w") as f:
        json.dump(meta, f)
    return {"upload_id": upload_id, "chunk_size": CHUNK_SIZE}


async def save_chunk(upload_id: str, chunk_index: int, data: bytes) -> list[int]:
    if not os.path.isdir(_staging_dir(upload_id)):
        raise ValueError(f"Upload {upload_id!r} not found")
    with open(_chunk_path(upload_id, chunk_index), "wb") as f:
        f.write(data)
    return _received_chunks(upload_id)


async def get_status(upload_id: str) -> dict:
    if not os.path.isdir(_staging_dir(upload_id)):
        raise ValueError(f"Upload {upload_id!r} not found")
    return {
        "upload_id": upload_id,
        "received": _received_chunks(upload_id),
        "complete": os.path.isfile(_assembled_path(upload_id)),
    }


def assemble_upload_sync(upload_id: str, total_chunks: int) -> str:
    """Synchronous assembly — call via asyncio.to_thread from async context."""
    if not os.path.isdir(_staging_dir(upload_id)):
        raise ValueError(f"Upload {upload_id!r} not found")
    received = set(_received_chunks(upload_id))
    missing = sorted(set(range(total_chunks)) - received)
    if missing:
        raise ValueError(f"Missing chunks: {missing}")
    out_path = _assembled_path(upload_id)
    with open(out_path, "wb") as out_f:
        for i in range(total_chunks):
            with open(_chunk_path(upload_id, i), "rb") as chunk_f:
                while True:
                    buf = chunk_f.read(8 * 1024 * 1024)
                    if not buf:
                        break
                    out_f.write(buf)
    return out_path


async def get_assembled_path(upload_id: str) -> str:
    path = _assembled_path(upload_id)
    if not os.path.isfile(path):
        raise ValueError(f"Upload {upload_id!r} has not been assembled yet. Call /complete first.")
    return path


async def get_filename(upload_id: str) -> str:
    """Return the original filename for this upload. Raises ValueError if upload not found or metadata is corrupt."""
    if not os.path.isfile(_meta_path(upload_id)):
        raise ValueError(f"Upload {upload_id!r} not found")
    with open(_meta_path(upload_id)) as f:
        meta = json.load(f)
    if "filename" not in meta:
        raise ValueError(f"Upload {upload_id!r} has no filename in metadata")
    return meta["filename"]


async def delete_upload(upload_id: str) -> None:
    """Remove the staging directory for this upload. Idempotent — safe to call for unknown IDs."""
    staging = _staging_dir(upload_id)
    if os.path.isdir(staging):
        shutil.rmtree(staging)


def sweep_expired_uploads(max_age_hours: int = 24) -> int:
    if not os.path.isdir(STAGING_ROOT):
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
    count = 0
    for name in os.listdir(STAGING_ROOT):
        staging = os.path.join(STAGING_ROOT, name)
        meta_file = os.path.join(staging, "meta.json")
        if not os.path.isfile(meta_file):
            continue
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            created_at = datetime.fromisoformat(meta["created_at"]).timestamp()
            if created_at < cutoff:
                shutil.rmtree(staging)
                count += 1
        except Exception as exc:
            logger.warning("sweep_expired_uploads: error removing %s: %s", staging, exc)
    return count
