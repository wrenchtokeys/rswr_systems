# H8 (help center wrap-up): the public form asks a visitor which shop they're
# with. Ported from PR #264, which built the public form in parallel with H2.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('support', '0004_guidefeedback_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='supportmessage',
            name='shop_name',
            field=models.CharField(
                blank=True, max_length=150,
                help_text='What a visitor typed as their shop; empty for signed-in senders',
            ),
        ),
    ]
