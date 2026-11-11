"""Serializers for application submission and representation."""

from __future__ import annotations

from rest_framework import serializers

from apps.applications.models import Application


class ApplicationCreateSerializer(serializers.Serializer):
    """Validate incoming payload for application submission."""

    challenge_id = serializers.UUIDField(
        required=True,
        error_messages={
            "required": "The 'challenge_id' field is required.",
            "invalid": "Must be a valid UUID.",
        },
    )
    motivation_letter = serializers.CharField(
        min_length=50,
        max_length=2000,
        required=True,
        trim_whitespace=True,
        error_messages={
            "required": "The 'motivation_letter' field is required.",
            "min_length": "Ensure motivation letter has at least 50 characters.",
            "max_length": "Ensure motivation letter has no more than 2000 characters.",
        },
    )


class ApplicationResponseSerializer(serializers.ModelSerializer):
    """Serialize persisted application entities for HTTP response."""

    class Meta:
        model = Application
        fields = (
            "id",
            "student_id",
            "challenge_id",
            "motivation_letter",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
