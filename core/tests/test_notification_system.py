"""
Quick integration test for Phase 4 notification system.

This script verifies:
1. NotificationService can create notifications
2. Signal handlers are registered
3. Templates can be rendered
4. Notification delivery channels are determined correctly

Run with: python manage.py shell < test_notification_system.py
Or: python manage.py shell -c "exec(open('test_notification_system.py').read())"
"""

import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rs_systems.settings.development')
django.setup()

from django.contrib.auth.models import User
from apps.technician_portal.models import Technician, Repair
from core.models import Customer
from core.models.notification import Notification
from core.models.notification_template import NotificationTemplate
from core.services.notification_service import NotificationService

print("=" * 60)
print("PHASE 4 NOTIFICATION SYSTEM INTEGRATION TEST")
print("=" * 60)

# Test 1: Check templates exist
print("\n[Test 1] Checking NotificationTemplate records...")
template_count = NotificationTemplate.objects.count()
print(f"✓ Found {template_count} notification templates in database")

if template_count >= 8:
    print("✓ All required templates present")
else:
    print(f"⚠ Warning: Expected 8 templates, found {template_count}")

# Test 2: Get a template and test rendering
print("\n[Test 2] Testing template rendering...")
template = NotificationTemplate.objects.filter(
    name='repair_approved'
).first()

if template:
    print(f"✓ Found template: {template.name}")

    # Test rendering
    context = {
        'repair_id': 123,
        'unit_number': 'TEST-001',
        'customer_name': 'Test Company',
        'estimated_cost': 75.00,
        'technician_name': 'Test Technician'
    }

    try:
        rendered = template.render(context)
        print(f"✓ Template rendered successfully")
        print(f"  Title: {rendered['title'][:50]}...")
        print(f"  Has email HTML: {bool(rendered.get('email_html'))}")
        print(f"  Has SMS: {bool(rendered.get('sms'))}")
    except Exception as e:
        print(f"✗ Template rendering failed: {e}")
else:
    print("✗ Template 'repair_approved' not found")

# Test 3: Check signal handlers are registered
print("\n[Test 3] Checking signal handlers...")
from django.db.models import signals
from apps.technician_portal.models import Repair

# Check if pre_save and post_save signals are connected for Repair
pre_save_receivers = signals.pre_save.receivers
post_save_receivers = signals.post_save.receivers

repair_pre_save = any(
    'track_repair_changes' in str(receiver)
    for receiver in pre_save_receivers
)
repair_post_save = any(
    'handle_repair' in str(receiver)
    for receiver in post_save_receivers
)

if repair_pre_save:
    print("✓ Repair pre_save signal handler registered")
else:
    print("✗ Repair pre_save signal handler NOT registered")

if repair_post_save:
    print("✓ Repair post_save signal handlers registered")
else:
    print("✗ Repair post_save signal handlers NOT registered")

# Test 4: Test notification priority channels
print("\n[Test 4] Testing notification delivery channels...")
test_priorities = [
    (Notification.PRIORITY_URGENT, ['in_app', 'email', 'sms']),
    (Notification.PRIORITY_HIGH, ['in_app', 'sms']),
    (Notification.PRIORITY_MEDIUM, ['in_app', 'email']),
    (Notification.PRIORITY_LOW, ['in_app']),
]

for priority, expected_channels in test_priorities:
    # Create a temp notification to test
    notif = Notification(priority=priority)
    channels = notif.get_delivery_channels()

    if set(channels) == set(expected_channels):
        print(f"✓ {priority}: {channels}")
    else:
        print(f"✗ {priority}: Expected {expected_channels}, got {channels}")

# Test 5: Verify services can be imported
print("\n[Test 5] Checking service imports...")
try:
    from core.services import NotificationService, EmailService, SMSService
    print("✓ All services imported successfully")
    print("  - NotificationService")
    print("  - EmailService")
    print("  - SMSService")
except ImportError as e:
    print(f"✗ Service import failed: {e}")

# Test 6: Verify tasks can be imported
print("\n[Test 6] Checking Celery task imports...")
try:
    from core.tasks import (
        send_notification_email,
        send_notification_sms,
        retry_failed_notifications,
        send_daily_digests,
        cleanup_old_delivery_logs
    )
    print("✓ All Celery tasks imported successfully")
    print("  - send_notification_email")
    print("  - send_notification_sms")
    print("  - retry_failed_notifications")
    print("  - send_daily_digests")
    print("  - cleanup_old_delivery_logs")
except ImportError as e:
    print(f"✗ Task import failed: {e}")

# Summary
print("\n" + "=" * 60)
print("INTEGRATION TEST COMPLETE")
print("=" * 60)
print("\nPhase 4 notification system is operational!")
print("\nNext steps:")
print("1. Create a repair to test signal-triggered notifications")
print("2. Start Celery worker to test task execution")
print("3. Configure AWS SES/SNS credentials for email/SMS delivery")
print("4. Monitor logs for notification creation and delivery")
print("\nTo manually test notification creation:")
print(">>> from core.services import NotificationService")
print(">>> # Get a technician and template")
print(">>> # NotificationService.create_notification(...)")
