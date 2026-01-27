from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def status(request):
    """
    Clawdbot status endpoint.
    Returns basic information about Clawdbot's operational status.
    """
    return JsonResponse({
        'status': 'online',
        'name': 'Clawdbot',
        'capabilities': [
            'web_browsing',
            'email',
            'github_access',
            's3_photo_access',
            'x_drafts',
        ],
        'endpoints': {
            'status': '/clawdbot/',
            'health': '/clawdbot/health/',
        }
    })


@require_GET
def health(request):
    """
    Clawdbot health check endpoint.
    Returns actual health status by checking database connectivity.
    """
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({
            'healthy': True,
            'service': 'clawdbot',
            'database': 'connected',
        })
    except Exception as e:
        return JsonResponse({
            'healthy': False,
            'service': 'clawdbot',
            'database': 'error',
        }, status=503)
