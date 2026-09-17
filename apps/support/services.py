"""
The support loop, in one place (HELP_CENTER_SESSIONS H2/H5).

Both contact forms — the signed-in one at /help/contact/ and the public one at
/contact/ — call submit_support_message(). A prospect's question and a shop's
question go to the same person and get the same reply, so they share one
record, one admin page and one sweep.

Record-first is the rule: the SupportMessage row is saved BEFORE any email is
attempted, so an SES outage cannot lose a cry for help. Rows whose admin
notification failed carry emailed_ok=False and are re-sent by
`manage.py sweep_support_messages`.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage

from core.email_utils import send_branded_email

from .models import SupportMessage

logger = logging.getLogger(__name__)

ACK_SUBJECT = 'We got your message'


def admin_notification(record):
    """The EmailMessage that tells the admins a message arrived.

    Reply-To is the sender, so answering from the inbox answers them
    directly. Built separately from the send so the sweep can rebuild it
    for a row whose first attempt failed.
    """
    tenant = record.tenant
    shop = tenant.name if tenant else '(no shop — public form)' if record.source == 'public' else '(no tenant)'
    body = (
        f"From: {record.name} <{record.email}>\n"
        f"Shop: {shop}\n"
        f"Role: {record.role or 'unknown'}\n"
        f"Topic: {record.get_topic_display()}\n"
        f"Page: {record.page or '(not recorded)'}\n\n"
        f"{record.message}\n\n"
        f"—\nReply to this email to answer them directly. "
        f"Admin: {settings.BASE_URL}/admin/support/supportmessage/{record.pk}/change/"
    )
    who = tenant.name if tenant else record.name or record.email
    return EmailMessage(
        subject=f"Support: {record.get_topic_display()} — {who}",
        body=body,
        to=[addr for _name, addr in settings.ADMINS],
        reply_to=[record.email],
    )


def notify_admins(record):
    """Send the admin notification and stamp the row. Never raises."""
    try:
        admin_notification(record).send()
        record.emailed_ok = True
        record.save(update_fields=['emailed_ok'])
        return True
    except Exception:
        # Row is already saved — the sweep catches emailed_ok=False.
        logger.exception('Support notification email failed (message #%s)', record.pk)
        return False


def acknowledgement_kwargs(record):
    """The send_branded_email() kwargs for the sender's acknowledgement.

    Separate from the send so `manage.py preview_emails` renders exactly
    what a sender gets. RS Systems talking, not a shop — platform branding,
    no shop colour. Plain subject: no brackets, no emoji
    (docs/operations/SES_OPERATIONS.md).
    """
    return dict(
        subject=ACK_SUBJECT,
        recipient_list=[record.email],
        headline='Got it — your message is in',
        body_paragraphs=[
            f"Hi {record.first_name or 'there'},",
            "A real person will read your message and reply to this address. "
            "Replies usually come the same business day.",
            "Here is what you sent us, for your records:",
            record.message,
        ],
        platform=True,
        lede='No bots, no ticket numbers.',
        note='If you did not send this, you can ignore it — nothing was changed on any account.',
    )


def send_acknowledgement(record):
    """Tell the sender their message arrived. Never raises."""
    try:
        send_branded_email(**acknowledgement_kwargs(record))
        record.acknowledged = True
        record.save(update_fields=['acknowledged'])
        return True
    except Exception:
        logger.exception('Support acknowledgement email failed (message #%s)', record.pk)
        return False


def submit_support_message(*, tenant, user, name, email, topic, message, page='', source='app', role=''):
    """Save the message, then notify — in that order.

    Returns the SupportMessage. Email failures are logged and reflected on
    the row (emailed_ok / acknowledged); they never fail the request.
    """
    if topic not in dict(SupportMessage.TOPIC_CHOICES):
        topic = 'question'
    record = SupportMessage.objects.create(
        tenant=tenant,
        user=user,
        name=(name or '').strip()[:150],
        email=email,
        topic=topic,
        message=message,
        page=(page or '')[:500],
        source=source,
        role=(role or '')[:20],
    )
    notify_admins(record)
    send_acknowledgement(record)
    return record
