"""
Simple Celery status check view.
Access at: /celery-status/
"""

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.conf import settings
import redis


@login_required
def celery_status(request):
    """
    Check if Celery workers are running and show queue status.
    Returns JSON with diagnostic information.
    """
    status = {}

    # 1. Check Redis connection and queue lengths
    try:
        r = redis.from_url(settings.CELERY_BROKER_URL)
        r.ping()

        # Check default celery queue
        celery_queue_length = r.llen('celery')

        status['redis'] = {
            'connected': True,
            'broker_url': settings.CELERY_BROKER_URL,
            'tasks_in_queue': celery_queue_length
        }
    except Exception as e:
        status['redis'] = {
            'connected': False,
            'error': str(e)
        }
        return JsonResponse(status)

    # 2. Check if Celery workers are responding
    try:
        from rs_systems.celery import app as celery_app

        inspect = celery_app.control.inspect(timeout=2.0)
        active_workers = inspect.active()

        if active_workers:
            status['celery'] = {
                'workers_online': True,
                'worker_count': len(active_workers),
                'workers': list(active_workers.keys()),
                'active_tasks': sum(len(tasks) for tasks in active_workers.values())
            }
        else:
            status['celery'] = {
                'workers_online': False,
                'worker_count': 0,
                'error': 'No workers responding to ping'
            }
    except Exception as e:
        status['celery'] = {
            'workers_online': False,
            'worker_count': 0,
            'error': str(e)
        }

    # 3. Diagnosis
    if status['redis']['tasks_in_queue'] > 0 and not status['celery']['workers_online']:
        status['diagnosis'] = {
            'issue': 'CELERY_WORKERS_NOT_RUNNING',
            'severity': 'CRITICAL',
            'message': f"{status['redis']['tasks_in_queue']} email tasks are queued but no workers are processing them",
            'solution': 'Celery workers need to be started on production EC2 instance via systemd'
        }
    elif not status['celery']['workers_online']:
        status['diagnosis'] = {
            'issue': 'CELERY_WORKERS_NOT_RUNNING',
            'severity': 'HIGH',
            'message': 'No Celery workers are running - new emails will not be sent',
            'solution': 'Check systemd service: sudo systemctl status celery-worker'
        }
    else:
        status['diagnosis'] = {
            'issue': None,
            'severity': 'OK',
            'message': 'Celery workers are running normally'
        }

    return JsonResponse(status, json_dumps_params={'indent': 2})
