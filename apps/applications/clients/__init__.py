"""HTTP clients for services consumed by the applications domain."""

from .challenge_client import ChallengeServiceClient, get_challenge_service_client

__all__ = ["ChallengeServiceClient", "get_challenge_service_client"]
