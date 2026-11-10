from django.db import DatabaseError, connection
from django.http import JsonResponse


def root_view(request):
    return JsonResponse(
        {
            "service": "application",
            "status": "running",
            "framework": "django",
        }
    )


def health_view(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse(
            {
                "status": "unhealthy",
                "database": "unavailable",
            },
            status=503,
        )

    return JsonResponse(
        {
            "status": "healthy",
            "database": "available",
        }
    )
