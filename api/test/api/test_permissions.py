"""Integration tests for the permissions management endpoints."""

import pytest


def test_list_permissions_empty(client):
    """Owner gets empty list when no rules exist."""
    team_id = client._team_id
    response = client.get(f"/teams/{team_id}/permissions")
    assert response.status_code == 200
    data = response.json()
    assert "permissions" in data
    assert isinstance(data["permissions"], list)


def test_create_permission_rule(client):
    """Owner can create a permission rule for a member."""
    team_id = client._team_id

    members_resp = client.get(f"/teams/{team_id}/members")
    assert members_resp.status_code == 200
    members = members_resp.json().get("members", [])

    if not members:
        pytest.skip("No members to test permissions with")

    target_user_id = members[0]["user_id"]

    payload = {
        "user_id": target_user_id,
        "resource_type": "experiment",
        "resource_id": "*",
        "actions": ["read", "execute"],
    }
    response = client.put(f"/teams/{team_id}/permissions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["resource_type"] == "experiment"
    assert data["resource_id"] == "*"
    assert set(data["actions"]) == {"read", "execute"}


def test_upsert_updates_existing_rule(client):
    """PUT with same user/resource_type/resource_id updates actions."""
    team_id = client._team_id
    members_resp = client.get(f"/teams/{team_id}/members")
    members = members_resp.json().get("members", [])
    if not members:
        pytest.skip("No members to test permissions with")
    target_user_id = members[0]["user_id"]

    client.put(
        f"/teams/{team_id}/permissions",
        json={
            "user_id": target_user_id,
            "resource_type": "model",
            "resource_id": "*",
            "actions": ["read"],
        },
    )

    response = client.put(
        f"/teams/{team_id}/permissions",
        json={
            "user_id": target_user_id,
            "resource_type": "model",
            "resource_id": "*",
            "actions": ["read", "write"],
        },
    )
    assert response.status_code == 200
    assert set(response.json()["actions"]) == {"read", "write"}


def test_get_permissions_for_user(client):
    """GET rules for a specific user returns their rules only."""
    team_id = client._team_id
    members_resp = client.get(f"/teams/{team_id}/members")
    members = members_resp.json().get("members", [])
    if not members:
        pytest.skip("No members to test permissions with")
    target_user_id = members[0]["user_id"]

    response = client.get(f"/teams/{team_id}/permissions/user/{target_user_id}")
    assert response.status_code == 200
    data = response.json()
    assert "permissions" in data
    for rule in data["permissions"]:
        assert rule["user_id"] == target_user_id


def test_delete_permission_rule(client):
    """DELETE removes a rule by ID."""
    team_id = client._team_id
    members_resp = client.get(f"/teams/{team_id}/members")
    members = members_resp.json().get("members", [])
    if not members:
        pytest.skip("No members to test permissions with")
    target_user_id = members[0]["user_id"]

    create_resp = client.put(
        f"/teams/{team_id}/permissions",
        json={
            "user_id": target_user_id,
            "resource_type": "dataset",
            "resource_id": "ds-1",
            "actions": ["read"],
        },
    )
    rule_id = create_resp.json()["id"]

    del_resp = client.delete(f"/teams/{team_id}/permissions/{rule_id}")
    assert del_resp.status_code == 200

    list_resp = client.get(f"/teams/{team_id}/permissions/user/{target_user_id}")
    ids = [r["id"] for r in list_resp.json()["permissions"]]
    assert rule_id not in ids


def test_create_permission_invalid_action(client):
    """Creating a rule with an invalid action returns 422."""
    team_id = client._team_id
    members_resp = client.get(f"/teams/{team_id}/members")
    members = members_resp.json().get("members", [])
    if not members:
        pytest.skip("No members to test permissions with")
    target_user_id = members[0]["user_id"]

    response = client.put(
        f"/teams/{team_id}/permissions",
        json={
            "user_id": target_user_id,
            "resource_type": "experiment",
            "resource_id": "*",
            "actions": ["fly"],
        },
    )
    # The app maps RequestValidationError → 400 (see api.py validation_exception_handler)
    assert response.status_code in (400, 422)
