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
    return JsonResponse({"status": "healthy"})
