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
from apps.core.permissions import IsStudentUser

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

        # 4. Atomic database persistence
        try:
            with transaction.atomic():
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
