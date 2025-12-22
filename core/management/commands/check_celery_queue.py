"""
Management command to check Celery task queue status in Redis.

This helps diagnose whether:
1. Tasks are being queued correctly
2. Workers are processing tasks
3. Tasks are stuck in the queue

Usage:
    python manage.py check_celery_queue
"""

from django.core.management.base import BaseCommand
from django.conf import settings
import redis
import json


class Command(BaseCommand):
    help = 'Check Celery task queue status in Redis'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('\n=== Celery Queue Diagnostic ==='))

        try:
            # Connect to Redis
            broker_url = settings.CELERY_BROKER_URL
            self.stdout.write(f'Broker URL: {broker_url}')

            r = redis.from_url(broker_url)

            # Test connection
            self.stdout.write(self.style.NOTICE('\nTesting Redis connection...'))
            r.ping()
            self.stdout.write(self.style.SUCCESS('✅ Redis connection OK'))

            # Check queue lengths
            self.stdout.write(self.style.NOTICE('\n=== Queue Status ==='))

            queues = ['celery', 'notifications', 'maintenance']
            total_tasks = 0

            for queue_name in queues:
                # Celery uses 'celery' as default queue name in Redis
                redis_key = f'celery'  # Default Celery queue key
                if queue_name != 'celery':
                    redis_key = queue_name

                length = r.llen(redis_key)
                total_tasks += length

                if length > 0:
                    self.stdout.write(
                        self.style.WARNING(f'  {queue_name}: {length} tasks pending')
                    )
                else:
                    self.stdout.write(f'  {queue_name}: {length} tasks')

            # Check if there are tasks waiting
            if total_tasks > 0:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(
                    f'⚠️  {total_tasks} tasks in queue but not being processed!'
                ))
                self.stdout.write(self.style.WARNING(
                    'This indicates Celery workers are NOT running.'
                ))
                self.stdout.write('')
                self.stdout.write('To start workers on production:')
                self.stdout.write('  sudo systemctl start celery-worker')
                self.stdout.write('  sudo systemctl status celery-worker')
            else:
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS('✅ No tasks in queue'))

            # Check active workers (Celery stores this in Redis)
            self.stdout.write(self.style.NOTICE('\n=== Worker Status ==='))
            try:
                # Try to get active workers from Celery
                # This requires celery to be running
                from rs_systems.celery import app as celery_app

                inspect = celery_app.control.inspect(timeout=2.0)
                active_workers = inspect.active()

                if active_workers:
                    self.stdout.write(self.style.SUCCESS(f'✅ {len(active_workers)} worker(s) online:'))
                    for worker_name, tasks in active_workers.items():
                        self.stdout.write(f'  - {worker_name}: {len(tasks)} active tasks')
                else:
                    self.stdout.write(self.style.ERROR('❌ No Celery workers responding'))
                    self.stdout.write('')
                    self.stdout.write(self.style.WARNING('Workers may be stopped. Check systemd:'))
                    self.stdout.write('  sudo systemctl status celery-worker')
                    self.stdout.write('  sudo journalctl -u celery-worker -n 50')

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'❌ Could not check worker status: {str(e)}'))
                self.stdout.write(self.style.WARNING('This usually means Celery workers are not running'))

            # Summary
            self.stdout.write(self.style.NOTICE('\n=== Summary ==='))
            self.stdout.write(f'Total queued tasks: {total_tasks}')

            if total_tasks > 0:
                self.stdout.write('')
                self.stdout.write(self.style.ERROR('❌ ISSUE FOUND: Tasks are queued but not processing'))
                self.stdout.write('')
                self.stdout.write('Root cause: Celery workers are not running on production')
                self.stdout.write('')
                self.stdout.write('Solution:')
                self.stdout.write('  1. SSH into production EC2 instance')
                self.stdout.write('  2. Check systemd service: sudo systemctl status celery-worker')
                self.stdout.write('  3. View logs: sudo journalctl -u celery-worker -n 100')
                self.stdout.write('  4. Restart if needed: sudo systemctl restart celery-worker')

        except redis.ConnectionError as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Cannot connect to Redis: {str(e)}'))
            self.stdout.write('')
            self.stdout.write('Check:')
            self.stdout.write(f'  - CELERY_BROKER_URL environment variable')
            self.stdout.write(f'  - ElastiCache Redis is running')
            self.stdout.write(f'  - Security groups allow connection')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Error: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())
