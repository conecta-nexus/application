"""Integration and contract tests for POST /api/v1/applications/ endpoint."""

from __future__ import annotations

import uuid

import httpx
import pytest
from rest_framework import status
from rest_framework.test import APIClient
import respx

from apps.applications.models import Application
from apps.core.authentication import StatelessJWTUser

CHALLENGE_BASE_URL = "http://challenge:8000"
PROFILE_BASE_URL = "http://profile:8000"
APPLICATIONS_URL = "/api/v1/applications/"

VALID_MOTIVATION_LETTER = (
    "I am very excited to apply to this challenge. I have strong experience in backend "
    "systems, distributed databases, and Python architectures, and I look forward to "
    "contributing high quality solutions to your team."
)


@pytest.fixture
def student_user() -> StatelessJWTUser:
    """Fixture providing an authenticated student user."""
    return StatelessJWTUser({
        "sub": str(uuid.uuid4()),
        "email": "student@ufps.edu.co",
        "role": "STUDENT",
        "scope": ["application:submit"],
        "is_active": True,
    })


@pytest.fixture
def company_user() -> StatelessJWTUser:
    """Fixture providing an authenticated corporate user."""
    return StatelessJWTUser({
        "sub": str(uuid.uuid4()),
        "email": "company@corp.com",
        "role": "COMPANY",
        "scope": [],
        "is_active": True,
    })


@pytest.fixture
def admin_user() -> StatelessJWTUser:
    """Fixture providing an administrative user."""
    return StatelessJWTUser({
        "sub": str(uuid.uuid4()),
        "email": "admin@ufps.edu.co",
        "role": "ADMIN",
        "scope": ["admin:all"],
        "is_active": True,
    })


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def challenge_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.mark.django_db
@respx.mock
def test_create_application_success(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
) -> None:
    """Successful application submission by eligible student to an open challenge returns 201."""
    api_client.force_authenticate(user=student_user)

    # Mock challenge service -> OPEN challenge
    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        200,
        json={"id": str(challenge_id), "status": "OPEN", "title": "Machine Learning Model"},
    )

    # Mock profile service -> eligible student
    respx.get(f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_user.id}/eligibility").respond(
        200,
        json={
            "user_id": str(student_user.id),
            "is_eligible": True,
            "current_semester": 7,
            "has_consent": True,
            "contact_info": {"email": student_user.email, "phone": "+573001234567"},
        },
    )

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["student_id"] == str(student_user.id)
    assert data["challenge_id"] == str(challenge_id)
    assert data["status"] == "PENDING"
    assert data["motivation_letter"] == VALID_MOTIVATION_LETTER

    # Verify DB persistence
    assert Application.objects.filter(student_id=student_user.id, challenge_id=challenge_id).exists()
    app = Application.objects.get(student_id=student_user.id, challenge_id=challenge_id)
    assert app.status == Application.Status.PENDING


@pytest.mark.django_db
def test_create_application_unauthenticated(api_client: APIClient, challenge_id: uuid.UUID) -> None:
    """Anonymous request must be rejected with 401 Unauthorized."""
    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }
    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
@pytest.mark.parametrize("non_student_role", ["COMPANY", "ADMIN"])
def test_create_application_forbidden_for_non_students(
    api_client: APIClient,
    challenge_id: uuid.UUID,
    non_student_role: str,
) -> None:
    """Only STUDENT role can apply; COMPANY and ADMIN receive 403 Forbidden."""
    user = StatelessJWTUser({
        "sub": str(uuid.uuid4()),
        "email": f"user_{non_student_role.lower()}@test.com",
        "role": non_student_role,
        "is_active": True,
    })
    api_client.force_authenticate(user=user)

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }
    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_payload,error_field",
    [
        ({"motivation_letter": VALID_MOTIVATION_LETTER}, "challenge_id"),
        ({"challenge_id": "not-a-uuid", "motivation_letter": VALID_MOTIVATION_LETTER}, "challenge_id"),
        ({"challenge_id": str(uuid.uuid4()), "motivation_letter": "Too short"}, "motivation_letter"),
        ({"challenge_id": str(uuid.uuid4()), "motivation_letter": "a" * 2001}, "motivation_letter"),
    ],
)
def test_create_application_validation_errors(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    invalid_payload: dict,
    error_field: str,
) -> None:
    """Validation failure in payload returns 400 Bad Request."""
    api_client.force_authenticate(user=student_user)
    response = api_client.post(APPLICATIONS_URL, invalid_payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert error_field in response.json()


@pytest.mark.django_db
def test_create_application_duplicate_rejected(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
) -> None:
    """Duplicate application submission to the same challenge returns 409 Conflict (RB-03)."""
    api_client.force_authenticate(user=student_user)

    # Pre-create an application in db
    Application.objects.create(
        student_id=student_user.id,
        challenge_id=challenge_id,
        motivation_letter=VALID_MOTIVATION_LETTER,
        status=Application.Status.PENDING,
    )

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "already" in response.json().get("detail", "").lower()


@pytest.mark.django_db
@respx.mock
def test_create_application_challenge_missing(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
) -> None:
    """Challenge not found in challenge microservice returns 404 Not Found."""
    api_client.force_authenticate(user=student_user)

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        404,
        json={"detail": "Not found"},
    )

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize("non_open_status", ["DRAFT", "IN_PROGRESS", "CLOSED", "CANCELLED"])
@respx.mock
def test_create_application_challenge_not_open(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
    non_open_status: str,
) -> None:
    """Challenge not in OPEN status returns 422 Unprocessable Content."""
    api_client.force_authenticate(user=student_user)

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        200,
        json={"id": str(challenge_id), "status": non_open_status, "title": "Sample"},
    )

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "not open" in response.json().get("detail", "").lower()


@pytest.mark.django_db
@respx.mock
def test_create_application_student_ineligible_semester(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
) -> None:
    """Student semester < 6 or > 10 returns 400 Bad Request."""
    api_client.force_authenticate(user=student_user)

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        200,
        json={"id": str(challenge_id), "status": "OPEN"},
    )

    respx.get(f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_user.id}/eligibility").respond(
        200,
        json={
            "user_id": str(student_user.id),
            "is_eligible": False,
            "current_semester": 4,
            "has_consent": True,
        },
    )

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "eligible" in response.json().get("detail", "").lower()


@pytest.mark.django_db
@respx.mock
def test_create_application_missing_consent(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
) -> None:
    """Student missing Habeas Data consent returns 400 Bad Request."""
    api_client.force_authenticate(user=student_user)

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        200,
        json={"id": str(challenge_id), "status": "OPEN"},
    )

    respx.get(f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_user.id}/eligibility").respond(
        200,
        json={
            "user_id": str(student_user.id),
            "is_eligible": False,
            "current_semester": 7,
            "has_consent": False,
        },
    )

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "habeas data" in response.json().get("detail", "").lower()


@pytest.mark.django_db
@respx.mock
def test_create_application_profile_not_found(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
) -> None:
    """Profile not found in profile service returns 400 Bad Request."""
    api_client.force_authenticate(user=student_user)

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        200,
        json={"id": str(challenge_id), "status": "OPEN"},
    )

    respx.get(f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_user.id}/eligibility").respond(
        404,
        json={"detail": "Student profile not found for the specified user."},
    )

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@respx.mock
def test_create_application_challenge_service_down(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
) -> None:
    """When challenge service is unreachable or returns 5xx, return 502 Bad Gateway."""
    api_client.force_authenticate(user=student_user)

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(503)

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.django_db
@respx.mock
def test_create_application_profile_service_down(
    api_client: APIClient,
    student_user: StatelessJWTUser,
    challenge_id: uuid.UUID,
) -> None:
    """When profile service is unreachable or returns 5xx, return 502 Bad Gateway."""
    api_client.force_authenticate(user=student_user)

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        200,
        json={"id": str(challenge_id), "status": "OPEN"},
    )

    respx.get(f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_user.id}/eligibility").respond(503)

    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": VALID_MOTIVATION_LETTER,
    }

    response = api_client.post(APPLICATIONS_URL, payload, format="json")
    assert response.status_code == status.HTTP_502_BAD_GATEWAY
