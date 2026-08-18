"""Fieldops S4: the customer's "request received" email has never been sent.

`Notification.get_delivery_channels()` compares `self.priority` against
`PRIORITY_URGENT`/`HIGH`/`MEDIUM`, which are the strings 'URGENT'/'HIGH'/
'MEDIUM'. Migration 0009 seeded the two customer-portal request templates
with **lowercase** values ('medium', 'high') — the only two rows in the whole
table that do. A lowercase priority matches no branch, so the channel list
falls through to `['in_app']` alone and the email is rendered and discarded.

Consequence, live since 0009: a customer submitting a repair request got an
in-app notification and no confirmation email, on every database seeded by
migrations (which is every fresh install, and production unless someone ran
`setup_notification_templates` by hand — the command has always had the
correct uppercase constants, which is why this survived unnoticed).

S4 echoes the customer's requested time back in that email rather than
opening a new customer-facing message stream, so the email actually needing
to send is a precondition of this session, not a drive-by.

`repair_request_submitted` is normalized here too — a value matching no
branch is simply broken — but its channels are deliberately left alone:
HIGH maps to ['in_app', 'sms'] and still excludes email (the N1 structural
bug), and whether the shop's "new request" notice should carry a
`channels_override` is N3's inventory decision, not this session's. SMS is
globally dark (`SMSService.is_enabled()` requires an origination identity
prod does not have), so nothing starts sending today either way.
"""

from django.db import migrations


def uppercase_priorities(apps, schema_editor):
    NotificationTemplate = apps.get_model('core', 'NotificationTemplate')
    for template in NotificationTemplate.objects.all():
        priority = template.default_priority or ''
        if priority and priority != priority.upper():
            NotificationTemplate.objects.filter(pk=template.pk).update(
                default_priority=priority.upper())

    # Any notification already written from a broken template keeps its
    # lowercase priority forever, which also breaks the bell's own filtering.
    Notification = apps.get_model('core', 'Notification')
    for value in ('urgent', 'high', 'medium', 'low'):
        Notification.objects.filter(priority=value).update(
            priority=value.upper())


def noop_reverse(apps, schema_editor):
    """Deliberately not reversible.

    Restoring the lowercase values would restore a bug, and there is no
    record of which rows were lowercase before this ran.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0030_job_rescheduled_covers_bookings'),
    ]

    operations = [
        migrations.RunPython(uppercase_priorities, noop_reverse),
    ]
