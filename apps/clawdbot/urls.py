"""
Clawdbot URL Configuration

Amelia's experimental endpoints for RS Systems automation.
"""

from django.urls import path
from . import views

app_name = 'clawdbot'

urlpatterns = [
    # Status and health
    path('', views.status, name='status'),
    path('health/', views.health, name='health'),
    
    # Customer and repair data
    path('customers/', views.list_customers, name='customers'),
    path('repairs/<int:customer_id>/', views.list_repairs, name='repairs'),
    
    # Invoice generation
    path('invoices/preview/<int:customer_id>/', views.invoice_preview, name='invoice_preview'),
    path('invoices/generate/<int:customer_id>/', views.generate_invoice, name='invoice_generate'),
    path('invoices/email/<int:customer_id>/', views.send_invoice_email, name='invoice_email'),
    path('invoices/saved/', views.list_saved_invoices, name='invoices_saved'),
    path('invoices/download/<str:filename>/', views.download_saved_invoice, name='invoice_download'),
    
    # Customer invoice preferences (GET to read, POST to update)
    path('preferences/<int:customer_id>/', views.get_invoice_preferences, name='preferences_get'),
    path('preferences/<int:customer_id>/update/', views.update_invoice_preferences, name='preferences_update'),
    
    # Invoice tracking
    path('billing/invoices/', views.list_invoices, name='invoices_list'),
    path('billing/invoices/<int:invoice_id>/', views.get_invoice, name='invoice_detail'),
    path('billing/invoices/<int:invoice_id>/payment/', views.record_payment, name='invoice_payment'),
    path('billing/uninvoiced/<int:customer_id>/', views.get_uninvoiced_repairs, name='uninvoiced_repairs'),
    path('billing/balance/<int:customer_id>/', views.get_customer_balance, name='customer_balance'),
]
