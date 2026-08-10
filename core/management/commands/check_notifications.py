from django.core.management.base import BaseCommand
from apps.technician_portal.models import Technician, Repair
from core.models import (
    TechnicianNotificationPreference,
    Customer,
    CustomerNotificationPreference,
    Notification,
    NotificationDeliveryLog
)
from django.contrib.contenttypes.models import ContentType


class Command(BaseCommand):
    help = 'Check notification system status and debug issues'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('\n=== NOTIFICATION SYSTEM DIAGNOSTIC ===\n'))

        # 1. Check Technician Email Verification
        self.stdout.write(self.style.WARNING('1. TECHNICIAN EMAIL VERIFICATION:'))
        techs = Technician.objects.all()
        for tech in techs:
            try:
                prefs = TechnicianNotificationPreference.objects.get(technician=tech)
                status = '✓' if prefs.can_send_email() else '✗'
                self.stdout.write(
                    f'{status} {tech.user.email}: '
                    f'email_verified={prefs.email_verified}, '
                    f'can_send={prefs.can_send_email()}'
                )
            except TechnicianNotificationPreference.DoesNotExist:
                self.stdout.write(f'✗ {tech.user.email}: NO PREFERENCES!')

        # 2. Check Customer Email Verification
        self.stdout.write(self.style.WARNING('\n2. CUSTOMER EMAIL VERIFICATION:'))
        customers = Customer.objects.all()
        for customer in customers:
            try:
                prefs = CustomerNotificationPreference.objects.get(customer=customer)
                status = '✓' if prefs.can_send_email() else '✗'
                self.stdout.write(
                    f'{status} {customer.email}: '
                    f'email_verified={prefs.email_verified}, '
                    f'can_send={prefs.can_send_email()}'
                )
            except CustomerNotificationPreference.DoesNotExist:
                self.stdout.write(f'✗ {customer.email}: NO PREFERENCES!')

        # 3. Check Recent Notifications Created
        self.stdout.write(self.style.WARNING('\n3. RECENT NOTIFICATIONS (Last 10):'))
        notifications = Notification.objects.all().order_by('-created_at')[:10]
        if notifications:
            for notif in notifications:
                self.stdout.write(
                    f'  [{notif.created_at}] {notif.category}: '
                    f'{notif.title} - read={notif.read}'
                )
        else:
            self.stdout.write('  No notifications found in database!')

        # 4. Check Recent Repairs
        self.stdout.write(self.style.WARNING('\n4. RECENT REPAIRS (Last 5):'))
        repairs = Repair.objects.all().order_by('-service_date')[:5]
        for repair in repairs:
            self.stdout.write(
                f'  Repair #{repair.id}: {repair.queue_status} '
                f'(date: {repair.service_date}, customer: {repair.customer.name})'
            )

        # 5. Delivery mode
        self.stdout.write(self.style.WARNING('\n5. DELIVERY MODE:'))
        self.stdout.write('  Notifications are delivered synchronously (no Celery/Redis required).')
        self.stdout.write('  Batch billing tasks run via management commands (cron).')

        # 6. Check Email Configuration
        self.stdout.write(self.style.WARNING('\n6. EMAIL CONFIGURATION:'))
        from django.conf import settings
        self.stdout.write(f'  EMAIL_BACKEND: {settings.EMAIL_BACKEND}')
        self.stdout.write(f'  EMAIL_HOST: {settings.EMAIL_HOST}')
        self.stdout.write(f'  DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}')

        # 7. Check Recent Delivery Logs
        self.stdout.write(self.style.WARNING('\n7. RECENT DELIVERY LOGS (Last 10):'))
        delivery_logs = NotificationDeliveryLog.objects.all().order_by('-created_at')[:10]
        if delivery_logs:
            for log in delivery_logs:
                self.stdout.write(
                    f'  [{log.created_at}] {log.channel} to {log.recipient_email or log.recipient_phone}: '
                    f'status={log.status}, attempts={log.attempt_number}'
                )
        else:
            self.stdout.write('  No delivery logs found - emails may not be queued!')

        # Summary
        verified_techs = TechnicianNotificationPreference.objects.filter(email_verified=True).count()
        verified_customers = CustomerNotificationPreference.objects.filter(email_verified=True).count()
        total_notifications = Notification.objects.count()

        self.stdout.write(self.style.SUCCESS('\n=== SUMMARY ==='))
        self.stdout.write(f'Verified Technicians: {verified_techs}/{techs.count()}')
        self.stdout.write(f'Verified Customers: {verified_customers}/{customers.count()}')
        self.stdout.write(f'Total Notifications: {total_notifications}')
