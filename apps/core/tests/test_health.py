"""Tests for core root and health check endpoints."""

from unittest.mock import patch
from django.db import DatabaseError
from django.test import Client
import pytest


def test_root_endpoint():
    """Verify root endpoint responds with service information."""
    client = Client()
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "application"
    assert data["status"] == "running"
    assert data["framework"] == "django"


@pytest.mark.django_db
def test_health_endpoint_healthy():
    """Verify health endpoint responds with 200 and healthy status when database is up."""
    client = Client()
    response = client.get("/health/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "available"


def test_health_endpoint_unhealthy():
    """Verify health endpoint responds with 503 and unhealthy status when database fails."""
    client = Client()
    with patch("apps.core.views.connection.cursor", side_effect=DatabaseError("DB connection error")):
        response = client.get("/health/")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "unavailable"
