import json
import os
import pytest


# Point staging at a temp dir for tests
@pytest.fixture(autouse=True)
def isolated_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "transformerlab.services.upload_service.STAGING_ROOT",
        str(tmp_path / "staging"),
    )
    yield


def test_init_creates_staging_dir():
    import asyncio
    from transformerlab.services.upload_service import init_upload, STAGING_ROOT

    result = asyncio.run(init_upload("model.zip", 1024 * 1024))

    assert "upload_id" in result
    assert result["chunk_size"] == 64 * 1024 * 1024
    staging = os.path.join(STAGING_ROOT, result["upload_id"])
    assert os.path.isdir(staging)
    with open(os.path.join(staging, "meta.json")) as f:
        meta = json.load(f)
    assert meta["filename"] == "model.zip"
    assert meta["total_size"] == 1024 * 1024


def test_save_chunk_writes_file():
    import asyncio
    from transformerlab.services.upload_service import init_upload, save_chunk, STAGING_ROOT

    r = asyncio.run(init_upload("data.bin", 200))
    uid = r["upload_id"]

    received = asyncio.run(save_chunk(uid, 0, b"hello chunk 0"))

    chunk_path = os.path.join(STAGING_ROOT, uid, "0")
    assert os.path.isfile(chunk_path)
    assert open(chunk_path, "rb").read() == b"hello chunk 0"
    assert received == [0]


def test_save_chunk_idempotent():
    import asyncio
    from transformerlab.services.upload_service import init_upload, save_chunk

    r = asyncio.run(init_upload("data.bin", 200))
    uid = r["upload_id"]

    asyncio.run(save_chunk(uid, 0, b"first write"))
    asyncio.run(save_chunk(uid, 0, b"second write"))

    from transformerlab.services.upload_service import STAGING_ROOT

    chunk_path = os.path.join(STAGING_ROOT, uid, "0")
    assert open(chunk_path, "rb").read() == b"second write"


def test_get_status_returns_received_chunks():
    import asyncio
    from transformerlab.services.upload_service import init_upload, save_chunk, get_status

    r = asyncio.run(init_upload("data.bin", 300))
    uid = r["upload_id"]
    asyncio.run(save_chunk(uid, 0, b"a"))
    asyncio.run(save_chunk(uid, 2, b"c"))

    status = asyncio.run(get_status(uid))

    assert status["upload_id"] == uid
    assert status["received"] == [0, 2]
    assert status["complete"] is False


def test_assemble_upload_concatenates_chunks():
    import asyncio
    from transformerlab.services.upload_service import init_upload, save_chunk, assemble_upload_sync, STAGING_ROOT

    r = asyncio.run(init_upload("data.bin", 6))
    uid = r["upload_id"]
    asyncio.run(save_chunk(uid, 0, b"ABC"))
    asyncio.run(save_chunk(uid, 1, b"DEF"))

    path = assemble_upload_sync(uid, total_chunks=2)

    assert open(path, "rb").read() == b"ABCDEF"
    # _staging_dir returns os.path.realpath(), so compare against the resolved path.
    assert path == os.path.realpath(os.path.join(STAGING_ROOT, uid, "assembled"))


def test_assemble_upload_raises_on_missing_chunks():
    import asyncio
    from transformerlab.services.upload_service import init_upload, save_chunk, assemble_upload_sync

    r = asyncio.run(init_upload("data.bin", 9))
    uid = r["upload_id"]
    asyncio.run(save_chunk(uid, 0, b"AAA"))
    # chunk 1 is missing

    with pytest.raises(ValueError, match="Missing chunks"):
        assemble_upload_sync(uid, total_chunks=2)


def test_delete_upload_removes_dir():
    import asyncio
    from transformerlab.services.upload_service import init_upload, delete_upload, STAGING_ROOT

    r = asyncio.run(init_upload("data.bin", 10))
    uid = r["upload_id"]

    asyncio.run(delete_upload(uid))

    assert not os.path.isdir(os.path.join(STAGING_ROOT, uid))


def test_get_assembled_path_returns_path_when_assembled():
    import asyncio
    from transformerlab.services.upload_service import init_upload, save_chunk, assemble_upload_sync, get_assembled_path

    r = asyncio.run(init_upload("data.bin", 3))
    uid = r["upload_id"]
    asyncio.run(save_chunk(uid, 0, b"XYZ"))
    assembled = assemble_upload_sync(uid, total_chunks=1)

    result = asyncio.run(get_assembled_path(uid))

    assert result == assembled


def test_get_assembled_path_raises_when_not_assembled():
    import asyncio
    from transformerlab.services.upload_service import init_upload, get_assembled_path

    r = asyncio.run(init_upload("data.bin", 3))
    uid = r["upload_id"]

    with pytest.raises(ValueError, match="has not been assembled"):
        asyncio.run(get_assembled_path(uid))


def test_save_chunk_raises_on_unknown_upload_id():
    import asyncio
    from transformerlab.services.upload_service import save_chunk

    # Must be a valid 32-char hex UUID format but refer to an upload that doesn't exist.
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(save_chunk("a" * 32, 0, b"data"))


def test_save_chunk_raises_on_invalid_upload_id():
    import asyncio
    from transformerlab.services.upload_service import save_chunk

    with pytest.raises(ValueError, match="Invalid upload_id"):
        asyncio.run(save_chunk("../../etc/passwd", 0, b"data"))


def test_get_filename_returns_filename():
    import asyncio
    from transformerlab.services.upload_service import init_upload, get_filename

    r = asyncio.run(init_upload("my_model.zip", 500))
    uid = r["upload_id"]

    result = asyncio.run(get_filename(uid))

    assert result == "my_model.zip"


def test_sweep_removes_old_uploads(tmp_path, monkeypatch):
    import asyncio
    from transformerlab.services import upload_service as svc

    monkeypatch.setattr(svc, "STAGING_ROOT", str(tmp_path / "staging"))

    r = asyncio.run(svc.init_upload("old.bin", 10))
    uid = r["upload_id"]

    # Backdating meta.json created_at by 25 hours
    from datetime import datetime, timezone, timedelta

    meta_path = os.path.join(svc.STAGING_ROOT, uid, "meta.json")
    with open(meta_path) as f:
        meta = json.load(f)
    meta["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    with open(meta_path, "w") as f:
        json.dump(meta, f)

    count = svc.sweep_expired_uploads(max_age_hours=24)

    assert count == 1
    assert not os.path.isdir(os.path.join(svc.STAGING_ROOT, uid))
