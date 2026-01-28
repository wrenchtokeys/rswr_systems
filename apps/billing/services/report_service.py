"""
Report Service - Generates daily and weekly business reports.

Provides:
- Daily summaries (repairs, invoices, payments)
- Weekly reports with trends
- Comparison to previous periods
- Email-ready formatting

Author: Amelia (Clawdbot AI)
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Count, Avg, F

logger = logging.getLogger(__name__)


class ReportService:
    """
    Generates business reports for different time periods.
    """
    
    def generate_daily_report(self, report_date):
        """
        Generate a daily report for a specific date.
        
        Args:
            report_date: date object for the report
            
        Returns:
            dict: Complete daily report
        """
        from apps.billing.models import Invoice, Payment
        from apps.technician_portal.models import Repair
        
        # Date range for the report day
        day_start = datetime.combine(report_date, datetime.min.time())
        day_end = datetime.combine(report_date, datetime.max.time())
        
        # Previous day for comparison
        prev_date = report_date - timedelta(days=1)
        
        # Repairs completed
        repairs_completed = Repair.objects.filter(
            queue_status='COMPLETED',
            repair_date__date=report_date
        )
        repair_count = repairs_completed.count()
        repair_revenue = sum(r.cost for r in repairs_completed)
        
        prev_repairs = Repair.objects.filter(
            queue_status='COMPLETED',
            repair_date__date=prev_date
        ).count()
        
        # Invoices created
        invoices_created = Invoice.objects.filter(
            invoice_date=report_date
        )
        invoice_count = invoices_created.count()
        invoice_total = invoices_created.aggregate(Sum('total'))['total__sum'] or Decimal('0')
        
        # Payments received
        payments = Payment.objects.filter(payment_date=report_date)
        payment_count = payments.count()
        payment_total = payments.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        
        prev_payments = Payment.objects.filter(
            payment_date=prev_date
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        
        # Payment breakdown by method
        payment_by_method = {}
        for p in payments:
            method = p.get_payment_method_display()
            if method not in payment_by_method:
                payment_by_method[method] = {'count': 0, 'total': 0}
            payment_by_method[method]['count'] += 1
            payment_by_method[method]['total'] += float(p.amount)
        
        # Outstanding snapshot
        outstanding = Invoice.objects.filter(
            status__in=['SENT', 'PARTIAL', 'OVERDUE']
        ).aggregate(
            total=Sum(F('total') - F('amount_paid')),
            count=Count('id')
        )
        
        overdue = Invoice.objects.filter(status='OVERDUE').aggregate(
            total=Sum(F('total') - F('amount_paid')),
            count=Count('id')
        )
        
        # Calculate changes
        payment_change = float(payment_total) - float(prev_payments)
        repair_change = repair_count - prev_repairs
        
        return {
            'report_type': 'daily',
            'date': report_date.isoformat(),
            'generated_at': timezone.now().isoformat(),
            
            'repairs': {
                'completed': repair_count,
                'revenue': float(repair_revenue),
                'change_from_yesterday': repair_change,
            },
            
            'invoices': {
                'created': invoice_count,
                'total': float(invoice_total),
            },
            
            'payments': {
                'received': payment_count,
                'total': float(payment_total),
                'change_from_yesterday': payment_change,
                'by_method': payment_by_method,
            },
            
            'outstanding': {
                'total': float(outstanding['total'] or 0),
                'count': outstanding['count'] or 0,
            },
            
            'overdue': {
                'total': float(overdue['total'] or 0),
                'count': overdue['count'] or 0,
            },
            
            'summary': self._generate_daily_summary(
                report_date, repair_count, float(payment_total), 
                float(outstanding['total'] or 0), overdue['count'] or 0
            ),
        }
    
    def generate_weekly_report(self, week_start):
        """
        Generate a weekly report starting from a specific date.
        
        Args:
            week_start: date object for the start of the week (Monday)
            
        Returns:
            dict: Complete weekly report
        """
        from apps.billing.models import Invoice, Payment
        from apps.technician_portal.models import Repair
        
        week_end = week_start + timedelta(days=6)
        
        # Previous week for comparison
        prev_week_start = week_start - timedelta(days=7)
        prev_week_end = week_start - timedelta(days=1)
        
        # Repairs
        repairs = Repair.objects.filter(
            queue_status='COMPLETED',
            repair_date__date__gte=week_start,
            repair_date__date__lte=week_end
        )
        repair_count = repairs.count()
        repair_revenue = sum(r.cost for r in repairs)
        
        prev_repairs = Repair.objects.filter(
            queue_status='COMPLETED',
            repair_date__date__gte=prev_week_start,
            repair_date__date__lte=prev_week_end
        ).count()
        
        # Invoices
        invoices = Invoice.objects.filter(
            invoice_date__gte=week_start,
            invoice_date__lte=week_end
        )
        invoice_count = invoices.count()
        invoice_total = invoices.aggregate(Sum('total'))['total__sum'] or Decimal('0')
        
        # Payments
        payments = Payment.objects.filter(
            payment_date__gte=week_start,
            payment_date__lte=week_end
        )
        payment_total = payments.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        
        prev_payments = Payment.objects.filter(
            payment_date__gte=prev_week_start,
            payment_date__lte=prev_week_end
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        
        # Daily breakdown
        daily_breakdown = []
        for i in range(7):
            day = week_start + timedelta(days=i)
            day_repairs = repairs.filter(repair_date__date=day).count()
            day_payments = payments.filter(payment_date=day).aggregate(
                Sum('amount')
            )['amount__sum'] or Decimal('0')
            
            daily_breakdown.append({
                'date': day.isoformat(),
                'day_name': day.strftime('%A'),
                'repairs': day_repairs,
                'payments': float(day_payments),
            })
        
        # Top customers this week
        top_customers = payments.values(
            'invoice__customer__id', 'invoice__customer__name'
        ).annotate(
            total=Sum('amount')
        ).order_by('-total')[:5]
        
        top_customer_list = [
            {
                'id': c['invoice__customer__id'],
                'name': c['invoice__customer__name'],
                'paid': float(c['total']),
            }
            for c in top_customers
        ]
        
        # Calculate week-over-week changes
        if float(prev_payments) > 0:
            payment_growth = ((float(payment_total) - float(prev_payments)) / float(prev_payments)) * 100
        else:
            payment_growth = 100.0 if float(payment_total) > 0 else 0.0
        
        repair_growth = ((repair_count - prev_repairs) / prev_repairs * 100) if prev_repairs > 0 else 0
        
        return {
            'report_type': 'weekly',
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'generated_at': timezone.now().isoformat(),
            
            'repairs': {
                'total': repair_count,
                'revenue': float(repair_revenue),
                'previous_week': prev_repairs,
                'growth_percent': round(repair_growth, 1),
            },
            
            'invoices': {
                'created': invoice_count,
                'total': float(invoice_total),
            },
            
            'payments': {
                'total': float(payment_total),
                'previous_week': float(prev_payments),
                'growth_percent': round(payment_growth, 1),
            },
            
            'daily_breakdown': daily_breakdown,
            'top_customers': top_customer_list,
            
            'summary': self._generate_weekly_summary(
                week_start, week_end, repair_count, float(payment_total),
                payment_growth, repair_growth
            ),
        }
    
    def _generate_daily_summary(self, date, repairs, payments, outstanding, overdue_count):
        """Generate a human-readable daily summary."""
        lines = [
            f"📊 Daily Report for {date.strftime('%B %d, %Y')}",
            "",
            f"🔧 Repairs completed: {repairs}",
            f"💰 Payments received: ${payments:,.2f}",
            f"📋 Outstanding invoices: ${outstanding:,.2f}",
        ]
        
        if overdue_count > 0:
            lines.append(f"⚠️ Overdue invoices: {overdue_count}")
        
        return "\n".join(lines)
    
    def _generate_weekly_summary(self, start, end, repairs, payments, payment_growth, repair_growth):
        """Generate a human-readable weekly summary."""
        growth_emoji = "📈" if payment_growth >= 0 else "📉"
        repair_emoji = "📈" if repair_growth >= 0 else "📉"
        
        lines = [
            f"📊 Weekly Report: {start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}",
            "",
            f"🔧 Repairs: {repairs} {repair_emoji} ({repair_growth:+.1f}% vs last week)",
            f"💰 Payments: ${payments:,.2f} {growth_emoji} ({payment_growth:+.1f}% vs last week)",
        ]
        
        return "\n".join(lines)
