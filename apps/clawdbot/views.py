import os
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
        'email': os.environ.get('CLAWDBOT_EMAIL', ''),
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
    Returns a simple health status for monitoring.
    """
    return JsonResponse({
        'healthy': True,
        'service': 'clawdbot',
    })
