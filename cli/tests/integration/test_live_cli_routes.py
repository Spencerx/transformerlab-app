"""Live API smoke tests for API routes touched by the CLI.

These tests run against a real server and validate route contracts that CLI commands rely on.
They are skipped by default unless TLAB_RUN_LIVE_SERVER_TESTS=1 is set.
"""

import os
import uuid

import httpx
import pytest


RUN_LIVE_TESTS = os.getenv("TLAB_RUN_LIVE_SERVER_TESTS") == "1"
BASE_URL = os.getenv("TLAB_LIVE_SERVER_URL", "http://127.0.0.1:8338").rstrip("/")
LOGIN_EMAIL = os.getenv("TLAB_LIVE_TEST_EMAIL", "admin@example.com")
LOGIN_PASSWORD = os.getenv("TLAB_LIVE_TEST_PASSWORD", "admin123")


pytestmark = pytest.mark.skipif(not RUN_LIVE_TESTS, reason="Set TLAB_RUN_LIVE_SERVER_TESTS=1 to run live tests")


def _auth_headers(client: httpx.Client) -> dict[str, str]:
    login_response = client.post(
        f"{BASE_URL}/auth/jwt/login",
        data={"username": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_response.status_code == 200, login_response.text

    token = login_response.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    teams_response = client.get(f"{BASE_URL}/users/me/teams", headers=auth_headers)
    assert teams_response.status_code == 200, teams_response.text

    teams_payload = teams_response.json()
    teams_list: list[dict]
    if isinstance(teams_payload, list):
        teams_list = teams_payload
    elif isinstance(teams_payload, dict):
        # Different API versions can return a wrapped object.
        if isinstance(teams_payload.get("teams"), list):
            teams_list = teams_payload["teams"]
        elif isinstance(teams_payload.get("data"), list):
            teams_list = teams_payload["data"]
        else:
            teams_list = []
    else:
        teams_list = []

    assert teams_list, f"Expected at least one team for the test user, got: {teams_payload!r}"
    team_id = teams_list[0]["id"]

    return {**auth_headers, "X-Team-Id": str(team_id)}


def _first_experiment_id(client: httpx.Client, headers: dict[str, str]) -> str:
    experiments_response = client.get(f"{BASE_URL}/experiment/", headers=headers)
    assert experiments_response.status_code == 200, experiments_response.text

    payload = experiments_response.json()
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            experiment_id = first.get("id")
            assert experiment_id, f"Experiment object missing id: {first!r}"
            return str(experiment_id)
        return str(first)
    if isinstance(payload, dict):
        for key in ("experiments", "data"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict):
                    experiment_id = first.get("id")
                    assert experiment_id, f"Experiment object missing id: {first!r}"
                    return str(experiment_id)
                return str(first)

    raise AssertionError(f"Expected at least one experiment, got: {payload!r}")


def _assert_status_in(response: httpx.Response, expected: set[int], route_name: str) -> None:
    assert response.status_code in expected, (
        f"{route_name} returned unexpected status {response.status_code}. "
        f"Expected one of {sorted(expected)}. Body: {response.text}"
    )


def _assert_not_found_contract(response: httpx.Response, route_name: str) -> None:
    """Accept both normal 404 and legacy 200 + NOT FOUND payload patterns."""
    if response.status_code == 404:
        return

    if response.status_code == 200:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = str(payload.get("message", payload.get("detail", ""))).lower()
        assert "not found" in message, (
            f"{route_name} returned 200 but did not indicate missing resource. Body: {response.text}"
        )
        return

    raise AssertionError(
        f"{route_name} returned unexpected status {response.status_code}. "
        f"Expected 404 or legacy 200/NOT FOUND. Body: {response.text}"
    )


def test_cli_route_contract_live_server() -> None:
    """Smoke test route contracts across all major CLI command groups."""
    provider_id: str | None = None
    experiment_id: str | None = None
    fake_task_id = "route-smoke-task-id"
    fake_job_id = "route-smoke-job-id"

    with httpx.Client(timeout=30.0) as client:
        headers = _auth_headers(client)
        auth_only_headers = {"Authorization": headers["Authorization"]}

        # Server/auth/user routes
        health_response = client.get(f"{BASE_URL}/healthz")
        _assert_status_in(health_response, {200}, "GET /healthz")

        user_response = client.get(f"{BASE_URL}/users/me", headers=auth_only_headers)
        _assert_status_in(user_response, {200}, "GET /users/me")

        teams_response = client.get(f"{BASE_URL}/users/me/teams", headers=auth_only_headers)
        _assert_status_in(teams_response, {200}, "GET /users/me/teams")

        # Experiment routes
        experiment_id = _first_experiment_id(client, headers)

        # Compute-provider routes
        list_response = client.get(f"{BASE_URL}/compute_provider/providers/?include_disabled=false", headers=headers)
        _assert_status_in(list_response, {200}, "GET /compute_provider/providers/")

        create_payload = {
            "name": f"cli-route-smoke-{uuid.uuid4().hex[:8]}",
            "type": "local",
            "config": {},
        }
        create_response = client.post(f"{BASE_URL}/compute_provider/providers/", headers=headers, json=create_payload)
        _assert_status_in(create_response, {200}, "POST /compute_provider/providers/")
        provider_id = create_response.json().get("id")
        assert provider_id, "Provider create response did not include id"

        info_response = client.get(f"{BASE_URL}/compute_provider/providers/{provider_id}", headers=headers)
        _assert_status_in(info_response, {200}, "GET /compute_provider/providers/{id}")

        provider_check_response = client.get(
            f"{BASE_URL}/compute_provider/providers/{provider_id}/check", headers=headers
        )
        _assert_status_in(
            provider_check_response,
            {200, 400, 404, 422},
            "GET /compute_provider/providers/{id}/check",
        )

        disable_response = client.patch(
            f"{BASE_URL}/compute_provider/providers/{provider_id}",
            headers=headers,
            json={"disabled": True},
        )
        _assert_status_in(disable_response, {200}, "PATCH /compute_provider/providers/{id} disable")

        enable_response = client.patch(
            f"{BASE_URL}/compute_provider/providers/{provider_id}",
            headers=headers,
            json={"disabled": False},
        )
        _assert_status_in(enable_response, {200}, "PATCH /compute_provider/providers/{id} enable")

        # Task and launch routes
        task_list_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/task/list_by_type_in_experiment?type=REMOTE",
            headers=headers,
        )
        _assert_status_in(task_list_response, {200}, "GET /experiment/{id}/task/list_by_type_in_experiment")

        task_gallery_response = client.get(f"{BASE_URL}/experiment/{experiment_id}/task/gallery", headers=headers)
        _assert_status_in(task_gallery_response, {200}, "GET /experiment/{id}/task/gallery")

        task_gallery_interactive_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/task/gallery/interactive",
            headers=headers,
        )
        _assert_status_in(task_gallery_interactive_response, {200}, "GET /experiment/{id}/task/gallery/interactive")

        validate_response = client.post(
            f"{BASE_URL}/experiment/{experiment_id}/task/validate",
            headers={**headers, "Content-Type": "text/plain"},
            content="name: smoke\nrun: echo hi\ntype: trainer\n",
        )
        _assert_status_in(validate_response, {200, 400, 422}, "POST /experiment/{id}/task/validate")

        task_get_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/task/{fake_task_id}/get", headers=headers
        )
        _assert_not_found_contract(task_get_response, "GET /experiment/{id}/task/{task_id}/get")

        task_delete_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/task/{fake_task_id}/delete",
            headers=headers,
        )
        _assert_status_in(task_delete_response, {200, 404}, "GET /experiment/{id}/task/{task_id}/delete")

        task_create_json_response = client.post(
            f"{BASE_URL}/experiment/{experiment_id}/task/create",
            headers=headers,
            json={"github_repo_url": "https://github.com/does-not-exist/repo"},
        )
        _assert_status_in(task_create_json_response, {200, 400, 404, 422}, "POST /experiment/{id}/task/create (json)")

        task_gallery_import_response = client.post(
            f"{BASE_URL}/experiment/{experiment_id}/task/gallery/import",
            headers=headers,
            json={
                "gallery_id": "route-smoke-gallery-id",
                "experiment_id": experiment_id,
                "is_interactive": False,
            },
        )
        _assert_status_in(
            task_gallery_import_response, {200, 400, 404, 422}, "POST /experiment/{id}/task/gallery/import"
        )

        # CLI launch uses this endpoint; a minimal payload may fail validation but should not 500.
        launch_response = client.post(
            f"{BASE_URL}/compute_provider/providers/{provider_id}/launch/",
            headers=headers,
            json={},
        )
        _assert_status_in(launch_response, {200, 202, 400, 404, 422}, "POST /compute_provider/providers/{id}/launch/")

        # Job/artifact/log routes
        jobs_list_response = client.get(f"{BASE_URL}/experiment/{experiment_id}/jobs/list?type=REMOTE", headers=headers)
        _assert_status_in(jobs_list_response, {200}, "GET /experiment/{id}/jobs/list")

        stop_job_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/jobs/{fake_job_id}/stop", headers=headers
        )
        _assert_not_found_contract(stop_job_response, "GET /experiment/{id}/jobs/{job_id}/stop")

        provider_logs_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/jobs/{fake_job_id}/provider_logs",
            headers=headers,
        )
        _assert_not_found_contract(provider_logs_response, "GET /experiment/{id}/jobs/{job_id}/provider_logs")

        stream_output_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/jobs/{fake_job_id}/stream_output",
            headers=headers,
        )
        _assert_not_found_contract(stream_output_response, "GET /experiment/{id}/jobs/{job_id}/stream_output")

        request_logs_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/jobs/{fake_job_id}/request_logs",
            headers=headers,
        )
        _assert_not_found_contract(request_logs_response, "GET /experiment/{id}/jobs/{job_id}/request_logs")

        tunnel_info_response = client.get(
            f"{BASE_URL}/experiment/{experiment_id}/jobs/{fake_job_id}/tunnel_info",
            headers=headers,
        )
        _assert_not_found_contract(tunnel_info_response, "GET /experiment/{id}/jobs/{job_id}/tunnel_info")

        artifacts_response = client.get(f"{BASE_URL}/jobs/{fake_job_id}/artifacts", headers=headers)
        _assert_status_in(artifacts_response, {200, 404}, "GET /jobs/{job_id}/artifacts")

        artifact_download_response = client.get(
            f"{BASE_URL}/jobs/{fake_job_id}/artifact/does-not-exist.txt?task=download",
            headers=headers,
        )
        _assert_status_in(artifact_download_response, {404, 405}, "GET /jobs/{job_id}/artifact/{filename}")

        artifacts_zip_response = client.get(f"{BASE_URL}/jobs/{fake_job_id}/artifacts/download_all", headers=headers)
        _assert_not_found_contract(artifacts_zip_response, "GET /jobs/{job_id}/artifacts/download_all")

        publish_dataset_response = client.post(
            f"{BASE_URL}/experiment/{experiment_id}/jobs/{fake_job_id}/datasets/does-not-exist/save_to_registry"
            "?mode=new&tag=latest&version_label=v1",
            headers=headers,
        )
        _assert_status_in(
            publish_dataset_response,
            {400, 404, 422},
            "POST /experiment/{id}/jobs/{job_id}/datasets/{name}/save_to_registry",
        )

        publish_model_response = client.post(
            f"{BASE_URL}/experiment/{experiment_id}/jobs/{fake_job_id}/models/does-not-exist/save_to_registry"
            "?mode=new&tag=latest&version_label=v1",
            headers=headers,
        )
        _assert_status_in(
            publish_model_response,
            {400, 404, 422},
            "POST /experiment/{id}/jobs/{job_id}/models/{name}/save_to_registry",
        )

        delete_response = client.delete(f"{BASE_URL}/compute_provider/providers/{provider_id}", headers=headers)
        _assert_status_in(delete_response, {200}, "DELETE /compute_provider/providers/{id}")
        provider_id = None

    # Best-effort cleanup if assertions fail mid-test.
    if provider_id:
        with httpx.Client(timeout=30.0) as client:
            headers = _auth_headers(client)
            client.delete(f"{BASE_URL}/compute_provider/providers/{provider_id}", headers=headers)
