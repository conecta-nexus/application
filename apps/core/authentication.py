"""Stateless RS256 JWT Authentication for Django REST Framework (ADR-002).

Implements cryptographically validated token parsing using the shared RSA public
key without querying the auth database.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings
import jwt
from rest_framework import authentication, exceptions

logger = logging.getLogger(__name__)

DEFAULT_JWT_ISSUER = "https://auth.conectanexus.ufps.edu.co"
DEFAULT_JWT_AUDIENCE = "conecta-nexus-services"


class StatelessJWTUser:
    """In-memory user object representing an authenticated entity via RS256 JWT."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        raw_sub = payload.get("sub")
        try:
            self.id: uuid.UUID | None = uuid.UUID(str(raw_sub)) if raw_sub else None
        except (ValueError, TypeError):
            self.id = raw_sub  # type: ignore[assignment]

        self.pk = self.id
        self.user_id = self.id
        self.email: str = str(payload.get("email", "")).strip()
        self.role: str = str(payload.get("role", "")).strip().upper()
        self.is_active: bool = bool(payload.get("is_active", True))

        scope_claim = payload.get("scope", "")
        if isinstance(scope_claim, str):
            self.scopes: list[str] = [s for s in scope_claim.split() if s]
        elif isinstance(scope_claim, (list, tuple)):
            self.scopes = [str(s) for s in scope_claim if s]
        else:
            self.scopes = []

    @property
    def is_authenticated(self) -> bool:
        """Always True for successfully authenticated JWT users."""
        return True

    @property
    def is_anonymous(self) -> bool:
        """Always False for authenticated JWT users."""
        return False

    def has_role(self, role: str) -> bool:
        """Check if user matches the given role (case-insensitive)."""
        return self.role == role.strip().upper()

    def has_any_role(self, *roles: str) -> bool:
        """Check if user matches any of the given roles."""
        normalized = {r.strip().upper() for r in roles}
        return self.role in normalized

    def has_scope(self, scope: str) -> bool:
        """Check if the user claims contain a given scope."""
        return scope.strip() in self.scopes

    def has_any_scope(self, *scopes: str) -> bool:
        """Check if user possesses at least one of the given scopes."""
        target_scopes = {s.strip() for s in scopes}
        return any(scope in target_scopes for scope in self.scopes)

    def has_all_scopes(self, *scopes: str) -> bool:
        """Check if user possesses all of the given scopes."""
        target_scopes = {s.strip() for s in scopes}
        return target_scopes.issubset(set(self.scopes))

    def __str__(self) -> str:
        return f"{self.email} ({self.role})"

    def __repr__(self) -> str:
        return f"<StatelessJWTUser id={self.id} role={self.role}>"


def get_jwt_public_key() -> str:
    """Retrieve the RSA public key PEM from settings, environment, or file on disk.

    Returns:
        Clean RSA public key PEM string.

    Raises:
        AuthenticationFailed: If key is not found or empty.
    """
    key_content = getattr(settings, "JWT_PUBLIC_KEY", None) or os.getenv("JWT_PUBLIC_KEY")
    if key_content and key_content.strip():
        return key_content.strip()

    key_path_str = getattr(settings, "JWT_PUBLIC_KEY_PATH", None) or os.getenv(
        "JWT_PUBLIC_KEY_PATH", "certs/jwt_public.pem"
    )
    key_path = Path(key_path_str)
    if not key_path.is_absolute():
        candidates = [
            settings.BASE_DIR / key_path,
            Path.cwd() / key_path,
        ]
        resolved = next((p for p in candidates if p.exists() and p.is_file()), None)
    else:
        resolved = key_path if key_path.exists() and key_path.is_file() else None

    if not resolved:
        raise exceptions.AuthenticationFailed(
            detail="RS256 public key is not configured or could not be found.",
            code="public_key_missing",
        )

    try:
        content = resolved.read_text(encoding="utf-8").strip()
        if not content:
            raise exceptions.AuthenticationFailed(
                detail="RS256 public key file is empty.",
                code="public_key_empty",
            )
        return content
    except OSError as exc:
        raise exceptions.AuthenticationFailed(
            detail=f"Failed to read RS256 public key: {exc}",
            code="public_key_read_error",
        ) from exc


class RS256JWTAuthentication(authentication.BaseAuthentication):
    """Stateless DRF authentication backend verifying RS256 JWT tokens with RSA public key."""

    keyword = "Bearer"

    def authenticate(self, request) -> tuple[StatelessJWTUser, dict[str, Any]] | None:
        auth_header = authentication.get_authorization_header(request).decode("utf-8")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) == 0:
            return None

        if parts[0].lower() != self.keyword.lower():
            return None

        if len(parts) == 1:
            raise exceptions.AuthenticationFailed(
                detail="Invalid Authorization header. No credentials provided.",
                code="invalid_header",
            )
        elif len(parts) > 2:
            raise exceptions.AuthenticationFailed(
                detail="Invalid Authorization header. Token string should not contain spaces.",
                code="invalid_header",
            )

        token = parts[1]
        payload = self.decode_and_validate_token(token)
        user = StatelessJWTUser(payload)
        return user, payload

    def decode_and_validate_token(self, token: str) -> dict[str, Any]:
        public_key = get_jwt_public_key()
        issuer = getattr(settings, "JWT_ISSUER", None) or os.getenv(
            "JWT_ISSUER", DEFAULT_JWT_ISSUER
        )
        audiences = getattr(settings, "JWT_AUDIENCES", None) or [
            getattr(settings, "JWT_AUDIENCE", DEFAULT_JWT_AUDIENCE),
            "conecta-nexus-gateway",
            "conecta-nexus-services",
        ]

        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=issuer,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": False,  # Multi-audience validation below
                    "require": ["exp", "sub", "role"],
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise exceptions.AuthenticationFailed(
                detail="Token has expired.",
                code="token_expired",
            ) from exc
        except jwt.InvalidIssuerError as exc:
            raise exceptions.AuthenticationFailed(
                detail="Token issuer is invalid.",
                code="invalid_issuer",
            ) from exc
        except jwt.PyJWTError as exc:
            raise exceptions.AuthenticationFailed(
                detail=f"Token validation failed: {str(exc)}",
                code="invalid_token",
            ) from exc

        # Multi-audience verification
        token_aud = payload.get("aud")
        expected_audiences = set(audiences)
        aud_valid = False
        if isinstance(token_aud, str):
            aud_valid = token_aud in expected_audiences
        elif isinstance(token_aud, (list, tuple)):
            aud_valid = any(aud in expected_audiences for aud in token_aud)

        if not aud_valid:
            raise exceptions.AuthenticationFailed(
                detail="Token audience is invalid.",
                code="invalid_audience",
            )

        # Validate Token Type (must be access token)
        token_type = payload.get("type", "access")
        if token_type != "access":
            raise exceptions.AuthenticationFailed(
                detail=f"Invalid token type: expected 'access', got '{token_type}'.",
                code="invalid_token_type",
            )

        # Validate User Active Status
        if payload.get("is_active") is False:
            raise exceptions.AuthenticationFailed(
                detail="User account is deactivated.",
                code="user_inactive",
            )

        return payload

    def authenticate_header(self, request) -> str:
        return self.keyword
