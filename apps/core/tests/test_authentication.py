"""Unit and integration tests for RS256 JWT stateless authentication (ADR-002)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.test import RequestFactory
import jwt
import pytest
from rest_framework.exceptions import AuthenticationFailed

from apps.core.authentication import (
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_ISSUER,
    RS256JWTAuthentication,
    StatelessJWTUser,
    get_jwt_public_key,
)


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[str, str]:
    """Generate ephemeral RSA private and public key PEM pair for test isolation."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


@pytest.fixture
def make_token(rsa_keypair: tuple[str, str], monkeypatch):
    """Helper fixture to mint RS256 JWT tokens signed with test key."""
    private_pem, public_pem = rsa_keypair
    monkeypatch.setattr(settings, "JWT_PUBLIC_KEY", public_pem)

    def _generate(
        sub: str | uuid.UUID | None = None,
        email: str = "student@ufps.edu.co",
        role: str = "STUDENT",
        scope: str | list[str] = "application:create application:read_own",
        expires_in_seconds: int = 900,
        iss: str = DEFAULT_JWT_ISSUER,
        aud: str | list[str] | None = None,
        token_type: str = "access",
        is_active: bool = True,
        key: str = private_pem,
    ) -> str:
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=expires_in_seconds)

        scope_val = " ".join(scope) if isinstance(scope, list) else scope

        payload: dict[str, Any] = {
            "iss": iss,
            "aud": aud or [DEFAULT_JWT_AUDIENCE, "conecta-nexus-gateway"],
            "sub": str(sub or uuid.uuid4()),
            "jti": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "type": token_type,
            "email": email,
            "role": role,
            "is_active": is_active,
            "scope": scope_val,
        }
        return jwt.encode(payload, key, algorithm="RS256")

    return _generate


# ==============================================================================
# 1. StatelessJWTUser Entity Tests
# ==============================================================================


def test_stateless_jwt_user_attributes_and_methods():
    """Verify in-memory StatelessJWTUser properties, methods, and role/scope checks."""
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "email": "estudiante@ufps.edu.co",
        "role": "STUDENT",
        "scope": "application:create application:read_own consent:read",
        "is_active": True,
    }
    user = StatelessJWTUser(payload)

    # Identifiers
    assert user.id == user_id
    assert user.pk == user_id
    assert user.user_id == user_id

    # Core claims
    assert user.email == "estudiante@ufps.edu.co"
    assert user.role == "STUDENT"
    assert user.is_authenticated is True
    assert user.is_anonymous is False

    # Role checks
    assert user.has_role("STUDENT") is True
    assert user.has_role("student") is True
    assert user.has_role("COMPANY") is False
    assert user.has_any_role("COMPANY", "STUDENT") is True
    assert user.has_any_role("COMPANY", "ADMIN") is False

    # Scope checks
    assert user.has_scope("application:create") is True
    assert user.has_scope("challenge:delete") is False
    assert user.has_any_scope("application:create", "admin:all") is True
    assert user.has_any_scope("admin:1", "admin:2") is False
    assert user.has_all_scopes("application:create", "consent:read") is True
    assert user.has_all_scopes("application:create", "missing:scope") is False

    assert "estudiante@ufps.edu.co (STUDENT)" in str(user)
    assert f"<StatelessJWTUser id={user_id} role=STUDENT>" in repr(user)


def test_stateless_jwt_user_handles_list_scopes():
    """Verify StatelessJWTUser correctly parses list-based scopes."""
    user = StatelessJWTUser({"sub": str(uuid.uuid4()), "role": "STUDENT", "scope": ["a", "b"]})
    assert user.scopes == ["a", "b"]
    assert user.has_scope("a") is True


# ==============================================================================
# 2. Public Key Loading Tests
# ==============================================================================


def test_get_jwt_public_key_from_disk(monkeypatch):
    """Verify loading public key from default certs/jwt_public.pem path."""
    monkeypatch.setattr(settings, "JWT_PUBLIC_KEY", "")
    key = get_jwt_public_key()
    assert "-----BEGIN PUBLIC KEY-----" in key
    assert "-----END PUBLIC KEY-----" in key


def test_get_jwt_public_key_missing_raises(monkeypatch):
    """Verify AuthenticationFailed when public key file is missing."""
    monkeypatch.setattr(settings, "JWT_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "JWT_PUBLIC_KEY_PATH", "nonexistent/key.pem")

    with pytest.raises(AuthenticationFailed) as exc_info:
        get_jwt_public_key()
    assert exc_info.value.get_codes() == "public_key_missing"


def test_get_jwt_public_key_empty_raises(tmp_path, monkeypatch):
    """Verify AuthenticationFailed when public key file is empty."""
    empty_file = tmp_path / "empty.pem"
    empty_file.write_text("")
    monkeypatch.setattr(settings, "JWT_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "JWT_PUBLIC_KEY_PATH", str(empty_file))

    with pytest.raises(AuthenticationFailed) as exc_info:
        get_jwt_public_key()
    assert exc_info.value.get_codes() == "public_key_empty"


# ==============================================================================
# 3. RS256JWTAuthentication Header Parsing Tests
# ==============================================================================


def test_authenticate_no_header_returns_none():
    """Requests without Authorization header return None (allowing anonymous routes)."""
    factory = RequestFactory()
    request = factory.get("/api/v1/health/")
    auth = RS256JWTAuthentication()
    assert auth.authenticate(request) is None


def test_authenticate_non_bearer_returns_none():
    """Requests with non-Bearer Authorization return None."""
    factory = RequestFactory()
    request = factory.get("/api/v1/health/", HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz")
    auth = RS256JWTAuthentication()
    assert auth.authenticate(request) is None


def test_authenticate_bearer_without_token_raises():
    """Bearer without token raises AuthenticationFailed."""
    factory = RequestFactory()
    request = factory.get("/api/v1/health/", HTTP_AUTHORIZATION="Bearer")
    auth = RS256JWTAuthentication()
    with pytest.raises(AuthenticationFailed, match="No credentials provided"):
        auth.authenticate(request)


def test_authenticate_bearer_with_extra_spaces_raises():
    """Bearer token with spaces raises AuthenticationFailed."""
    factory = RequestFactory()
    request = factory.get("/api/v1/health/", HTTP_AUTHORIZATION="Bearer token with spaces")
    auth = RS256JWTAuthentication()
    with pytest.raises(AuthenticationFailed, match="should not contain spaces"):
        auth.authenticate(request)


def test_authenticate_header_method():
    """Verify authenticate_header returns 'Bearer' for 401 challenges."""
    auth = RS256JWTAuthentication()
    assert auth.authenticate_header(RequestFactory().get("/")) == "Bearer"


# ==============================================================================
# 4. Token Cryptographic & Claims Validation Tests
# ==============================================================================


def test_authenticate_valid_token_success(make_token):
    """Valid RS256 access token returns AuthenticatedUser and payload dict."""
    user_id = uuid.uuid4()
    token = make_token(sub=user_id, role="STUDENT", email="student@ufps.edu.co")

    factory = RequestFactory()
    request = factory.get("/api/v1/applications/", HTTP_AUTHORIZATION=f"Bearer {token}")
    auth = RS256JWTAuthentication()
    user, payload = auth.authenticate(request)

    assert isinstance(user, StatelessJWTUser)
    assert user.id == user_id
    assert user.role == "STUDENT"
    assert user.email == "student@ufps.edu.co"
    assert payload["sub"] == str(user_id)


def test_authenticate_expired_token_raises(make_token):
    """Expired access token raises AuthenticationFailed with code token_expired."""
    token = make_token(expires_in_seconds=-60)
    factory = RequestFactory()
    request = factory.get("/api/v1/applications/", HTTP_AUTHORIZATION=f"Bearer {token}")
    auth = RS256JWTAuthentication()

    with pytest.raises(AuthenticationFailed) as exc_info:
        auth.authenticate(request)
    assert exc_info.value.get_codes() == "token_expired"


def test_authenticate_tampered_token_raises(make_token):
    """Tampered token signature raises AuthenticationFailed with code invalid_token."""
    token = make_token()
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.AAAA"

    factory = RequestFactory()
    request = factory.get("/api/v1/applications/", HTTP_AUTHORIZATION=f"Bearer {tampered}")
    auth = RS256JWTAuthentication()

    with pytest.raises(AuthenticationFailed) as exc_info:
        auth.authenticate(request)
    assert exc_info.value.get_codes() == "invalid_token"


def test_authenticate_invalid_issuer_raises(make_token):
    """Token with invalid issuer raises AuthenticationFailed with code invalid_issuer."""
    token = make_token(iss="https://evil-auth.com")
    factory = RequestFactory()
    request = factory.get("/api/v1/applications/", HTTP_AUTHORIZATION=f"Bearer {token}")
    auth = RS256JWTAuthentication()

    with pytest.raises(AuthenticationFailed) as exc_info:
        auth.authenticate(request)
    assert exc_info.value.get_codes() == "invalid_issuer"


def test_authenticate_invalid_audience_raises(make_token):
    """Token with alien audience raises AuthenticationFailed with code invalid_audience."""
    token = make_token(aud="unrelated-microservice")
    factory = RequestFactory()
    request = factory.get("/api/v1/applications/", HTTP_AUTHORIZATION=f"Bearer {token}")
    auth = RS256JWTAuthentication()

    with pytest.raises(AuthenticationFailed) as exc_info:
        auth.authenticate(request)
    assert exc_info.value.get_codes() == "invalid_audience"


def test_authenticate_refresh_token_type_rejected(make_token):
    """Refresh tokens cannot be used to authenticate API requests."""
    token = make_token(token_type="refresh")
    factory = RequestFactory()
    request = factory.get("/api/v1/applications/", HTTP_AUTHORIZATION=f"Bearer {token}")
    auth = RS256JWTAuthentication()

    with pytest.raises(AuthenticationFailed) as exc_info:
        auth.authenticate(request)
    assert exc_info.value.get_codes() == "invalid_token_type"


def test_authenticate_deactivated_user_raises(make_token):
    """Token with is_active=False raises AuthenticationFailed with code user_inactive."""
    token = make_token(is_active=False)
    factory = RequestFactory()
    request = factory.get("/api/v1/applications/", HTTP_AUTHORIZATION=f"Bearer {token}")
    auth = RS256JWTAuthentication()

    with pytest.raises(AuthenticationFailed) as exc_info:
        auth.authenticate(request)
    assert exc_info.value.get_codes() == "user_inactive"
