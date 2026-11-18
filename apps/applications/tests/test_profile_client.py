"""Integration tests for the synchronous ProfileServiceClient inter-service client."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from apps.applications.clients.profile_client import ProfileServiceClient
from apps.applications.exceptions import (
    ConsentMissingError,
    ProfileServiceUnavailableError,
    StudentNotEligibleError,
    StudentProfileNotFoundError,
)

BASE_PROFILE_URL = "http://profile:8000"


@pytest.fixture
def student_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def client() -> ProfileServiceClient:
    return ProfileServiceClient(
        base_url=BASE_PROFILE_URL,
        token="test-internal-token",
        timeout=1.0,
        max_retries=2,
        backoff_factor=0.01,
    )


@respx.mock
def test_check_eligibility_success(client: ProfileServiceClient, student_id: uuid.UUID) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    expected_response = {
        "user_id": str(student_id),
        "is_eligible": True,
        "current_semester": 7,
        "has_consent": True,
        "contact_info": {
            "email": "student@ufps.edu.co",
            "phone": "+573001234567",
        },
    }

    route = respx.get(endpoint_url).respond(200, json=expected_response)

    result = client.check_eligibility(student_id)

    assert route.called
    assert route.call_count == 1
    assert route.calls.last.request.headers["authorization"] == "Bearer test-internal-token"
    assert result["is_eligible"] is True
    assert result["current_semester"] == 7
    assert result["has_consent"] is True
    assert result["contact_info"]["email"] == "student@ufps.edu.co"


@pytest.mark.parametrize("semester", [6, 10])
@respx.mock
def test_check_eligibility_semester_boundaries(
    client: ProfileServiceClient,
    student_id: uuid.UUID,
    semester: int,
) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    respx.get(endpoint_url).respond(
        200,
        json={
            "user_id": str(student_id),
            "is_eligible": True,
            "current_semester": semester,
            "has_consent": True,
            "contact_info": {"email": "student@ufps.edu.co", "phone": "+573001234567"},
        },
    )

    result = client.check_eligibility(student_id)
    assert result["current_semester"] == semester
    assert result["is_eligible"] is True


@pytest.mark.parametrize("semester", [1, 5, 11])
@respx.mock
def test_check_eligibility_ineligible_semester(
    client: ProfileServiceClient,
    student_id: uuid.UUID,
    semester: int,
) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    respx.get(endpoint_url).respond(
        200,
        json={
            "user_id": str(student_id),
            "is_eligible": False,
            "current_semester": semester,
            "has_consent": True,
            "contact_info": {"email": "student@ufps.edu.co", "phone": "+573001234567"},
        },
    )

    with pytest.raises(StudentNotEligibleError) as exc_info:
        client.check_eligibility(student_id)

    assert "not academically eligible" in str(exc_info.value)


@respx.mock
def test_check_eligibility_missing_consent(
    client: ProfileServiceClient,
    student_id: uuid.UUID,
) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    respx.get(endpoint_url).respond(
        200,
        json={
            "user_id": str(student_id),
            "is_eligible": False,
            "current_semester": 7,
            "has_consent": False,
            "contact_info": {"email": "student@ufps.edu.co", "phone": "+573001234567"},
        },
    )

    with pytest.raises(ConsentMissingError) as exc_info:
        client.check_eligibility(student_id)

    assert "mandatory Habeas Data consent" in str(exc_info.value)


@respx.mock
def test_check_eligibility_student_not_found(
    client: ProfileServiceClient,
    student_id: uuid.UUID,
) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    respx.get(endpoint_url).respond(
        404,
        json={"detail": "Student profile not found for the specified user."},
    )

    with pytest.raises(StudentProfileNotFoundError):
        client.check_eligibility(student_id)


@pytest.mark.parametrize("unauthorized_status", [401, 403])
@respx.mock
def test_check_eligibility_unauthorized(
    client: ProfileServiceClient,
    student_id: uuid.UUID,
    unauthorized_status: int,
) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    respx.get(endpoint_url).respond(
        unauthorized_status,
        json={"detail": "Internal service token or administrative scope required."},
    )

    with pytest.raises(ProfileServiceUnavailableError) as exc_info:
        client.check_eligibility(student_id)

    assert "unauthorized" in str(exc_info.value).lower()


@respx.mock
def test_check_eligibility_retry_on_500_recovers(
    client: ProfileServiceClient,
    student_id: uuid.UUID,
) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    route = respx.get(endpoint_url)
    route.side_effect = [
        httpx.Response(500, json={"error": "Database temporary glitch"}),
        httpx.Response(
            200,
            json={
                "user_id": str(student_id),
                "is_eligible": True,
                "current_semester": 8,
                "has_consent": True,
                "contact_info": {"email": "student@ufps.edu.co", "phone": "+573001234567"},
            },
        ),
    ]

    result = client.check_eligibility(student_id)

    assert route.call_count == 2
    assert result["is_eligible"] is True
    assert result["current_semester"] == 8


@respx.mock
def test_check_eligibility_retry_exhausted_raises_unavailable(
    client: ProfileServiceClient,
    student_id: uuid.UUID,
) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    route = respx.get(endpoint_url).respond(503, json={"error": "Service overloaded"})

    with pytest.raises(ProfileServiceUnavailableError) as exc_info:
        client.check_eligibility(student_id)

    # 1 initial call + 2 retries = 3 calls
    assert route.call_count == 3
    assert "503" in str(exc_info.value)


@respx.mock
def test_check_eligibility_timeout_exhausted_raises_unavailable(
    client: ProfileServiceClient,
    student_id: uuid.UUID,
) -> None:
    endpoint_url = f"{BASE_PROFILE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    route = respx.get(endpoint_url)
    route.side_effect = httpx.ConnectTimeout("Connection timed out")

    with pytest.raises(ProfileServiceUnavailableError) as exc_info:
        client.check_eligibility(student_id)

    assert route.call_count == 3
    assert "communication error" in str(exc_info.value).lower()


def test_profile_client_context_manager() -> None:
    with ProfileServiceClient(base_url="http://localhost:8000") as c:
        assert c.base_url == "http://localhost:8000"
        assert c._client is not None
