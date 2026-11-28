"""Tests for atomic application acceptance, RBAC, rollback, and RB-05 contact reveal."""

from __future__ import annotations

import uuid

import pytest
import respx
from rest_framework import status
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.core.authentication import StatelessJWTUser

CHALLENGE_BASE_URL = "http://challenge:8000"
PROFILE_BASE_URL = "http://profile:8000"


def accept_url(application_id: uuid.UUID) -> str:
    return f"/api/v1/applications/{application_id}/accept/"


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def company_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def other_company_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def student_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def other_student_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def challenge_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def company_user(company_id: uuid.UUID) -> StatelessJWTUser:
    return StatelessJWTUser(
        {
            "sub": str(company_id),
            "email": "company@nexus.co",
            "role": "COMPANY",
            "is_active": True,
        }
    )


@pytest.fixture
def student_user(student_id: uuid.UUID) -> StatelessJWTUser:
    return StatelessJWTUser(
        {
            "sub": str(student_id),
            "email": "student@ufps.edu.co",
            "role": "STUDENT",
            "is_active": True,
        }
    )


@pytest.mark.django_db
def test_accept_application_unauthenticated_returns_401(
    api_client: APIClient,
    student_id: uuid.UUID,
    challenge_id: uuid.UUID,
) -> None:
    app = Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="M" * 60,
        status=Application.Status.PENDING,
    )
    response = api_client.post(accept_url(app.id), format="json")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["STUDENT", "ADMIN"])
def test_accept_application_forbidden_for_non_company_roles(
    api_client: APIClient,
    student_id: uuid.UUID,
    challenge_id: uuid.UUID,
    role: str,
) -> None:
    app = Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="M" * 60,
        status=Application.Status.PENDING,
    )
    user = StatelessJWTUser(
        {
            "sub": str(uuid.uuid4()),
            "email": f"{role.lower()}@nexus.co",
            "role": role,
            "is_active": True,
        }
    )
    api_client.force_authenticate(user=user)
    response = api_client.post(accept_url(app.id), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_accept_application_not_found_returns_404(
    api_client: APIClient,
    company_user: StatelessJWTUser,
) -> None:
    api_client.force_authenticate(user=company_user)
    response = api_client.post(accept_url(uuid.uuid4()), format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
@respx.mock
def test_accept_application_forbidden_for_non_owner_company(
    api_client: APIClient,
    company_user: StatelessJWTUser,
    other_company_id: uuid.UUID,
    student_id: uuid.UUID,
    challenge_id: uuid.UUID,
) -> None:
    app = Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="M" * 60,
        status=Application.Status.PENDING,
    )
    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={
            "id": str(challenge_id),
            "company_id": str(other_company_id),
            "title": "Data Pipeline",
            "status": "OPEN",
        },
    )

    api_client.force_authenticate(user=company_user)
    response = api_client.post(accept_url(app.id), format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    app.refresh_from_db()
    assert app.status == Application.Status.PENDING


@pytest.mark.django_db
@respx.mock
def test_accept_application_challenge_not_open_returns_409(
    api_client: APIClient,
    company_user: StatelessJWTUser,
    student_id: uuid.UUID,
    challenge_id: uuid.UUID,
) -> None:
    app = Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="M" * 60,
        status=Application.Status.PENDING,
    )
    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={
            "id": str(challenge_id),
            "company_id": str(company_user.id),
            "title": "Data Pipeline",
            "status": "IN_PROGRESS",
        },
    )

    api_client.force_authenticate(user=company_user)
    response = api_client.post(accept_url(app.id), format="json")

    assert response.status_code == status.HTTP_409_CONFLICT
    app.refresh_from_db()
    assert app.status == Application.Status.PENDING


@pytest.mark.django_db
@respx.mock
@pytest.mark.parametrize("initial_status", [Application.Status.ACCEPTED, Application.Status.REJECTED])
def test_accept_application_non_pending_application_returns_409(
    api_client: APIClient,
    company_user: StatelessJWTUser,
    student_id: uuid.UUID,
    challenge_id: uuid.UUID,
    initial_status: str,
) -> None:
    app = Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="M" * 60,
        status=initial_status,
    )
    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={
            "id": str(challenge_id),
            "company_id": str(company_user.id),
            "title": "Data Pipeline",
            "status": "OPEN",
        },
    )

    api_client.force_authenticate(user=company_user)
    response = api_client.post(accept_url(app.id), format="json")

    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
@respx.mock
def test_accept_application_conflict_if_sibling_already_accepted(
    api_client: APIClient,
    company_user: StatelessJWTUser,
    student_id: uuid.UUID,
    other_student_id: uuid.UUID,
    challenge_id: uuid.UUID,
) -> None:
    Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="A" * 60,
        status=Application.Status.ACCEPTED,
    )
    pending_app = Application.objects.create(
        student_id=other_student_id,
        challenge_id=challenge_id,
        motivation_letter="B" * 60,
        status=Application.Status.PENDING,
    )
    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={
            "id": str(challenge_id),
            "company_id": str(company_user.id),
            "title": "Data Pipeline",
            "status": "OPEN",
        },
    )

    api_client.force_authenticate(user=company_user)
    response = api_client.post(accept_url(pending_app.id), format="json")

    assert response.status_code == status.HTTP_409_CONFLICT
    pending_app.refresh_from_db()
    assert pending_app.status == Application.Status.PENDING


@pytest.mark.django_db
@respx.mock
def test_accept_application_success_locks_challenge_rejects_siblings_and_reveals_contacts(
    api_client: APIClient,
    company_user: StatelessJWTUser,
    student_id: uuid.UUID,
    other_student_id: uuid.UUID,
    challenge_id: uuid.UUID,
) -> None:
    target = Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="Chosen student motivation letter " * 3,
        status=Application.Status.PENDING,
    )
    competing = Application.objects.create(
        student_id=other_student_id,
        challenge_id=challenge_id,
        motivation_letter="Competing student motivation letter " * 3,
        status=Application.Status.PENDING,
    )
    unrelated_challenge_id = uuid.uuid4()
    unrelated_app = Application.objects.create(
        student_id=other_student_id,
        challenge_id=unrelated_challenge_id,
        motivation_letter="Other challenge application letter " * 3,
        status=Application.Status.PENDING,
    )

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={
            "id": str(challenge_id),
            "company_id": str(company_user.id),
            "title": "API Refactoring",
            "status": "OPEN",
        },
    )
    lock_route = respx.post(
        f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}/lock"
    ).respond(
        200,
        json={
            "id": str(challenge_id),
            "status": "IN_PROGRESS",
            "locked": True,
        },
    )
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    ).respond(
        200,
        json={
            "user_id": str(student_id),
            "is_eligible": True,
            "current_semester": 8,
            "has_consent": True,
            "contact_info": {
                "email": "student@ufps.edu.co",
                "phone": "+573001112233",
            },
        },
    )
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/companies/{company_user.id}/contact"
    ).respond(
        200,
        json={
            "user_id": str(company_user.id),
            "business_name": "Acme Tech SAS",
            "contact_info": {
                "email": "talent@acmetech.co",
                "phone": "+573109998877",
            },
        },
    )

    api_client.force_authenticate(user=company_user)
    response = api_client.post(accept_url(target.id), format="json")

    assert response.status_code == status.HTTP_200_OK
    assert lock_route.called
    body = response.json()
    assert body["id"] == str(target.id)
    assert body["status"] == Application.Status.ACCEPTED
    assert body["challenge_status"] == "IN_PROGRESS"
    assert body["contact_reveal"] == {
        "student": {
            "email": "student@ufps.edu.co",
            "phone": "+573001112233",
        },
        "company": {
            "business_name": "Acme Tech SAS",
            "email": "talent@acmetech.co",
            "phone": "+573109998877",
        },
    }

    target.refresh_from_db()
    competing.refresh_from_db()
    unrelated_app.refresh_from_db()
    assert target.status == Application.Status.ACCEPTED
    assert competing.status == Application.Status.REJECTED
    assert unrelated_app.status == Application.Status.PENDING


@pytest.mark.django_db
@respx.mock
@pytest.mark.parametrize(
    "lock_status_code,expected_http_status",
    [
        (409, status.HTTP_409_CONFLICT),
        (404, status.HTTP_404_NOT_FOUND),
        (503, status.HTTP_502_BAD_GATEWAY),
    ],
)
def test_accept_application_rolls_back_db_when_challenge_lock_fails(
    api_client: APIClient,
    company_user: StatelessJWTUser,
    student_id: uuid.UUID,
    other_student_id: uuid.UUID,
    challenge_id: uuid.UUID,
    lock_status_code: int,
    expected_http_status: int,
) -> None:
    target = Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="Chosen student motivation letter " * 3,
        status=Application.Status.PENDING,
    )
    competing = Application.objects.create(
        student_id=other_student_id,
        challenge_id=challenge_id,
        motivation_letter="Competing student motivation letter " * 3,
        status=Application.Status.PENDING,
    )

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={
            "id": str(challenge_id),
            "company_id": str(company_user.id),
            "title": "API Refactoring",
            "status": "OPEN",
        },
    )
    respx.post(
        f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}/lock"
    ).respond(lock_status_code, json={"detail": "Lock rejected"})

    api_client.force_authenticate(user=company_user)
    response = api_client.post(accept_url(target.id), format="json")

    assert response.status_code == expected_http_status
    target.refresh_from_db()
    competing.refresh_from_db()
    assert target.status == Application.Status.PENDING
    assert competing.status == Application.Status.PENDING


@pytest.mark.django_db
@respx.mock
def test_accept_application_succeeds_even_if_contact_enrichment_degrades(
    api_client: APIClient,
    company_user: StatelessJWTUser,
    student_id: uuid.UUID,
    challenge_id: uuid.UUID,
) -> None:
    target = Application.objects.create(
        student_id=student_id,
        challenge_id=challenge_id,
        motivation_letter="Chosen student motivation letter " * 3,
        status=Application.Status.PENDING,
    )
    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={
            "id": str(challenge_id),
            "company_id": str(company_user.id),
            "title": "API Refactoring",
            "status": "OPEN",
        },
    )
    respx.post(
        f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}/lock"
    ).respond(200, json={"id": str(challenge_id), "status": "IN_PROGRESS", "locked": True})
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    ).respond(503)
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/companies/{company_user.id}/contact"
    ).respond(503)

    api_client.force_authenticate(user=company_user)
    response = api_client.post(accept_url(target.id), format="json")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == Application.Status.ACCEPTED
    assert body["contact_reveal"] == {"student": {}, "company": {}}
