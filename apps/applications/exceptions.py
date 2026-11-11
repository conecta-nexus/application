"""Domain exceptions for application submission workflows."""


class ApplicationDomainError(Exception):
    """Base class for expected applications-domain failures."""


class ChallengeNotFoundError(ApplicationDomainError):
    """Raised when the target challenge does not exist."""

    def __init__(self, challenge_id: str) -> None:
        self.challenge_id = challenge_id
        super().__init__(f"Challenge '{challenge_id}' was not found")


class ChallengeNotOpenError(ApplicationDomainError):
    """Raised when applications cannot be submitted to a challenge."""

    def __init__(self, challenge_id: str, status: str) -> None:
        self.challenge_id = challenge_id
        self.status = status
        super().__init__(
            f"Challenge '{challenge_id}' is not open for applications "
            f"(status: {status})"
        )


class ChallengeServiceUnavailableError(ApplicationDomainError):
    """Raised when Challenge cannot provide a valid response."""
