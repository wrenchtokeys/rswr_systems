"""
Management command for automated billing tasks.

Run daily via cron:
    python manage.py process_billing

Or specific tasks:
    python manage.py process_billing --overdue-check
    python manage.py process_billing --send-reminders
    python manage.py process_billing --batch-invoices
    python manage.py process_billing --daily-report

Author: Amelia (Clawdbot AI)
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
import json


class Command(BaseCommand):
    help = 'Run automated billing tasks (overdue check, reminders, batch invoicing)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--overdue-check',
            action='store_true',
            help='Mark overdue invoices',
        )
        parser.add_argument(
            '--send-reminders',
            action='store_true',
            help='Send payment reminders for due/overdue invoices',
        )
        parser.add_argument(
            '--batch-invoices',
            action='store_true',
            help='Generate batch invoices for customers with uninvoiced repairs',
        )
        parser.add_argument(
            '--daily-report',
            action='store_true',
            help='Generate and print daily report',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Run all tasks',
        )
    
    def handle(self, *args, **options):
        run_all = options['all']
        ran_something = False
        
        # If no specific flag, run all
        if not any([options['overdue_check'], options['send_reminders'],
                     options['batch_invoices'], options['daily_report']]):
            run_all = True
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"📋 Billing Processing - {timezone.now().strftime('%Y-%m-%d %H:%M')}")
        self.stdout.write(f"{'='*60}\n")
        
        # 1. Update overdue statuses
        if run_all or options['overdue_check']:
            ran_something = True
            self._check_overdue()
        
        # 2. Send reminders
        if run_all or options['send_reminders']:
            ran_something = True
            self._send_reminders()
        
        # 3. Batch invoice generation
        if run_all or options['batch_invoices']:
            ran_something = True
            self._batch_invoices()
        
        # 4. Daily report
        if run_all or options['daily_report']:
            ran_something = True
            self._daily_report()
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS('✅ Billing processing complete'))
        self.stdout.write(f"{'='*60}\n")
    
    def _get_active_tenants(self):
        """Return all active Tenant objects."""
        from apps.tenants.models import Tenant
        return Tenant.objects.filter(is_active=True)

    def _check_overdue(self):
        """Mark invoices as overdue if past due date — runs per tenant."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        
        self.stdout.write("\n📅 Checking for overdue invoices...")
        
        total_updated = 0
        for tenant in self._get_active_tenants():
            service = InvoiceTrackingService(tenant=tenant)
            updated = service.update_overdue_statuses()
            total_updated += updated
            if updated:
                self.stdout.write(f"   [{tenant.name}] ⚠️ {updated} invoice(s) marked OVERDUE")
        
        if total_updated:
            self.stdout.write(self.style.WARNING(f"   Total: {total_updated} invoice(s) marked OVERDUE"))
        else:
            self.stdout.write(self.style.SUCCESS("   ✅ No new overdue invoices"))
    
    def _send_reminders(self):
        """Send payment reminders — runs per tenant."""
        from apps.billing.services.reminder_service import ReminderService
        
        self.stdout.write("\n📧 Processing payment reminders...")
        
        total_sent = 0
        total_errors = 0
        
        for tenant in self._get_active_tenants():
            service = ReminderService(tenant=tenant)
            
            due_soon = service.process_due_soon_reminders()
            overdue = service.process_overdue_reminders()
            
            tenant_sent = due_soon['sent'] + overdue['sent']
            tenant_errors = due_soon['errors'] + overdue['errors']
            total_sent += tenant_sent
            total_errors += tenant_errors
            
            if tenant_sent:
                self.stdout.write(f"   [{tenant.name}] 📨 {tenant_sent} reminder(s) sent")
        
        if total_sent:
            self.stdout.write(self.style.SUCCESS(f"   Total: {total_sent} reminder(s) sent"))
        if total_errors:
            self.stdout.write(self.style.ERROR(f"   Total errors: {total_errors}"))
        if total_sent == 0 and total_errors == 0:
            self.stdout.write("   No reminders needed today")
    
    def _batch_invoices(self):
        """Generate invoices for batch customers with pending repairs — runs per tenant."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        from apps.customer_portal.models import CustomerRepairPreference
        
        self.stdout.write("\n📋 Checking batch invoice customers...")
        
        invoiced_count = 0
        
        for tenant in self._get_active_tenants():
            tracking = InvoiceTrackingService(tenant=tenant)
            
            # Find batch customers with uninvoiced repairs for THIS tenant
            batch_prefs = CustomerRepairPreference.objects.filter(
                invoice_preference='batch',
                customer__tenant=tenant,
            ).select_related('customer')
            
            for pref in batch_prefs:
                uninvoiced = list(tracking.get_uninvoiced_repairs(pref.customer))
                uninvoiced.extend(tracking.get_uninvoiced_replacements(pref.customer))

                if len(uninvoiced) >= 10:  # Auto-batch at 10+ jobs
                    try:
                        # CODE-096: Always create as DRAFT; attempt email and only
                        # mark SENT on confirmed delivery (AGENTS.md gotcha).
                        invoice = tracking.create_invoice_from_services(
                            customer=pref.customer,
                            services=uninvoiced,
                        )
                        invoiced_count += 1

                        # Attempt to email the invoice if customer has an email
                        emailed = False
                        email_note = ''
                        if pref.customer.email:
                            try:
                                from apps.billing.services.invoice_email_service import InvoiceEmailService
                                email_svc = InvoiceEmailService(tenant=tenant)
                                success, msg = email_svc.send_invoice_email(
                                    customer_id=pref.customer.id,
                                    recipient_email=pref.customer.email,
                                    invoice=invoice,
                                )
                                if success:
                                    invoice.record_email_sent(pref.customer.email)
                                    emailed = True
                                    email_note = ' ✉️ emailed'
                                else:
                                    email_note = f' ⚠️ email failed: {msg}'
                            except Exception as email_exc:
                                email_note = f' ⚠️ email error: {email_exc}'
                        else:
                            email_note = ' (no email on file)'

                        self.stdout.write(
                            f"   [{tenant.name}] 📄 {pref.customer.name}: "
                            f"{len(uninvoiced)} jobs → {invoice.invoice_number} (${invoice.total}){email_note}"
                        )
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(
                            f"   [{tenant.name}] ❌ {pref.customer.name}: Error - {e}"
                        ))
                elif len(uninvoiced) > 0:
                    self.stdout.write(
                        f"   [{tenant.name}] ⏳ {pref.customer.name}: {len(uninvoiced)} jobs waiting "
                        f"(threshold: 10)"
                    )
        
        if invoiced_count == 0:
            self.stdout.write("   No batch invoices generated")
    
    def _daily_report(self):
        """Print daily report summary — runs per tenant."""
        from apps.billing.services.report_service import ReportService
        
        self.stdout.write("\n📊 Daily Report...")
        
        for tenant in self._get_active_tenants():
            service = ReportService(tenant=tenant)
            report = service.generate_daily_report(timezone.localdate())
            
            self.stdout.write(f"\n  [{tenant.name}] {report['summary']}")
            self.stdout.write(
                f"   Outstanding: ${report['outstanding']['total']:,.2f} "
                f"({report['outstanding']['count']} invoices)"
            )
            
            if report['overdue']['count'] > 0:
                self.stdout.write(self.style.WARNING(
                    f"   Overdue: ${report['overdue']['total']:,.2f} "
                    f"({report['overdue']['count']} invoices)"
                ))
