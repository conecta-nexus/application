"""Core infrastructure and authentication module for application microservice."""

from apps.core.authentication import RS256JWTAuthentication, StatelessJWTUser
from apps.core.permissions import (
    HasScope,
    IsAdminUser,
    IsCompanyUser,
    IsStudentUser,
    RequireScopes,
)

__all__ = [
    "HasScope",
    "IsAdminUser",
    "IsCompanyUser",
    "IsStudentUser",
    "RS256JWTAuthentication",
    "RequireScopes",
    "StatelessJWTUser",
]
