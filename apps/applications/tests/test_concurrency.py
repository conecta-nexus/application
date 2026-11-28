"""Concurrency and row-level locking tests for application submission and acceptance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
from unittest.mock import patch

from django.db import IntegrityError, connection, connections
import pytest
import respx
from rest_framework import status
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.core.authentication import StatelessJWTUser

CHALLENGE_BASE_URL = "http://challenge:8000"
PROFILE_BASE_URL = "http://profile:8000"
APPLICATIONS_URL = "/api/v1/applications/"


@pytest.mark.django_db
@respx.mock
def test_create_application_handles_concurrent_integrity_error_as_409() -> None:
    """When two requests race past existence check, DB unique constraint yields 409 Conflict."""
    student_id = uuid.uuid4()
    challenge_id = uuid.uuid4()
    student_user = StatelessJWTUser(
        {
            "sub": str(student_id),
            "email": "student@ufps.edu.co",
            "role": "STUDENT",
            "is_active": True,
        }
    )

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        200, json={"id": str(challenge_id), "status": "OPEN"}
    )
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    ).respond(
        200,
        json={"user_id": str(student_id), "is_eligible": True, "current_semester": 8, "has_consent": True},
    )

    client = APIClient()
    client.force_authenticate(user=student_user)

    with patch.object(
        Application.objects,
        "create",
        side_effect=IntegrityError("duplicate key value violates unique constraint"),
    ):
        response = client.post(
            APPLICATIONS_URL,
            {
                "challenge_id": str(challenge_id),
                "motivation_letter": "Valid motivation letter content spanning enough characters.",
            },
            format="json",
        )

    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
@respx.mock
def test_sequential_second_accept_after_commit_fails_with_409() -> None:
    """Second acceptance attempt on another candidate returns 409 and preserves first match."""
    company_id = uuid.uuid4()
    challenge_id = uuid.uuid4()
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()

    company_user = StatelessJWTUser(
        {"sub": str(company_id), "email": "corp@nexus.co", "role": "COMPANY", "is_active": True}
    )

    app_a = Application.objects.create(
        student_id=student_a,
        challenge_id=challenge_id,
        motivation_letter="Candidate A motivation letter " * 3,
        status=Application.Status.PENDING,
    )
    app_b = Application.objects.create(
        student_id=student_b,
        challenge_id=challenge_id,
        motivation_letter="Candidate B motivation letter " * 3,
        status=Application.Status.PENDING,
    )

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={"id": str(challenge_id), "company_id": str(company_id), "status": "OPEN"},
    )
    respx.post(
        f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}/lock"
    ).respond(200, json={"id": str(challenge_id), "status": "IN_PROGRESS", "locked": True})
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_a}/eligibility"
    ).respond(200, json={"contact_info": {"email": "a@ufps.edu.co"}})
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/companies/{company_id}/contact"
    ).respond(200, json={"business_name": "Corp", "contact_info": {"email": "corp@nexus.co"}})

    client = APIClient()
    client.force_authenticate(user=company_user)

    first = client.post(f"/api/v1/applications/{app_a.id}/accept/", format="json")
    second = client.post(f"/api/v1/applications/{app_b.id}/accept/", format="json")

    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_409_CONFLICT
    app_a.refresh_from_db()
    app_b.refresh_from_db()
    assert app_a.status == Application.Status.ACCEPTED
    assert app_b.status == Application.Status.REJECTED


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Real SELECT FOR UPDATE concurrency test requires PostgreSQL.",
)
@pytest.mark.django_db(transaction=True)
@respx.mock
def test_concurrent_accept_requests_with_postgres_row_locks_allow_single_winner() -> None:
    """Two simultaneous POST /accept requests under PostgreSQL yield one 200 and one 409."""
    company_id = uuid.uuid4()
    challenge_id = uuid.uuid4()
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()

    company_user = StatelessJWTUser(
        {"sub": str(company_id), "email": "corp@nexus.co", "role": "COMPANY", "is_active": True}
    )

    app_a = Application.objects.create(
        student_id=student_a,
        challenge_id=challenge_id,
        motivation_letter="Candidate A motivation letter " * 3,
        status=Application.Status.PENDING,
    )
    app_b = Application.objects.create(
        student_id=student_b,
        challenge_id=challenge_id,
        motivation_letter="Candidate B motivation letter " * 3,
        status=Application.Status.PENDING,
    )

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}").respond(
        200,
        json={"id": str(challenge_id), "company_id": str(company_id), "status": "OPEN"},
    )
    lock_route = respx.post(
        f"{CHALLENGE_BASE_URL}/api/v1/challenges/internal/{challenge_id}/lock"
    ).respond(200, json={"id": str(challenge_id), "status": "IN_PROGRESS", "locked": True})
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_a}/eligibility"
    ).respond(200, json={"contact_info": {"email": "a@ufps.edu.co"}})
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_b}/eligibility"
    ).respond(200, json={"contact_info": {"email": "b@ufps.edu.co"}})
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/companies/{company_id}/contact"
    ).respond(200, json={"business_name": "Corp", "contact_info": {"email": "corp@nexus.co"}})

    barrier = threading.Barrier(2, timeout=5)

    def worker(target_app_id: uuid.UUID) -> int:
        try:
            client = APIClient()
            client.force_authenticate(user=company_user)
            barrier.wait()
            resp = client.post(f"/api/v1/applications/{target_app_id}/accept/", format="json")
            return resp.status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, app_a.id), pool.submit(worker, app_b.id)]
        results = sorted(f.result(timeout=15) for f in futures)

    assert results == [status.HTTP_200_OK, status.HTTP_409_CONFLICT]
    assert lock_route.call_count == 1
    statuses = list(
        Application.objects.filter(challenge_id=challenge_id).values_list("status", flat=True)
    )
    assert sorted(statuses) == [Application.Status.ACCEPTED, Application.Status.REJECTED]


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Real SELECT FOR UPDATE concurrency test requires PostgreSQL.",
)
@pytest.mark.django_db(transaction=True)
@respx.mock
def test_concurrent_duplicate_create_requests_with_postgres_allow_single_record() -> None:
    """Two simultaneous POST /applications requests by one student produce one 201 and one 409."""
    student_id = uuid.uuid4()
    challenge_id = uuid.uuid4()
    student_user = StatelessJWTUser(
        {"sub": str(student_id), "email": "student@ufps.edu.co", "role": "STUDENT", "is_active": True}
    )

    respx.get(f"{CHALLENGE_BASE_URL}/api/v1/challenges/{challenge_id}").respond(
        200, json={"id": str(challenge_id), "status": "OPEN"}
    )
    respx.get(
        f"{PROFILE_BASE_URL}/api/v1/profiles/internal/{student_id}/eligibility"
    ).respond(
        200,
        json={"user_id": str(student_id), "is_eligible": True, "current_semester": 8, "has_consent": True},
    )

    barrier = threading.Barrier(2, timeout=5)
    payload = {
        "challenge_id": str(challenge_id),
        "motivation_letter": "Simultaneous application submission test letter spanning fifty chars.",
    }

    def worker() -> int:
        try:
            client = APIClient()
            client.force_authenticate(user=student_user)
            barrier.wait()
            resp = client.post(APPLICATIONS_URL, payload, format="json")
            return resp.status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker), pool.submit(worker)]
        results = sorted(f.result(timeout=15) for f in futures)

    assert results == [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT]
    assert Application.objects.filter(student_id=student_id, challenge_id=challenge_id).count() == 1
