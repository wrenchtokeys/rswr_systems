"""
Web-based diagnostic view for production troubleshooting.

Access at: /diagnostic/ (requires authentication)
"""

from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
import redis
import logging

logger = logging.getLogger(__name__)


@login_required
def diagnostic_view(request):
    """
    Comprehensive diagnostic page showing:
    1. SendGrid email configuration
    2. Celery worker status
    3. Redis queue status
    4. Direct email test option
    """

    # Collect diagnostic information
    diagnostics = {}

    # 1. Email Configuration
    diagnostics['email'] = {
        'backend': settings.EMAIL_BACKEND,
        'host': settings.EMAIL_HOST,
        'port': settings.EMAIL_PORT,
        'use_tls': settings.EMAIL_USE_TLS,
        'from_email': settings.DEFAULT_FROM_EMAIL,
        'api_key_set': bool(settings.EMAIL_HOST_PASSWORD),
    }

    # 2. Celery Configuration
    diagnostics['celery'] = {
        'broker_url': settings.CELERY_BROKER_URL,
        'result_backend': settings.CELERY_RESULT_BACKEND,
    }

    # 3. Redis Connection Test
    try:
        r = redis.from_url(settings.CELERY_BROKER_URL)
        r.ping()
        diagnostics['redis'] = {
            'status': 'connected',
            'error': None
        }

        # Check queue lengths
        queue_lengths = {}
        for queue_name in ['celery', 'notifications', 'maintenance']:
            length = r.llen(queue_name if queue_name != 'celery' else 'celery')
            queue_lengths[queue_name] = length

        diagnostics['redis']['queues'] = queue_lengths
        diagnostics['redis']['total_queued'] = sum(queue_lengths.values())

    except Exception as e:
        diagnostics['redis'] = {
            'status': 'error',
            'error': str(e)
        }

    # 4. Celery Worker Status
    try:
        from rs_systems.celery import app as celery_app
        inspect = celery_app.control.inspect(timeout=2.0)
        active_workers = inspect.active()

        if active_workers:
            diagnostics['celery']['workers'] = {
                'status': 'online',
                'count': len(active_workers),
                'details': {name: len(tasks) for name, tasks in active_workers.items()}
            }
        else:
            diagnostics['celery']['workers'] = {
                'status': 'offline',
                'count': 0,
                'details': {}
            }
    except Exception as e:
        diagnostics['celery']['workers'] = {
            'status': 'error',
            'count': 0,
            'error': str(e)
        }

    # 5. Test Direct Email (if requested)
    if request.GET.get('send_test_email') == 'true':
        user_email = request.user.email
        try:
            email = EmailMultiAlternatives(
                subject='RS Systems Diagnostic Test Email',
                body=f'Test email sent at {timezone.now()}. If you receive this, SendGrid is working.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user_email]
            )

            html = f'''
            <html>
            <body>
                <h2>✅ SendGrid Test Successful</h2>
                <p>You received this email, which means SendGrid is configured correctly.</p>
                <p><small>Sent at {timezone.now()}</small></p>
            </body>
            </html>
            '''
            email.attach_alternative(html, "text/html")

            result = email.send(fail_silently=False)

            diagnostics['test_email'] = {
                'status': 'sent' if result == 1 else 'failed',
                'recipient': user_email,
                'timestamp': str(timezone.now())
            }
        except Exception as e:
            diagnostics['test_email'] = {
                'status': 'error',
                'error': str(e)
            }

    # Generate HTML report
    if request.GET.get('format') == 'json':
        return JsonResponse(diagnostics, json_dumps_params={'indent': 2})

    # HTML view
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>RS Systems Production Diagnostics</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; }}
            h1 {{ color: #333; }}
            h2 {{ color: #0066cc; margin-top: 30px; }}
            .status {{ padding: 10px; border-radius: 4px; margin: 10px 0; }}
            .success {{ background: #d4edda; color: #155724; }}
            .warning {{ background: #fff3cd; color: #856404; }}
            .error {{ background: #f8d7da; color: #721c24; }}
            .info {{ background: #d1ecf1; color: #0c5460; }}
            pre {{ background: #f8f9fa; padding: 15px; border-radius: 4px; overflow-x: auto; }}
            .btn {{ display: inline-block; padding: 10px 20px; background: #0066cc; color: white; text-decoration: none; border-radius: 4px; margin: 10px 0; }}
            .btn:hover {{ background: #0052a3; }}
            table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #f8f9fa; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔧 RS Systems Production Diagnostics</h1>
            <p>Generated at: {timezone.now()}</p>
            <p>User: {request.user.email}</p>

            <h2>📧 Email Configuration (SendGrid)</h2>
            <table>
                <tr><th>Setting</th><th>Value</th></tr>
                <tr><td>Email Backend</td><td>{diagnostics['email']['backend']}</td></tr>
                <tr><td>SMTP Host</td><td>{diagnostics['email']['host']}</td></tr>
                <tr><td>SMTP Port</td><td>{diagnostics['email']['port']}</td></tr>
                <tr><td>Use TLS</td><td>{diagnostics['email']['use_tls']}</td></tr>
                <tr><td>From Email</td><td>{diagnostics['email']['from_email']}</td></tr>
                <tr><td>API Key Set</td><td>{'✅ Yes' if diagnostics['email']['api_key_set'] else '❌ No'}</td></tr>
            </table>

            <h2>🔄 Celery Workers</h2>
            {f'''
            <div class="status {'success' if diagnostics['celery']['workers']['status'] == 'online' else 'error'}">
                <strong>Status:</strong> {diagnostics['celery']['workers']['status'].upper()}<br>
                <strong>Active Workers:</strong> {diagnostics['celery']['workers']['count']}<br>
                {f"<strong>Details:</strong> {diagnostics['celery']['workers']['details']}" if diagnostics['celery']['workers']['count'] > 0 else ''}
            </div>
            ''' if diagnostics['celery']['workers']['status'] != 'error' else f'''
            <div class="status error">
                <strong>Error:</strong> {diagnostics['celery']['workers'].get('error', 'Unknown error')}<br>
                <strong>This means Celery workers are NOT running!</strong>
            </div>
            '''}

            <h2>📦 Redis Queue Status</h2>
            {f'''
            <div class="status {'success' if diagnostics['redis']['status'] == 'connected' else 'error'}">
                <strong>Connection:</strong> {diagnostics['redis']['status'].upper()}<br>
                <strong>Total Queued Tasks:</strong> {diagnostics['redis'].get('total_queued', 0)}
            </div>
            <table>
                <tr><th>Queue</th><th>Pending Tasks</th></tr>
                {chr(10).join(f"<tr><td>{name}</td><td>{count}</td></tr>" for name, count in diagnostics['redis'].get('queues', {}).items())}
            </table>
            ''' if diagnostics['redis']['status'] == 'connected' else f'''
            <div class="status error">
                <strong>Error:</strong> {diagnostics['redis'].get('error', 'Unknown error')}
            </div>
            '''}

            {f'''
            <h2>✉️ Test Email Result</h2>
            <div class="status {'success' if diagnostics['test_email']['status'] == 'sent' else 'error'}">
                <strong>Status:</strong> {diagnostics['test_email']['status'].upper()}<br>
                <strong>Recipient:</strong> {diagnostics['test_email'].get('recipient', 'N/A')}<br>
                {f"<strong>Error:</strong> {diagnostics['test_email'].get('error', '')}<br>" if diagnostics['test_email']['status'] == 'error' else ''}
                {f"<strong>Check your email inbox at {diagnostics['test_email'].get('recipient')}</strong>" if diagnostics['test_email']['status'] == 'sent' else ''}
            </div>
            ''' if 'test_email' in diagnostics else ''}

            <h2>🧪 Actions</h2>
            <a href="?send_test_email=true" class="btn">Send Test Email to {request.user.email}</a>
            <a href="?format=json" class="btn">View JSON</a>

            <h2>📊 Diagnosis</h2>
            {_generate_diagnosis(diagnostics)}

            <h2>📋 Raw Data</h2>
            <pre>{_format_dict(diagnostics)}</pre>
        </div>
    </body>
    </html>
    '''

    return HttpResponse(html)


def _generate_diagnosis(diagnostics):
    """Generate diagnosis based on diagnostic data."""

    workers_online = diagnostics['celery']['workers']['status'] == 'online'
    redis_connected = diagnostics['redis']['status'] == 'connected'
    tasks_queued = diagnostics['redis'].get('total_queued', 0) > 0

    if not redis_connected:
        return '<div class="status error"><strong>❌ CRITICAL:</strong> Redis is not accessible. Check ElastiCache configuration.</div>'

    if not workers_online and tasks_queued:
        return '''
        <div class="status error">
            <strong>❌ ISSUE FOUND:</strong> Celery workers are NOT running but tasks are queued!<br><br>
            <strong>Root Cause:</strong> Email tasks are being created but not processed.<br><br>
            <strong>Solution:</strong><br>
            1. Check systemd service: <code>sudo systemctl status celery-worker</code><br>
            2. View logs: <code>sudo journalctl -u celery-worker -n 100</code><br>
            3. Check .ebextensions/celery.config deployment<br>
            4. Restart if needed: <code>sudo systemctl restart celery-worker</code>
        </div>
        '''

    if not workers_online and not tasks_queued:
        return '''
        <div class="status warning">
            <strong>⚠️ WARNING:</strong> Celery workers are not running.<br><br>
            <strong>Impact:</strong> New email notifications will not be sent until workers are started.<br><br>
            <strong>Action Required:</strong> Start Celery workers on production EC2 instance.
        </div>
        '''

    if workers_online and not tasks_queued:
        return '''
        <div class="status success">
            <strong>✅ ALL SYSTEMS OPERATIONAL</strong><br><br>
            Workers are running and queue is empty. System is healthy.<br><br>
            If emails still aren't being sent, the issue may be with:<br>
            - Notification creation (check /test-notification/)<br>
            - SendGrid account (send test email above)
        </div>
        '''

    if workers_online and tasks_queued:
        return '''
        <div class="status info">
            <strong>ℹ️ INFO:</strong> Workers are processing tasks.<br><br>
            There are tasks in the queue being worked on. This is normal during high load.
        </div>
        '''

    return '<div class="status info">Status unclear. Review data above.</div>'


def _format_dict(d, indent=0):
    """Format dictionary for display."""
    import json
    return json.dumps(d, indent=2, default=str)
