"""HTTP clients for external microservice communication."""

from apps.applications.clients.challenge_client import (
    ChallengeServiceClient,
    get_challenge_service_client,
)
from apps.applications.clients.profile_client import ProfileServiceClient

__all__ = [
    "ChallengeServiceClient",
    "ProfileServiceClient",
    "get_challenge_service_client",
]
