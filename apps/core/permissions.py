"""Role-based authorization and scope permissions for Django REST Framework."""

from __future__ import annotations

from typing import Type

from rest_framework import permissions


class IsStudentUser(permissions.BasePermission):
    """Allows access only to authenticated users with the STUDENT role."""

    message = "Operation requires STUDENT role."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", "").upper() == "STUDENT"
        )


class IsCompanyUser(permissions.BasePermission):
    """Allows access only to authenticated users with the COMPANY role."""

    message = "Operation requires COMPANY role."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", "").upper() == "COMPANY"
        )


class IsAdminUser(permissions.BasePermission):
    """Allows access only to authenticated users with the ADMIN role."""

    message = "Operation requires ADMIN role."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", "").upper() == "ADMIN"
        )


def HasScope(required_scope: str) -> Type[permissions.BasePermission]:
    """Permission factory requiring the user token to contain a specific OAuth2 scope."""

    class _ScopePermission(permissions.BasePermission):
        message = f"Missing required OAuth2 scope: '{required_scope}'."

        def has_permission(self, request, view) -> bool:
            return bool(
                request.user
                and request.user.is_authenticated
                and hasattr(request.user, "has_scope")
                and request.user.has_scope(required_scope)
            )

    return _ScopePermission


def RequireScopes(*required_scopes: str) -> Type[permissions.BasePermission]:
    """Permission factory requiring the user token to contain all specified OAuth2 scopes."""

    class _MultiScopePermission(permissions.BasePermission):
        message = f"Missing required OAuth2 scopes: {list(required_scopes)}."

        def has_permission(self, request, view) -> bool:
            return bool(
                request.user
                and request.user.is_authenticated
                and hasattr(request.user, "has_all_scopes")
                and request.user.has_all_scopes(*required_scopes)
            )

    return _MultiScopePermission


__all__ = [
    "HasScope",
    "IsAdminUser",
    "IsCompanyUser",
    "IsStudentUser",
    "RequireScopes",
]
