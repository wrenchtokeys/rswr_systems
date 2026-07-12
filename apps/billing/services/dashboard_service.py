"""
Billing Dashboard Service - Real-time business metrics and insights.

Provides:
- Revenue metrics (today, week, month, year)
- Outstanding invoice tracking
- Payment velocity
- Customer insights
- Trend analysis

Author: Amelia (Clawdbot AI)
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict
from django.utils import timezone
from django.db.models import Sum, Count, Avg, F, Q
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth

logger = logging.getLogger(__name__)


class DashboardService:
    """
    Generates real-time dashboard metrics for the billing system.
    All queries are scoped to a tenant for data isolation.
    """
    
    def __init__(self, tenant=None):
        self.tenant = tenant
    
    def _filter(self, qs):
        """Apply tenant filter to any queryset."""
        if self.tenant:
            return qs.filter(tenant=self.tenant)
        return qs.none()

    def _filter_payment(self, qs):
        """
        Apply tenant filter to a Payment queryset.

        Payment has no direct tenant FK — the path is Payment → Invoice → Tenant.
        Using _filter() (which does filter(tenant=…)) on Payment.objects raises
        FieldError: Cannot resolve keyword 'tenant' into field.  (CODE-190)
        """
        if self.tenant:
            return qs.filter(invoice__tenant=self.tenant)
        return qs.none()
    
    def get_full_dashboard(self):
        """
        Get complete dashboard data.
        
        Returns:
            dict: Full dashboard with all metrics
        """
        return {
            'generated_at': timezone.now().isoformat(),
            'revenue': self.get_revenue_metrics(),
            'invoices': self.get_invoice_metrics(),
            'payments': self.get_payment_metrics(),
            'customers': self.get_customer_metrics(),
            'alerts': self.get_alerts(),
            'trends': self.get_trends(),
        }
    
    def get_revenue_metrics(self):
        """
        Calculate revenue metrics across different time periods.
        """
        from apps.billing.models import Payment
        
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = today_start.replace(day=1)
        year_start = today_start.replace(month=1, day=1)
        
        # Previous periods for comparison
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
        prev_month_end = month_start - timedelta(seconds=1)
        
        def sum_payments(start, end=None):
            qs = self._filter_payment(Payment.objects).filter(payment_date__gte=start.date())
            if end:
                qs = qs.filter(payment_date__lte=end.date())
            result = qs.aggregate(total=Sum('amount'))['total']
            return float(result) if result else 0.0
        
        this_month = sum_payments(month_start)
        last_month = sum_payments(prev_month_start, prev_month_end)
        
        # Calculate growth percentage
        if last_month > 0:
            month_growth = ((this_month - last_month) / last_month) * 100
        else:
            month_growth = 100.0 if this_month > 0 else 0.0
        
        return {
            'today': sum_payments(today_start),
            'this_week': sum_payments(week_start),
            'this_month': this_month,
            'last_month': last_month,
            'this_year': sum_payments(year_start),
            'month_over_month_growth': round(month_growth, 1),
        }
    
    def get_invoice_metrics(self):
        """
        Calculate invoice-related metrics.
        """
        from apps.billing.models import Invoice
        
        invoices = self._filter(Invoice.objects).exclude(status='CANCELLED')
        
        # Counts by status
        status_counts = dict(
            invoices.values('status').annotate(count=Count('id')).values_list('status', 'count')
        )
        
        # Amounts
        outstanding = invoices.filter(
            status__in=['SENT', 'PARTIAL', 'OVERDUE']
        ).aggregate(
            total=Sum(F('total') - F('amount_paid')),
            count=Count('id')
        )
        
        overdue = invoices.filter(status='OVERDUE').aggregate(
            total=Sum(F('total') - F('amount_paid')),
            count=Count('id')
        )
        
        # Average days to pay (for PAID invoices)
        paid_invoices = invoices.filter(status='PAID', sent_at__isnull=False, paid_at__isnull=False)
        avg_days = None
        if paid_invoices.exists():
            total_days = sum(
                (inv.paid_at - inv.sent_at).days 
                for inv in paid_invoices 
                if inv.paid_at and inv.sent_at
            )
            avg_days = total_days / paid_invoices.count() if paid_invoices.count() > 0 else None
        
        return {
            'total_count': invoices.count(),
            'by_status': {
                'draft': status_counts.get('DRAFT', 0),
                'sent': status_counts.get('SENT', 0),
                'partial': status_counts.get('PARTIAL', 0),
                'paid': status_counts.get('PAID', 0),
                'overdue': status_counts.get('OVERDUE', 0),
            },
            'outstanding': {
                'amount': float(outstanding['total'] or 0),
                'count': outstanding['count'] or 0,
            },
            'overdue': {
                'amount': float(overdue['total'] or 0),
                'count': overdue['count'] or 0,
            },
            'average_days_to_pay': round(avg_days, 1) if avg_days else None,
        }
    
    def get_payment_metrics(self):
        """
        Calculate payment-related metrics.
        """
        from apps.billing.models import Payment
        
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)
        
        recent_payments = self._filter_payment(Payment.objects).filter(
            payment_date__gte=thirty_days_ago.date()
        )
        
        # By method
        by_method = dict(
            recent_payments.values('payment_method').annotate(
                total=Sum('amount'),
                count=Count('id')
            ).values_list('payment_method', 'total')
        )
        
        # Recent payments list
        latest = self._filter_payment(Payment.objects).select_related('invoice', 'invoice__customer').order_by('-created_at')[:10]
        latest_list = [
            {
                'id': p.id,
                'amount': float(p.amount),
                'date': p.payment_date.isoformat(),
                'method': p.payment_method,
                'invoice_number': p.invoice.invoice_number,
                'customer': p.invoice.customer.name,
            }
            for p in latest
        ]
        
        return {
            'last_30_days': {
                'total': float(recent_payments.aggregate(Sum('amount'))['amount__sum'] or 0),
                'count': recent_payments.count(),
            },
            'by_method': {k: float(v) for k, v in by_method.items()},
            'recent': latest_list,
        }
    
    def get_customer_metrics(self):
        """
        Calculate customer-related billing metrics.
        """
        from apps.billing.models import Invoice
        from core.models import Customer
        
        # Customers with outstanding balances
        outstanding_by_customer = self._filter(Invoice.objects).filter(
            status__in=['SENT', 'PARTIAL', 'OVERDUE']
        ).values('customer__id', 'customer__name').annotate(
            outstanding=Sum(F('total') - F('amount_paid')),
            invoice_count=Count('id')
        ).order_by('-outstanding')[:10]
        
        top_outstanding = [
            {
                'id': c['customer__id'],
                'name': c['customer__name'],
                'outstanding': float(c['outstanding']),
                'invoice_count': c['invoice_count'],
            }
            for c in outstanding_by_customer
        ]
        
        # Top customers by revenue (all time)
        top_revenue = self._filter(Invoice.objects).filter(
            status='PAID'
        ).values('customer__id', 'customer__name').annotate(
            total_paid=Sum('amount_paid')
        ).order_by('-total_paid')[:10]
        
        top_revenue_list = [
            {
                'id': c['customer__id'],
                'name': c['customer__name'],
                'total_paid': float(c['total_paid']),
            }
            for c in top_revenue
        ]
        
        return {
            'with_outstanding_balance': len(top_outstanding),
            'top_outstanding': top_outstanding,
            'top_revenue': top_revenue_list,
        }
    
    def get_alerts(self):
        """
        Generate actionable alerts.
        """
        from apps.billing.models import Invoice
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        
        alerts = []
        
        # Overdue invoices
        overdue = self._filter(Invoice.objects).filter(status='OVERDUE')
        if overdue.exists():
            total_overdue = sum(inv.amount_due for inv in overdue)
            alerts.append({
                'type': 'overdue',
                'severity': 'high',
                'message': f"{overdue.count()} overdue invoice(s) totaling ${total_overdue:,.2f}",
                'count': overdue.count(),
                'amount': float(total_overdue),
            })
        
        # Invoices due soon (next 7 days)
        now = timezone.localdate()
        due_soon = self._filter(Invoice.objects).filter(
            status__in=['SENT', 'PARTIAL'],
            due_date__gte=now,
            due_date__lte=now + timedelta(days=7)
        )
        if due_soon.exists():
            total_due_soon = sum(inv.amount_due for inv in due_soon)
            alerts.append({
                'type': 'due_soon',
                'severity': 'medium',
                'message': f"{due_soon.count()} invoice(s) due in next 7 days (${total_due_soon:,.2f})",
                'count': due_soon.count(),
                'amount': float(total_due_soon),
            })
        
        # Large outstanding single invoice (> $500)
        large_outstanding = self._filter(Invoice.objects).filter(
            status__in=['SENT', 'PARTIAL', 'OVERDUE']
        ).annotate(
            due=F('total') - F('amount_paid')
        ).filter(due__gte=500).order_by('-due')[:5]
        
        for inv in large_outstanding:
            alerts.append({
                'type': 'large_invoice',
                'severity': 'info',
                'message': f"Large invoice {inv.invoice_number}: ${inv.amount_due:,.2f} outstanding ({inv.customer.name})",
                'invoice_id': inv.id,
                'amount': float(inv.amount_due),
            })
        
        # Uninvoiced completed repairs (batch customers)
        tracking = InvoiceTrackingService(tenant=self.tenant)
        from core.models import Customer
        from apps.customer_portal.models import CustomerRepairPreference
        
        if self.tenant:
            batch_prefs_qs = CustomerRepairPreference.objects.filter(
                invoice_preference='batch',
                customer__tenant=self.tenant,
            ).select_related('customer')
        else:
            batch_prefs_qs = CustomerRepairPreference.objects.none()
        batch_customers = batch_prefs_qs
        
        for pref in batch_customers:
            uninvoiced = tracking.get_uninvoiced_repairs(pref.customer)
            if uninvoiced.count() >= 5:  # Alert if 5+ repairs waiting
                total_value = sum(r.get_discounted_cost()['final_cost'] for r in uninvoiced)
                alerts.append({
                    'type': 'uninvoiced_repairs',
                    'severity': 'info',
                    'message': f"{pref.customer.name} has {uninvoiced.count()} uninvoiced repairs (${total_value:,.2f})",
                    'customer_id': pref.customer.id,
                    'count': uninvoiced.count(),
                    'amount': float(total_value),
                })
        
        return sorted(alerts, key=lambda x: {'high': 0, 'medium': 1, 'info': 2}[x['severity']])
    
    def get_trends(self):
        """
        Calculate trend data for charts.
        """
        from apps.billing.models import Payment, Invoice
        
        now = timezone.now()
        
        # Daily revenue for last 30 days
        thirty_days_ago = now - timedelta(days=30)
        daily_revenue = self._filter_payment(Payment.objects).filter(
            payment_date__gte=thirty_days_ago.date()
        ).annotate(
            day=TruncDate('payment_date')
        ).values('day').annotate(
            total=Sum('amount')
        ).order_by('day')
        
        daily_data = [
            {'date': d['day'].isoformat(), 'amount': float(d['total'])}
            for d in daily_revenue
        ]
        
        # Weekly invoice count for last 12 weeks
        twelve_weeks_ago = now - timedelta(weeks=12)
        weekly_invoices = self._filter(Invoice.objects).filter(
            created_at__gte=twelve_weeks_ago
        ).annotate(
            week=TruncWeek('created_at')
        ).values('week').annotate(
            count=Count('id'),
            total=Sum('total')
        ).order_by('week')
        
        weekly_data = [
            {
                'week': w['week'].isoformat(),
                'count': w['count'],
                'total': float(w['total']) if w['total'] else 0
            }
            for w in weekly_invoices
        ]
        
        return {
            'daily_revenue_30d': daily_data,
            'weekly_invoices_12w': weekly_data,
        }
