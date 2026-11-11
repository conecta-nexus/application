"""Synchronous client for challenge status validation."""

from functools import lru_cache
from typing import Any
from uuid import UUID

import httpx
from django.conf import settings

from apps.applications.exceptions import (
    ChallengeNotFoundError,
    ChallengeNotOpenError,
    ChallengeServiceUnavailableError,
)


class ChallengeServiceClient:
    """Validate challenge availability through the Challenge microservice."""

    _MAX_CONNECTIONS = 20
    _MAX_KEEPALIVE_CONNECTIONS = 10

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Create a reusable client, allowing transport injection in tests."""
        self._owns_http_client = http_client is None

        if http_client is not None:
            self._http_client = http_client
            return

        resolved_base_url = (
            settings.CHALLENGE_SERVICE_URL if base_url is None else base_url
        ).strip().rstrip("/")
        resolved_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.CHALLENGE_SERVICE_TIMEOUT_SECONDS
        )

        if not resolved_base_url:
            raise ValueError("Challenge service base URL cannot be empty")
        if resolved_timeout <= 0:
            raise ValueError("Challenge service timeout must be greater than zero")

        self._http_client = httpx.Client(
            base_url=resolved_base_url,
            timeout=httpx.Timeout(resolved_timeout),
            limits=httpx.Limits(
                max_connections=self._MAX_CONNECTIONS,
                max_keepalive_connections=self._MAX_KEEPALIVE_CONNECTIONS,
            ),
            headers={"Accept": "application/json"},
        )

    def validate_open_challenge(
        self,
        challenge_id: UUID | str,
    ) -> dict[str, Any]:
        """Return challenge data when it exists and its status is OPEN."""
        normalized_id = str(challenge_id)
        endpoint = f"/api/v1/challenges/{normalized_id}"

        try:
            response = self._http_client.get(endpoint)
        except httpx.RequestError as exc:
            raise ChallengeServiceUnavailableError(
                "Challenge service request failed"
            ) from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ChallengeNotFoundError(normalized_id)

        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ChallengeServiceUnavailableError(
                f"Challenge service returned HTTP {response.status_code}"
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ChallengeServiceUnavailableError(
                f"Challenge service returned unexpected HTTP {response.status_code}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ChallengeServiceUnavailableError(
                "Challenge service returned invalid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise ChallengeServiceUnavailableError(
                "Challenge service returned an invalid response payload"
            )

        raw_status = payload.get("status")
        if not isinstance(raw_status, str) or not raw_status.strip():
            raise ChallengeServiceUnavailableError(
                "Challenge service response does not contain a valid status"
            )

        status = raw_status.strip().upper()
        if status != "OPEN":
            raise ChallengeNotOpenError(normalized_id, status)

        return payload

    def close(self) -> None:
        """Release the owned HTTP connection pool."""
        if self._owns_http_client:
            self._http_client.close()


@lru_cache(maxsize=1)
def get_challenge_service_client() -> ChallengeServiceClient:
    """Return one process-wide client so its connection pool is reused."""
    return ChallengeServiceClient()
