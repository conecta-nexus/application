import uuid

from django.core.validators import MaxLengthValidator, MinLengthValidator
from django.db import models


class Application(models.Model):
    """Represent a student's application to a challenge."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_id = models.UUIDField(db_index=True)
    challenge_id = models.UUIDField(db_index=True)
    motivation_letter = models.TextField(
        validators=[
            MinLengthValidator(50),
            MaxLengthValidator(2000),
        ]
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "applications"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("student_id", "challenge_id"),
                name="unique_active_student_challenge_application",
            )
        ]

    def __str__(self) -> str:
        return f"{self.student_id} -> {self.challenge_id} ({self.status})"
