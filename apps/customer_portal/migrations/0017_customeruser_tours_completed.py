from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customer_portal', '0016_customeruser_deactivated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='customeruser',
            name='tours_completed',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
