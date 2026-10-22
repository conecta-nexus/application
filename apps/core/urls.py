from django.urls import path
from apps.core import views

app_name = "core"

urlpatterns = [
    path("", views.root_view, name="root"),
    path("health/", views.health_view, name="health"),
]
