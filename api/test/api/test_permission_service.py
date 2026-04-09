"""Unit tests for permission_service.check_permission()."""

from unittest.mock import AsyncMock, MagicMock

from transformerlab.services.permission_service import check_permission
from transformerlab.shared.models.models import UserTeam, TeamRole, ResourcePermission


def _make_session(*scalar_values):
    """
    Returns a mock AsyncSession whose execute() calls return each
    scalar_values item in order (via scalar_one_or_none).
    """
    session = AsyncMock()
    results = []
    for val in scalar_values:
        r = MagicMock()
        r.scalar_one_or_none.return_value = val
        results.append(r)
    session.execute.side_effect = results
    return session


def _owner(user_id="u1", team_id="t1"):
    return UserTeam(user_id=user_id, team_id=team_id, role=TeamRole.OWNER.value)


def _member(user_id="u1", team_id="t1"):
    return UserTeam(user_id=user_id, team_id=team_id, role=TeamRole.MEMBER.value)


def _rule(resource_type, resource_id, actions):
    return ResourcePermission(
        id="r1",
        user_id="u1",
        team_id="t1",
        resource_type=resource_type,
        resource_id=resource_id,
        actions=actions,
    )


# --- owner tests ---


async def test_owner_always_allowed_for_any_action():
    session = _make_session(_owner())
    assert await check_permission(session, "u1", "t1", "experiment", "exp1", "delete") is True


async def test_owner_allowed_even_for_admin_action():
    session = _make_session(_owner())
    assert await check_permission(session, "u1", "t1", "*", "*", "admin") is True


# --- non-member tests ---


async def test_non_member_is_denied():
    session = _make_session(None)
    assert await check_permission(session, "u1", "t1", "experiment", "exp1", "read") is False


# --- denylist default tests ---


async def test_member_with_no_acl_records_has_full_access():
    session = _make_session(_member(), None, None, None)
    assert await check_permission(session, "u1", "t1", "experiment", "exp1", "delete") is True


# --- exact match tests ---


async def test_member_exact_match_action_allowed():
    rule = _rule("experiment", "exp1", ["read", "execute"])
    session = _make_session(_member(), rule)
    assert await check_permission(session, "u1", "t1", "experiment", "exp1", "read") is True


async def test_member_exact_match_action_denied():
    rule = _rule("experiment", "exp1", ["read", "execute"])
    session = _make_session(_member(), rule)
    assert await check_permission(session, "u1", "t1", "experiment", "exp1", "delete") is False


# --- type wildcard tests ---


async def test_member_type_wildcard_action_allowed():
    rule = _rule("experiment", "*", ["read"])
    session = _make_session(_member(), None, rule)
    assert await check_permission(session, "u1", "t1", "experiment", "exp-any", "read") is True


async def test_member_type_wildcard_action_denied():
    rule = _rule("experiment", "*", ["read"])
    session = _make_session(_member(), None, rule)
    assert await check_permission(session, "u1", "t1", "experiment", "exp-any", "delete") is False


# --- global wildcard tests ---


async def test_member_global_wildcard_action_allowed():
    rule = _rule("*", "*", ["read", "execute"])
    session = _make_session(_member(), None, None, rule)
    assert await check_permission(session, "u1", "t1", "model", "some-model", "execute") is True


async def test_member_global_wildcard_action_denied():
    rule = _rule("*", "*", ["read"])
    session = _make_session(_member(), None, None, rule)
    assert await check_permission(session, "u1", "t1", "model", "some-model", "delete") is False


# --- specificity precedence: exact beats type wildcard ---


async def test_exact_match_takes_precedence_over_type_wildcard():
    exact_rule = _rule("experiment", "exp1", ["read"])
    type_rule = _rule("experiment", "*", ["read", "delete"])
    session = _make_session(_member(), exact_rule)
    assert await check_permission(session, "u1", "t1", "experiment", "exp1", "delete") is False
    session1 = _make_session(_member(), type_rule)
    assert await check_permission(session1, "u1", "t1", "experiment", "exp1", "delete") is True
