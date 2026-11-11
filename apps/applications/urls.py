"""Routing configuration for the applications domain."""

from django.urls import path

from apps.applications.views import ApplicationCreateView

app_name = "applications"

urlpatterns = [
    path("", ApplicationCreateView.as_view(), name="application-create"),
]
