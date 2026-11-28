"""API views for student applications management and orchestration."""

from __future__ import annotations

import logging
from typing import Any

from django.db import IntegrityError, transaction
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.clients.challenge_client import (
    ChallengeServiceClient,
    get_challenge_service_client,
)
from apps.applications.clients.profile_client import ProfileServiceClient
from apps.applications.exceptions import (
    ChallengeNotFoundError,
    ChallengeNotOpenError,
    ChallengeServiceUnavailableError,
    ConsentMissingError,
    ProfileServiceUnavailableError,
    StudentNotEligibleError,
    StudentProfileNotFoundError,
)
from apps.applications.models import Application
from apps.applications.serializers import (
    ApplicationCreateSerializer,
    ApplicationResponseSerializer,
)
from apps.core.permissions import IsCompanyUser, IsStudentUser

logger = logging.getLogger(__name__)


class ApplicationCreateView(APIView):
    """Orchestration controller for submitting a student application.

    Enforces:
    - Authentication and STUDENT role (RBAC).
    - Motivation letter length (50-2000 characters).
    - Challenge existence and OPEN status in challenge microservice.
    - Student academic eligibility (semesters 6-10) and Habeas Data consent in profile microservice (RB-02).
    - Application non-duplicity per student/challenge pair (RB-03).
    - Atomic DB persistence in db_applications.
    """

    permission_classes = [permissions.IsAuthenticated, IsStudentUser]

    def get_challenge_client(self) -> ChallengeServiceClient:
        """Obtain a ChallengeServiceClient instance."""
        return get_challenge_service_client()

    def get_profile_client(self) -> ProfileServiceClient:
        """Obtain a ProfileServiceClient instance."""
        return ProfileServiceClient()

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Handle application submission and validation pipeline."""
        serializer = ApplicationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        challenge_id = serializer.validated_data["challenge_id"]
        motivation_letter = serializer.validated_data["motivation_letter"]
        student_id = getattr(request.user, "id", None) or getattr(request.user, "pk", None)

        if not student_id:
            return Response(
                {"detail": "Unable to determine student identity from token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 1. Non-duplicity check (RB-03 fast check before remote HTTP calls)
        if Application.objects.filter(student_id=student_id, challenge_id=challenge_id).exists():
            return Response(
                {"detail": "Student has already submitted an active application for this challenge."},
                status=status.HTTP_409_CONFLICT,
            )

        # 2. Challenge service validation: challenge must exist and be OPEN
        challenge_client = self.get_challenge_client()
        try:
            challenge_client.validate_open_challenge(challenge_id)
        except ChallengeNotFoundError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ChallengeNotOpenError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except ChallengeServiceUnavailableError as exc:
            logger.error("Challenge service unavailable during application submission: %s", exc)
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # 3. Profile service validation: student eligibility and Habeas Data consent (RB-02)
        profile_client = self.get_profile_client()
        try:
            profile_client.check_eligibility(student_id)
        except (StudentNotEligibleError, ConsentMissingError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except StudentProfileNotFoundError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ProfileServiceUnavailableError as exc:
            logger.error("Profile service unavailable during application submission: %s", exc)
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # 4. Atomic database persistence with row-level duplicate guard (RB-03 / Concurrency)
        try:
            with transaction.atomic():
                if (
                    Application.objects.select_for_update()
                    .filter(student_id=student_id, challenge_id=challenge_id)
                    .exists()
                ):
                    return Response(
                        {"detail": "Student has already submitted an active application for this challenge."},
                        status=status.HTTP_409_CONFLICT,
                    )
                application = Application.objects.create(
                    student_id=student_id,
                    challenge_id=challenge_id,
                    motivation_letter=motivation_letter,
                    status=Application.Status.PENDING,
                )
        except IntegrityError:
            return Response(
                {"detail": "Student has already submitted an active application for this challenge."},
                status=status.HTTP_409_CONFLICT,
            )

        response_data = ApplicationResponseSerializer(application).data
        return Response(response_data, status=status.HTTP_201_CREATED)


class _AcceptConflictError(Exception):
    """Internal control-flow exception to trigger atomic rollback on state conflict."""


class ApplicationAcceptView(APIView):
    """Atomically accept a student application, lock the challenge (RB-04), and reveal contacts (RB-05)."""

    permission_classes = [permissions.IsAuthenticated, IsCompanyUser]

    def get_challenge_client(self) -> ChallengeServiceClient:
        """Obtain a ChallengeServiceClient instance."""
        return get_challenge_service_client()

    def get_profile_client(self) -> ProfileServiceClient:
        """Obtain a ProfileServiceClient instance."""
        return ProfileServiceClient()

    def post(self, request: Request, application_id: Any, *args: Any, **kwargs: Any) -> Response:
        company_id = getattr(request.user, "id", None) or getattr(request.user, "pk", None)
        if not company_id:
            return Response(
                {"detail": "Unable to determine company identity from token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        target_meta = (
            Application.objects.filter(pk=application_id)
            .values("id", "challenge_id")
            .first()
        )
        if target_meta is None:
            return Response(
                {"detail": "Application not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        challenge_id = target_meta["challenge_id"]
        challenge_client = self.get_challenge_client()

        # Verify challenge ownership before acquiring long-lived DB row locks
        try:
            challenge_data = challenge_client.get_challenge_internal(challenge_id)
        except ChallengeNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ChallengeServiceUnavailableError as exc:
            logger.error("Challenge service unavailable during acceptance: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        if str(challenge_data.get("company_id")) != str(company_id):
            return Response(
                {"detail": "Forbidden: You do not own the challenge for this application."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if str(challenge_data.get("status", "")).upper() != "OPEN":
            return Response(
                {"detail": f"Challenge is not OPEN (current status: {challenge_data.get('status')})."},
                status=status.HTTP_409_CONFLICT,
            )

        # Atomic state transition with deterministic row locking (RB-04 / Concurrency)
        try:
            with transaction.atomic():
                locked_apps = list(
                    Application.objects.select_for_update()
                    .filter(challenge_id=challenge_id)
                    .order_by("id")
                )
                target = next((app for app in locked_apps if app.id == application_id), None)
                if target is None:
                    return Response(
                        {"detail": "Application not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                if any(
                    app.status == Application.Status.ACCEPTED and app.id != target.id
                    for app in locked_apps
                ):
                    raise _AcceptConflictError(
                        "Another candidate has already been accepted for this challenge."
                    )

                if target.status != Application.Status.PENDING:
                    raise _AcceptConflictError(
                        f"Application cannot be accepted from '{target.status}' state."
                    )

                target.status = Application.Status.ACCEPTED
                target.save(update_fields=["status", "updated_at"])

                # Freeze/reject competing pending applications on the same challenge
                Application.objects.filter(
                    challenge_id=challenge_id,
                    status=Application.Status.PENDING,
                ).exclude(pk=target.pk).update(status=Application.Status.REJECTED)

                # Synchronously lock challenge to IN_PROGRESS; rolls back DB on failure
                locked_challenge = challenge_client.lock_challenge_in_progress(challenge_id)
        except _AcceptConflictError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ChallengeNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ChallengeNotOpenError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ChallengeServiceUnavailableError as exc:
            logger.error("Challenge lock failed; rolled back application acceptance: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        # Reciprocal contact reveal (RB-05)
        profile_client = self.get_profile_client()
        student_contact: dict[str, Any] = {}
        company_contact: dict[str, Any] = {}
        try:
            student_contact = profile_client.get_student_contact(target.student_id)
        except (StudentProfileNotFoundError, ProfileServiceUnavailableError) as exc:
            logger.warning("Unable to enrich student contact after acceptance: %s", exc)

        try:
            company_contact = profile_client.get_company_contact(company_id)
        except ProfileServiceUnavailableError as exc:
            logger.warning("Unable to enrich company contact after acceptance: %s", exc)

        response_data = dict(ApplicationResponseSerializer(target).data)
        response_data["challenge_status"] = locked_challenge.get("status", "IN_PROGRESS")
        response_data["contact_reveal"] = {
            "student": student_contact,
            "company": company_contact,
        }
        return Response(response_data, status=status.HTTP_200_OK)
