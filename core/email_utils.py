"""
Shared HTML email builder for RS Systems.

All outgoing emails should use `send_branded_email()` to get consistent
branding with the nice invoice-style HTML template.
"""
import logging
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def shop_sender(shop_name=None, reply_to_email=None):
    """
    Build (from_email, reply_to) for shop-branded email.

    Mail is always sent through the platform's SES-verified address —
    sending from a shop's own domain would fail SPF/DKIM — but the From
    header shows the shop's name and replies route to the shop's email.

    The display name is "<Shop> via RS Systems" (the Stripe/Xero pattern):
    a bare third-party name over a platform address reads as display-name
    spoofing to corporate mail gateways and gets quarantined.

    Returns:
        tuple: (from_email str, reply_to list)
    """
    bare_address = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
    if shop_name:
        from_email = formataddr((f"{shop_name} via RS Systems", bare_address))
    else:
        from_email = settings.DEFAULT_FROM_EMAIL
    reply_to = [reply_to_email] if reply_to_email else []
    return from_email, reply_to


def _normalize_detail_rows(detail_rows):
    """Accept the row shapes callers use and hand the template one of them.

    ('Total', '$84.75')                       -> plain row
    ('Total', '$84.75', 'strong')             -> label goes dark too
    ('Balance', '$0.00', 'strong money')      -> value goes green
    {'label': ..., 'value': ..., 'money': 1}  -> passed through

    Two-tuples are what every existing caller passes and stay the default;
    the flags exist so a summary row (Total, Balance, Amount paid) can carry
    the weight it has on the invoice itself instead of looking like one more
    line of metadata.
    """
    rows = []
    for row in detail_rows or []:
        if isinstance(row, dict):
            rows.append({
                'label': row.get('label', ''),
                'value': row.get('value', ''),
                'strong': row.get('strong', ''),
                'money': row.get('money', ''),
            })
            continue
        label, value, flags = (list(row) + [''])[:3]
        flags = flags or ''
        rows.append({
            'label': label,
            'value': value,
            'strong': 'strong' in flags,
            'money': 'money' in flags,
        })
    return rows


def render_branded_email(
    subject,
    headline,
    body_paragraphs,
    *,
    tenant=None,
    platform=False,
    lede=None,
    note=None,
    preheader=None,
    pill_label=None,
    pill_tone=None,
    header_meta=None,
    unsubscribe_path=None,
    button_text=None,
    button_url=None,
    secondary_button_text=None,
    secondary_button_url=None,
    detail_rows=None,
    plain_text=None,
    tracking_pixel_url=None,
):
    """Render a branded email without sending it.

    The rendering half of send_branded_email, split out so `manage.py
    preview_emails` renders EXACTLY what a real send would produce —
    identity resolution, row normalization and all. Previews that
    hand-build the template context drift the day someone edits the real
    context and not the copy.

    Returns:
        tuple: (html str, plain_text str)
    """
    from django.template.loader import render_to_string

    from core.models.email_branding import EmailBrandingConfig

    # Identity. A platform email (subscription, billing, account) is from
    # RS Systems, so it resolves branding with no tenant — platform name,
    # platform blue — and carries the shop's name on the right of the header
    # instead. Letting a shop's brand colour onto a platform email is how
    # an owner ends up unable to tell who is asking them for money.
    branding = EmailBrandingConfig.get_tenant_context(None if platform else tenant)
    if platform and tenant is not None and not header_meta:
        header_meta = tenant.name or ''

    rows = _normalize_detail_rows(detail_rows)
    context = {
        'subject': subject,
        'headline': headline,
        'lede': lede,
        'note': note,
        'preheader': preheader or lede or '',
        'pill_label': pill_label,
        'pill_tone': pill_tone,
        'header_meta': header_meta,
        'unsubscribe_path': unsubscribe_path,
        'body_paragraphs': body_paragraphs or [],
        'detail_rows': rows,
        'button_text': button_text,
        'button_url': button_url,
        'secondary_button_text': secondary_button_text,
        'secondary_button_url': secondary_button_url,
        'tracking_pixel_url': tracking_pixel_url,
        'branding': branding,
        'base_url': getattr(settings, 'SITE_URL', 'https://rssystems.io').rstrip('/'),
    }

    html = render_to_string('emails/generic.html', context)
    if not plain_text:
        # Rendered from the same context as the HTML, so the two halves
        # cannot say different things. The template owns the layout — the
        # rows of '=' rulers this used to emit are gone for good.
        plain_text = render_to_string('emails/generic.txt', context).strip() + '\n'
    return html, plain_text


def send_branded_email(
    subject,
    recipient_list,
    headline,
    body_paragraphs,
    *,
    tenant=None,
    platform=False,
    lede=None,
    note=None,
    preheader=None,
    pill_label=None,
    pill_tone=None,
    header_meta=None,
    unsubscribe_path=None,
    button_text=None,
    button_url=None,
    secondary_button_text=None,
    secondary_button_url=None,
    detail_rows=None,
    plain_text=None,
    from_email=None,
    cc=None,
    attachments=None,
    fail_silently=False,
    tracking_pixel_url=None,
    headers=None,
):
    """
    Send an email through the shared chassis (templates/emails/base.html).

    This used to build its own HTML in an f-string, which meant RS Systems
    had two unrelated email designs — this one and the Django notification
    templates — that shared no header, button, type scale or colour. Both
    now render through emails/base.html, so a fix lands once.

    Args:
        subject: Email subject line
        recipient_list: List of email addresses
        headline: The news, as a sentence — say what the subject line says
        body_paragraphs: List of paragraph strings (escaped on render)
        tenant: Optional Tenant for branding (company name, logo, colour)
        platform: True for mail from RS Systems itself (subscription,
            billing, account). Forces the platform identity and colour and
            puts the shop's name in `header_meta` instead — a shop's brand
            colour must never appear on a platform email.
        lede: Optional one-sentence subhead under the headline
        note: Optional quiet closing line under the action
        preheader: Optional inbox preview line (defaults to the lede)
        pill_label / pill_tone: Optional status pill. Tones are in
            core/templatetags/email_ui.py.
        header_meta: Optional right side of the header (a job or invoice ref)
        unsubscribe_path: Optional path for the preferences link
        button_text / button_url: The one primary action
        secondary_button_text / secondary_button_url: Rendered as a plain
            link under the primary, not a competing button
        detail_rows: Rows for the detail block — see _normalize_detail_rows
        plain_text: Optional override for the plain-text alternative
        from_email: Override from address
        cc: Optional CC list
        attachments: Optional list of (filename, content, mimetype) tuples
        fail_silently: Whether to suppress send errors
        tracking_pixel_url: Optional open-tracking pixel (invoice emails)
        headers: Optional dict of extra message headers (e.g. List-Unsubscribe,
            X-SES-MESSAGE-TAGS for SES event correlation)

    Returns:
        int: Number of emails sent (0 or 1)
    """
    reply_to_email = '' if platform else (tenant.business_email or '' if tenant else '')

    html, plain_text = render_branded_email(
        subject,
        headline,
        body_paragraphs,
        tenant=tenant,
        platform=platform,
        lede=lede,
        note=note,
        preheader=preheader,
        pill_label=pill_label,
        pill_tone=pill_tone,
        header_meta=header_meta,
        unsubscribe_path=unsubscribe_path,
        button_text=button_text,
        button_url=button_url,
        secondary_button_text=secondary_button_text,
        secondary_button_url=secondary_button_url,
        detail_rows=detail_rows,
        plain_text=plain_text,
        tracking_pixel_url=tracking_pixel_url,
    )

    # A platform email is from RS Systems, not "<Shop> via RS Systems" —
    # the From line has to agree with the header the reader is looking at,
    # and replies about a subscription must not land in the shop's inbox.
    default_from, reply_to = shop_sender(
        shop_name=None if platform else (tenant.name if tenant else None),
        reply_to_email=reply_to_email,
    )
    email = EmailMultiAlternatives(
        subject=subject,
        body=plain_text,
        from_email=from_email or default_from,
        to=recipient_list,
        cc=cc or [],
        reply_to=reply_to,
        headers=headers or None,
    )
    email.attach_alternative(html, 'text/html')

    if attachments:
        for filename, content, mimetype in attachments:
            email.attach(filename, content, mimetype)

    return email.send(fail_silently=fail_silently)
