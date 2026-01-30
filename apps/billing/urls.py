"""
Billing URL Configuration

These are the canonical billing API endpoints.
They live at /api/billing/ in the main URL config.

The /clawdbot/ namespace proxies to these for backward compatibility
during the experimental phase.

Author: Amelia (Clawdbot AI)
"""

from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    # Dashboard & Reports
    path('dashboard/', views.dashboard, name='dashboard'),
    path('reports/daily/', views.daily_report, name='daily_report'),
    path('reports/weekly/', views.weekly_report, name='weekly_report'),
    
    # Invoice CRUD
    path('invoices/', views.list_invoices, name='invoices_list'),
    path('invoices/create/<int:customer_id>/', views.create_invoice, name='invoice_create'),
    path('invoices/<int:invoice_id>/', views.get_invoice, name='invoice_detail'),
    path('invoices/<int:invoice_id>/payment/', views.record_payment, name='invoice_payment'),
    path('invoices/<int:invoice_id>/cancel/', views.cancel_invoice, name='invoice_cancel'),
    
    # Customer billing
    path('customers/<int:customer_id>/uninvoiced/', views.get_uninvoiced_repairs, name='uninvoiced_repairs'),
    path('customers/<int:customer_id>/balance/', views.get_customer_balance, name='customer_balance'),
    path('customers/<int:customer_id>/preferences/', views.get_invoice_preferences, name='preferences_get'),
    path('customers/<int:customer_id>/preferences/update/', views.update_invoice_preferences, name='preferences_update'),
    
    # Stripe (payment channel — not a duplicate invoicing system)
    path('stripe/status/', views.stripe_status, name='stripe_status'),
    path('stripe/checkout/<int:invoice_id>/', views.create_checkout_session, name='stripe_checkout'),
    path('stripe/payment-link/<int:invoice_id>/', views.create_payment_link, name='payment_link'),
    path('stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),
    
    # Reminders
    path('reminders/summary/', views.reminder_summary, name='reminder_summary'),
    path('reminders/send/<int:invoice_id>/', views.send_reminder, name='send_reminder'),
    path('reminders/process/', views.process_all_reminders, name='process_reminders'),
]
