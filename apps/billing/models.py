"""
Billing Models

Future home for:
- Invoice model (tracking generated invoices)
- InvoiceLineItem model
- Payment tracking

For now, invoice generation is stateless (generates PDFs on demand).
Models will be added when we need to track invoice history in the database.
"""

from django.db import models

# Models will be added here as billing features mature
# Example future models:
#
# class Invoice(models.Model):
#     customer = models.ForeignKey('core.Customer', on_delete=models.CASCADE)
#     invoice_number = models.CharField(max_length=50, unique=True)
#     invoice_date = models.DateField()
#     total = models.DecimalField(max_digits=10, decimal_places=2)
#     s3_key = models.CharField(max_length=255, blank=True)
#     emailed_at = models.DateTimeField(null=True, blank=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#
# class InvoiceLineItem(models.Model):
#     invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
#     repair = models.ForeignKey('technician_portal.Repair', on_delete=models.SET_NULL, null=True)
#     description = models.CharField(max_length=255)
#     amount = models.DecimalField(max_digits=10, decimal_places=2)
