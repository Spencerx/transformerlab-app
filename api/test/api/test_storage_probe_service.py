import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_check_storage_probe_found():
    """check_storage_probe returns found=True when sentinel file exists."""
    with patch("transformerlab.services.compute_provider.storage_probe_service.set_organization_id") as mock_set_org:
        with patch(
            "transformerlab.services.compute_provider.storage_probe_service.get_workspace_dir",
            new=AsyncMock(return_value="/mnt/nfs/orgs/team1/workspace"),
        ):
            with patch("transformerlab.services.compute_provider.storage_probe_service.storage") as mock_storage:
                mock_storage.join = lambda *parts: "/".join(parts)
                mock_storage.exists = AsyncMock(return_value=True)

                from transformerlab.services.compute_provider.storage_probe_service import check_storage_probe

                result = await check_storage_probe(job_id="job-123", team_id="team1")

    assert result["found"] is True
    assert "storage-probe-job-123.txt" in result["path"]
    mock_set_org.assert_any_call("team1")
    mock_set_org.assert_any_call(None)


@pytest.mark.asyncio
async def test_check_storage_probe_not_found():
    """check_storage_probe returns found=False when sentinel file is missing."""
    with patch("transformerlab.services.compute_provider.storage_probe_service.set_organization_id"):
        with patch(
            "transformerlab.services.compute_provider.storage_probe_service.get_workspace_dir",
            new=AsyncMock(return_value="/mnt/nfs/orgs/team1/workspace"),
        ):
            with patch("transformerlab.services.compute_provider.storage_probe_service.storage") as mock_storage:
                mock_storage.join = lambda *parts: "/".join(parts)
                mock_storage.exists = AsyncMock(return_value=False)

                from transformerlab.services.compute_provider.storage_probe_service import check_storage_probe

                result = await check_storage_probe(job_id="job-999", team_id="team1")

    assert result["found"] is False


@pytest.mark.asyncio
async def test_launch_storage_probe_returns_job_id():
    """launch_storage_probe calls launch_template_on_provider and returns job_id."""
    mock_launch = AsyncMock(return_value={"job_id": 42, "status": "success"})

    with patch(
        "transformerlab.services.compute_provider.storage_probe_service.launch_template_on_provider",
        new=mock_launch,
    ):
        from transformerlab.services.compute_provider.storage_probe_service import launch_storage_probe

        user_and_team = {"team_id": "team1", "user": MagicMock(id="user1", first_name="", last_name="", email="")}
        result = await launch_storage_probe(
            provider_id="prov-1",
            user_and_team=user_and_team,
            session=MagicMock(),
        )

    assert result["job_id"] == 42
    assert result["experiment_id"] == "__storage_probe__"
    call_args = mock_launch.call_args
    request = call_args.kwargs["request"]
    assert request.run == "python -m lab.probe"
    assert request.experiment_id == "__storage_probe__"
    assert request.cpus == "1"
    assert request.accelerators is None
