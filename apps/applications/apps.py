from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    """Configure the applications domain Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.applications"
    verbose_name = "Applications"
