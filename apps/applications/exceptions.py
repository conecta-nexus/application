"""Domain exceptions for the applications microservice."""


class ApplicationDomainError(Exception):
    """Base exception for application business domain errors."""


class StudentNotEligibleError(ApplicationDomainError):
    """Raised when a student does not meet the semester eligibility criteria (semesters 6-10)."""

    def __init__(
        self,
        message: str = "Student does not meet academic semester eligibility (must be in semester 6 to 10).",
    ):
        super().__init__(message)
        self.message = message


class ConsentMissingError(ApplicationDomainError):
    """Raised when a student has not accepted the mandatory Law 1581 Habeas Data consent."""

    def __init__(
        self,
        message: str = "Student has not provided mandatory Habeas Data consent.",
    ):
        super().__init__(message)
        self.message = message


class StudentProfileNotFoundError(ApplicationDomainError):
    """Raised when the student profile cannot be found in the profile microservice."""

    def __init__(
        self,
        message: str = "Student profile not found for the specified user.",
    ):
        super().__init__(message)
        self.message = message


class ProfileServiceUnavailableError(ApplicationDomainError):
    """Raised when the profile microservice is unavailable, times out, or returns 5xx."""

    def __init__(
        self,
        message: str = "Profile service is currently unavailable.",
    ):
        super().__init__(message)
        self.message = message


class ChallengeNotFoundError(ApplicationDomainError):
    """Raised when the specified challenge is not found in the challenge microservice."""

    def __init__(
        self,
        message: str = "Challenge not found.",
    ):
        super().__init__(message)
        self.message = message


class ChallengeNotOpenError(ApplicationDomainError):
    """Raised when the challenge is not open for applications."""

    def __init__(
        self,
        message: str = "Challenge is not open for student applications.",
    ):
        super().__init__(message)
        self.message = message


class ChallengeServiceUnavailableError(ApplicationDomainError):
    """Raised when the challenge microservice is unavailable, times out, or returns 5xx."""

    def __init__(
        self,
        message: str = "Challenge service is currently unavailable.",
    ):
        super().__init__(message)
        self.message = message


class DuplicateApplicationError(ApplicationDomainError):
    """Raised when a student attempts to apply more than once to the same challenge (RB-03)."""

    def __init__(
        self,
        message: str = "Student has already submitted an active application for this challenge.",
    ):
        super().__init__(message)
        self.message = message
