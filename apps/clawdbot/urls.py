"""
Clawdbot URL Configuration

Clawdbot-specific endpoints + billing proxy for backward compatibility.

Canonical billing API lives at /api/billing/
"""

from django.urls import path, include
from . import views

app_name = 'clawdbot'

urlpatterns = [
    # Clawdbot-specific endpoints
    path('', views.status, name='status'),
    path('health/', views.health, name='health'),
    path('customers/', views.list_customers, name='customers'),
    path('repairs/<int:customer_id>/', views.list_repairs, name='repairs'),
    
    # PDF generation (original clawdbot features)
    path('invoices/preview/<int:customer_id>/', views.invoice_preview, name='invoice_preview'),
    path('invoices/generate/<int:customer_id>/', views.generate_invoice, name='invoice_generate'),
    
    # Proxy billing endpoints for backward compatibility
    # Canonical home: /api/billing/
    path('billing/', include('apps.billing.urls')),
]
