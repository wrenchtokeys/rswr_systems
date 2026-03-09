from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customer_portal', '0010_add_approval_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerinvitation',
            name='is_primary_contact',
            field=models.BooleanField(default=False, help_text='Set this user as the primary contact for the customer'),
        ),
    ]
