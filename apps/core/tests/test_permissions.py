"""Unit tests for role-based and OAuth2 scope DRF permissions."""

import uuid
import pytest
from django.test import RequestFactory
from rest_framework.views import APIView

from apps.core.authentication import StatelessJWTUser
from apps.core.permissions import (
    HasScope,
    IsAdminUser,
    IsCompanyUser,
    IsStudentUser,
    RequireScopes,
)


def mock_request(role: str | None = "STUDENT", scopes: list[str] | None = None, is_authenticated: bool = True):
    """Helper to mock a DRF request with an in-memory user."""
    factory = RequestFactory()
    request = factory.get("/test")
    if is_authenticated and role:
        request.user = StatelessJWTUser({
            "sub": str(uuid.uuid4()),
            "email": "test@ufps.edu.co",
            "role": role,
            "scope": scopes or [],
            "is_active": True,
        })
    else:
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
    return request


def test_is_student_user_permission():
    """Verify IsStudentUser allows STUDENT and blocks others."""
    perm = IsStudentUser()
    view = APIView()

    assert perm.has_permission(mock_request(role="STUDENT"), view) is True
    assert perm.has_permission(mock_request(role="COMPANY"), view) is False
    assert perm.has_permission(mock_request(role="ADMIN"), view) is False
    assert perm.has_permission(mock_request(is_authenticated=False), view) is False


def test_is_company_user_permission():
    """Verify IsCompanyUser allows COMPANY and blocks others."""
    perm = IsCompanyUser()
    view = APIView()

    assert perm.has_permission(mock_request(role="COMPANY"), view) is True
    assert perm.has_permission(mock_request(role="STUDENT"), view) is False
    assert perm.has_permission(mock_request(role="ADMIN"), view) is False
    assert perm.has_permission(mock_request(is_authenticated=False), view) is False


def test_is_admin_user_permission():
    """Verify IsAdminUser allows ADMIN and blocks others."""
    perm = IsAdminUser()
    view = APIView()

    assert perm.has_permission(mock_request(role="ADMIN"), view) is True
    assert perm.has_permission(mock_request(role="STUDENT"), view) is False
    assert perm.has_permission(mock_request(role="COMPANY"), view) is False
    assert perm.has_permission(mock_request(is_authenticated=False), view) is False


def test_has_scope_permission():
    """Verify HasScope permission factory."""
    perm_class = HasScope("application:create")
    perm = perm_class()
    view = APIView()

    # User with scope
    req_with_scope = mock_request(role="STUDENT", scopes=["application:create", "application:read"])
    assert perm.has_permission(req_with_scope, view) is True

    # User without scope
    req_without_scope = mock_request(role="STUDENT", scopes=["challenge:read"])
    assert perm.has_permission(req_without_scope, view) is False

    # Anonymous user
    assert perm.has_permission(mock_request(is_authenticated=False), view) is False


def test_require_scopes_multi_permission():
    """Verify RequireScopes requires all listed scopes."""
    perm_class = RequireScopes("application:create", "application:read_own")
    perm = perm_class()
    view = APIView()

    # All scopes present
    req_all = mock_request(scopes=["application:create", "application:read_own"])
    assert perm.has_permission(req_all, view) is True

    # Partial scopes present
    req_partial = mock_request(scopes=["application:create"])
    assert perm.has_permission(req_partial, view) is False
