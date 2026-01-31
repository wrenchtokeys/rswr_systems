"""
Add BillingConfig singleton and payment_terms to Invoice.

BillingConfig stores company address (for invoices), default payment terms,
and invoice defaults. Configurable via Admin Dashboard.

Invoice.payment_terms defaults to 'COD' (Cash on Delivery).

Author: Amelia (Clawdbot AI)
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_alter_invoicelineitem_repair'),
    ]

    operations = [
        # 1. Create BillingConfig singleton
        migrations.CreateModel(
            name='BillingConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton_id', models.BooleanField(default=True, editable=False, unique=True)),
                # Company info
                ('company_name', models.CharField(default='Rockstar Windshield Repair', help_text='Company name displayed on invoices', max_length=200)),
                ('company_address', models.CharField(blank=True, help_text='Street address (e.g., 123 Main St)', max_length=200)),
                ('company_city', models.CharField(blank=True, help_text='City', max_length=100)),
                ('company_state', models.CharField(blank=True, help_text='State (e.g., TX)', max_length=50)),
                ('company_zip', models.CharField(blank=True, help_text='ZIP / Postal code', max_length=20)),
                ('company_phone', models.CharField(blank=True, help_text='Phone number shown on invoices', max_length=30)),
                ('company_email', models.EmailField(blank=True, help_text='Email shown on invoices', max_length=254)),
                ('company_website', models.URLField(blank=True, help_text='Website URL shown on invoices')),
                # Payment terms
                ('default_payment_terms', models.CharField(
                    choices=[
                        ('COD', 'Cash on Delivery (COD)'),
                        ('DUE_ON_RECEIPT', 'Due on Receipt'),
                        ('NET15', 'Net 15'),
                        ('NET30', 'Net 30'),
                        ('NET45', 'Net 45'),
                        ('NET60', 'Net 60'),
                    ],
                    default='COD',
                    help_text='Default payment terms for new invoices',
                    max_length=20,
                )),
                ('default_due_days', models.PositiveIntegerField(
                    default=0,
                    help_text='Default days until invoice is due (0 = due on receipt/COD). Overridden by payment terms if set.',
                )),
                # Invoice defaults
                ('invoice_footer_note', models.TextField(blank=True, default='Thank you for your business!', help_text='Footer text printed at the bottom of every invoice')),
                ('invoice_number_prefix', models.CharField(default='INV', help_text='Prefix for auto-generated invoice numbers', max_length=20)),
                # Timestamps
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Billing Configuration',
                'verbose_name_plural': 'Billing Configuration',
            },
        ),
        # 2. Add payment_terms to Invoice
        migrations.AddField(
            model_name='invoice',
            name='payment_terms',
            field=models.CharField(
                choices=[
                    ('COD', 'Cash on Delivery (COD)'),
                    ('DUE_ON_RECEIPT', 'Due on Receipt'),
                    ('NET15', 'Net 15'),
                    ('NET30', 'Net 30'),
                    ('NET45', 'Net 45'),
                    ('NET60', 'Net 60'),
                ],
                default='COD',
                help_text='Payment terms for this invoice',
                max_length=20,
            ),
        ),
    ]
