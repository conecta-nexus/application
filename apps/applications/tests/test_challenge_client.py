"""Integration tests for the synchronous Challenge service client."""

from uuid import UUID, uuid4

import httpx
import pytest

from apps.applications.clients.challenge_client import ChallengeServiceClient
from apps.applications.exceptions import (
    ChallengeNotFoundError,
    ChallengeNotOpenError,
    ChallengeServiceUnavailableError,
)


def build_service(handler: httpx.MockTransport) -> ChallengeServiceClient:
    """Build the service with a real httpx client and mocked transport."""
    http_client = httpx.Client(
        base_url="http://challenge:8000",
        transport=handler,
        timeout=3.0,
    )
    return ChallengeServiceClient(http_client=http_client)


def challenge_payload(challenge_id: UUID, status: str) -> dict[str, str]:
    """Return the response fields required by this client contract."""
    return {
        "id": str(challenge_id),
        "title": "Improve legal case assignment",
        "status": status,
    }


def test_validate_open_challenge_returns_payload() -> None:
    """Accept an existing challenge whose status is strictly OPEN."""
    challenge_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == f"/api/v1/challenges/{challenge_id}"
        return httpx.Response(
            200,
            json=challenge_payload(challenge_id, "OPEN"),
        )

    service = build_service(httpx.MockTransport(handler))

    result = service.validate_open_challenge(challenge_id)

    assert result["id"] == str(challenge_id)
    assert result["status"] == "OPEN"


@pytest.mark.parametrize(
    "status",
    ["DRAFT", "IN_PROGRESS", "CLOSED", "CANCELLED"],
)
def test_validate_open_challenge_rejects_non_open_status(status: str) -> None:
    """Reject every challenge state that does not accept applications."""
    challenge_id = uuid4()
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json=challenge_payload(challenge_id, status),
        )
    )
    service = build_service(transport)

    with pytest.raises(ChallengeNotOpenError) as exc_info:
        service.validate_open_challenge(challenge_id)

    assert exc_info.value.challenge_id == str(challenge_id)
    assert exc_info.value.status == status


def test_validate_open_challenge_raises_not_found_for_404() -> None:
    """Translate a 404 response into the domain exception."""
    challenge_id = uuid4()
    service = build_service(
        httpx.MockTransport(lambda _: httpx.Response(404, json={"detail": "Not found"}))
    )

    with pytest.raises(ChallengeNotFoundError) as exc_info:
        service.validate_open_challenge(challenge_id)

    assert exc_info.value.challenge_id == str(challenge_id)


def test_validate_open_challenge_translates_timeout() -> None:
    """Translate network timeouts into an unavailable-service error."""
    challenge_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Challenge timed out", request=request)

    service = build_service(httpx.MockTransport(handler))

    with pytest.raises(
        ChallengeServiceUnavailableError,
        match="Challenge service request failed",
    ):
        service.validate_open_challenge(challenge_id)


def test_validate_open_challenge_translates_server_error() -> None:
    """Translate upstream 5xx responses into an unavailable-service error."""
    service = build_service(
        httpx.MockTransport(lambda _: httpx.Response(503, json={"detail": "Unavailable"}))
    )

    with pytest.raises(
        ChallengeServiceUnavailableError,
        match="Challenge service returned HTTP 503",
    ):
        service.validate_open_challenge(uuid4())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"id": str(uuid4())}),
    ],
)
def test_validate_open_challenge_rejects_invalid_payload(
    response: httpx.Response,
) -> None:
    """Treat malformed upstream payloads as an unavailable service contract."""
    service = build_service(httpx.MockTransport(lambda _: response))

    with pytest.raises(ChallengeServiceUnavailableError):
        service.validate_open_challenge(uuid4())
