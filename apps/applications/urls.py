"""Routing configuration for the applications domain."""

from django.urls import path

from apps.applications.views import ApplicationAcceptView, ApplicationCreateView

app_name = "applications"

urlpatterns = [
    path("", ApplicationCreateView.as_view(), name="application-create"),
    path(
        "<uuid:application_id>/accept/",
        ApplicationAcceptView.as_view(),
        name="application-accept",
    ),
]
