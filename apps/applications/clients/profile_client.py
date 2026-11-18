"""Synchronous HTTP client for querying student academic eligibility in profile microservice."""

from __future__ import annotations

import logging
import time
from typing import Any
import uuid

from django.conf import settings
import httpx

from apps.applications.exceptions import (
    ConsentMissingError,
    ProfileServiceUnavailableError,
    StudentNotEligibleError,
    StudentProfileNotFoundError,
)

logger = logging.getLogger(__name__)


class ProfileServiceClient:
    """Synchronous HTTP client for the profile microservice internal eligibility API."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 3.0,
        max_retries: int = 2,
        backoff_factor: float = 0.2,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize the profile service client.

        Args:
            base_url: Base URL of the profile service.
            token: Bearer JWT token with internal service scope.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retries for 5xx errors or network failures.
            backoff_factor: Multiplier for exponential backoff between retries.
            client: Optional pre-configured httpx.Client instance.
        """
        raw_url = base_url or getattr(settings, "PROFILE_SERVICE_URL", "http://profile:8000")
        self.base_url = str(raw_url).rstrip("/")
        self.token = token if token is not None else getattr(settings, "INTERNAL_SERVICE_TOKEN", "")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
            self._client = httpx.Client(timeout=self.timeout, limits=limits)
            self._owns_client = True

    def close(self) -> None:
        """Close underlying HTTP client connections."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ProfileServiceClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def check_eligibility(
        self,
        student_id: uuid.UUID | str,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Query the internal eligibility endpoint of the profile microservice.

        Validates whether a student is in semesters 6-10 and has accepted the
        mandatory Habeas Data consent (RB-02).

        Args:
            student_id: UUID of the student to query.
            token: Optional override token for Authorization header.

        Returns:
            Dictionary containing student eligibility and profile details:
            {
                "user_id": "<uuid>",
                "is_eligible": True,
                "current_semester": 7,
                "has_consent": True,
                "contact_info": {"email": "...", "phone": "..."}
            }

        Raises:
            StudentProfileNotFoundError: Student does not exist in profile service (404).
            ConsentMissingError: Student has not accepted Habeas Data consent.
            StudentNotEligibleError: Student is not eligible (semester outside 6-10).
            ProfileServiceUnavailableError: Service returned 5xx, timed out, or connection failed.
        """
        url = f"{self.base_url}/api/v1/profiles/internal/{student_id}/eligibility"
        auth_token = token if token is not None else self.token

        headers: dict[str, str] = {
            "Accept": "application/json",
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        last_exception: Exception | None = None
        response: httpx.Response | None = None

        total_attempts = self.max_retries + 1
        for attempt in range(total_attempts):
            try:
                response = self._client.get(url, headers=headers)
                if response.status_code >= 500:
                    if attempt < self.max_retries:
                        logger.warning(
                            "Profile service returned status %d on attempt %d/%d; retrying...",
                            response.status_code,
                            attempt + 1,
                            total_attempts,
                        )
                        time.sleep(self.backoff_factor * (2**attempt))
                        continue
                    raise ProfileServiceUnavailableError(
                        f"Profile service returned server error {response.status_code}."
                    )
                # Success or client-side error (4xx) - do not retry 4xx
                break
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    logger.warning(
                        "Network error connecting to profile service on attempt %d/%d: %s; retrying...",
                        attempt + 1,
                        total_attempts,
                        exc,
                    )
                    time.sleep(self.backoff_factor * (2**attempt))
                    continue
                raise ProfileServiceUnavailableError(
                    f"Profile service communication error after {total_attempts} attempts: {exc}"
                ) from exc

        if response is None:
            raise ProfileServiceUnavailableError(
                f"Profile service unavailable: {last_exception}"
            )

        if response.status_code == 404:
            raise StudentProfileNotFoundError("Student profile not found for the specified user.")

        if response.status_code in (401, 403):
            raise ProfileServiceUnavailableError(
                "Application microservice is unauthorized to access profile eligibility."
            )

        if response.status_code != 200:
            raise ProfileServiceUnavailableError(
                f"Profile service returned unexpected status {response.status_code}."
            )

        try:
            data = response.json()
        except Exception as exc:
            raise ProfileServiceUnavailableError(
                "Profile service returned invalid JSON response."
            ) from exc

        # RB-02: Habeas data consent verification
        has_consent = bool(data.get("has_consent", False))
        if not has_consent:
            raise ConsentMissingError(
                "Student has not provided mandatory Habeas Data consent."
            )

        # RB-02: Semester range [6, 10] verification
        current_semester = data.get("current_semester")
        is_eligible = bool(data.get("is_eligible", False))

        if (
            not is_eligible
            or current_semester is None
            or not (6 <= int(current_semester) <= 10)
        ):
            raise StudentNotEligibleError(
                f"Student in semester {current_semester} is not academically eligible (semesters 6-10 required)."
            )

        return data
