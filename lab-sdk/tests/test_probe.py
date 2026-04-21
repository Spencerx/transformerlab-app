import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_probe_writes_sentinel_file():
    """Probe writes a sentinel JSON file to TFL_STORAGE_URI/debug/storage-probe-{job_id}.txt."""
    written: dict = {}

    mock_file = MagicMock()
    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
    mock_file.__aexit__ = AsyncMock(return_value=None)

    async def capture(data):
        written["data"] = data

    mock_file.write = capture

    with patch.dict(
        os.environ,
        {
            "_TFL_JOB_ID": "job-abc",
            "TFL_STORAGE_URI": "/tmp/probe-test-workspace",
            "TFL_STORAGE_PROVIDER": "localfs",
        },
    ):
        import importlib
        import lab.probe as probe_mod

        importlib.reload(probe_mod)
        with patch.object(probe_mod.storage, "makedirs", new=AsyncMock()):
            with patch.object(probe_mod.storage, "open", return_value=mock_file):
                await probe_mod._run()

    assert "data" in written
    payload = json.loads(written["data"])
    assert payload["job_id"] == "job-abc"
    assert payload["storage_uri"] == "/tmp/probe-test-workspace"
    assert payload["storage_provider"] == "localfs"


@pytest.mark.asyncio
async def test_probe_falls_back_when_no_storage_uri(tmp_path):
    """Probe falls back to get_workspace_dir() when TFL_STORAGE_URI is not set."""
    written: dict = {}

    mock_file = MagicMock()
    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
    mock_file.__aexit__ = AsyncMock(return_value=None)

    async def capture(data):
        written["data"] = data

    mock_file.write = capture

    env = {k: v for k, v in os.environ.items() if k not in ("TFL_STORAGE_URI",)}
    env["_TFL_JOB_ID"] = "job-xyz"

    with patch.dict(os.environ, env, clear=True):
        import importlib
        import lab.probe as probe_mod

        importlib.reload(probe_mod)
        with patch.object(probe_mod.storage, "makedirs", new=AsyncMock()):
            with patch.object(probe_mod.storage, "open", return_value=mock_file):
                with patch("lab.dirs.get_workspace_dir", new=AsyncMock(return_value=str(tmp_path))):
                    await probe_mod._run()

    assert "data" in written
    payload = json.loads(written["data"])
    assert payload["job_id"] == "job-xyz"
