"""
Shared HTML email builder for RS Systems.

All outgoing emails should use `send_branded_email()` to get consistent
branding with the nice invoice-style HTML template.
"""
import logging
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

logger = logging.getLogger(__name__)


def shop_sender(shop_name=None, reply_to_email=None):
    """
    Build (from_email, reply_to) for shop-branded email.

    Mail is always sent through the platform's SES-verified address —
    sending from a shop's own domain would fail SPF/DKIM — but the From
    header shows the shop's name and replies route to the shop's email.

    Returns:
        tuple: (from_email str, reply_to list)
    """
    bare_address = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
    from_email = formataddr((shop_name, bare_address)) if shop_name else settings.DEFAULT_FROM_EMAIL
    reply_to = [reply_to_email] if reply_to_email else []
    return from_email, reply_to


def send_branded_email(
    subject,
    recipient_list,
    headline,
    body_paragraphs,
    *,
    tenant=None,
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
):
    """
    Send a branded HTML email with consistent styling.

    Args:
        subject: Email subject line
        recipient_list: List of email addresses
        headline: Big text at top of email (e.g. "Welcome to RS Systems!")
        body_paragraphs: List of paragraph strings (plain text, will be escaped)
        tenant: Optional Tenant for branding (company name, logo, etc.)
        button_text: Optional primary CTA button text
        button_url: Optional primary CTA button URL
        secondary_button_text: Optional secondary button text
        secondary_button_url: Optional secondary button URL
        detail_rows: Optional list of (label, value) tuples for a detail box
        plain_text: Optional override for plain-text version
        from_email: Override from address
        cc: Optional CC list
        attachments: Optional list of (filename, content, mimetype) tuples
        fail_silently: Whether to suppress send errors

    Returns:
        int: Number of emails sent (0 or 1)
    """
    # Branding
    company_name = 'RS Systems'
    company_phone = ''
    company_address = ''
    primary_color = '#1e40af'
    button_color = '#2563eb'
    reply_to_email = ''
    if tenant:
        company_name = tenant.name or company_name
        company_phone = tenant.business_phone or ''
        company_address = tenant.business_address or ''
        reply_to_email = tenant.business_email or ''
        if getattr(tenant, 'brand_color', ''):
            primary_color = tenant.brand_color
            button_color = tenant.brand_color

    # Build plain text fallback
    if not plain_text:
        plain_text = f"{headline}\n\n"
        plain_text += "\n\n".join(body_paragraphs)
        if detail_rows:
            plain_text += "\n\n"
            for label, value in detail_rows:
                plain_text += f"  {label}: {value}\n"
        if button_url:
            plain_text += f"\n{button_text or 'Click here'}: {button_url}\n"
        plain_text += f"\n\n— {company_name}"
        if company_phone:
            plain_text += f"\n{company_phone}"

    # Build paragraphs HTML
    paragraphs_html = ''
    for p in body_paragraphs:
        paragraphs_html += f'<p style="font-size:15px;color:#374151;margin:0 0 16px;line-height:1.6;">{escape(p)}</p>'

    # Detail box
    details_html = ''
    if detail_rows:
        rows = ''
        for label, value in detail_rows:
            rows += f'<tr><td style="padding:4px 0;color:#6b7280;">{escape(str(label))}</td><td style="text-align:right;font-weight:600;color:#111827;">{escape(str(value))}</td></tr>'
        details_html = f'''
        <div style="background-color:#f9fafb;border-radius:8px;padding:16px;margin-bottom:20px;">
            <table style="width:100%;font-size:14px;">{rows}</table>
        </div>'''

    # Primary button
    button_html = ''
    if button_text and button_url:
        button_html = f'''
        <div style="text-align:center;margin:24px 0;">
            <a href="{escape(button_url)}" style="display:inline-block;padding:14px 32px;background-color:{button_color};color:#ffffff;text-decoration:none;font-size:16px;font-weight:600;border-radius:8px;">
                {escape(button_text)}
            </a>
        </div>'''

    # Secondary button
    secondary_html = ''
    if secondary_button_text and secondary_button_url:
        secondary_html = f'''
        <div style="text-align:center;margin:16px 0;">
            <a href="{escape(secondary_button_url)}" style="display:inline-block;padding:10px 24px;background-color:#ffffff;color:{button_color};text-decoration:none;font-size:14px;font-weight:500;border:2px solid {button_color};border-radius:8px;">
                {escape(secondary_button_text)}
            </a>
        </div>'''

    # Footer
    footer_parts = [f'<p style="margin:0;font-size:13px;color:#6b7280;font-weight:600;">{escape(company_name)}</p>']
    if company_address:
        footer_parts.append(f'<p style="margin:4px 0 0;font-size:12px;color:#9ca3af;">{escape(company_address)}</p>')
    if company_phone:
        footer_parts.append(f'<p style="margin:4px 0 0;font-size:12px;color:#9ca3af;">{escape(company_phone)}</p>')
    footer_html = '\n'.join(footer_parts)

    # Open-tracking pixel (e.g. invoice emails — loading it marks the
    # invoice viewed). Not escaped: callers pass a URL we built ourselves.
    pixel_html = ''
    if tracking_pixel_url:
        pixel_html = (
            f'<img src="{tracking_pixel_url}" width="1" height="1" alt="" '
            f'style="display:block;width:1px;height:1px;border:0;overflow:hidden;">'
        )

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">

<!-- Header -->
<div style="background-color:{primary_color};padding:24px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;">{escape(company_name)}</h1>
</div>

<!-- Body -->
<div style="background-color:#ffffff;padding:32px 40px;border:1px solid #e5e7eb;border-top:none;">
    <h2 style="font-size:22px;color:#111827;margin:0 0 20px;font-weight:700;">{escape(headline)}</h2>
    {paragraphs_html}
    {details_html}
    {button_html}
    {secondary_html}
</div>

<!-- Footer -->
<div style="padding:16px 24px;text-align:center;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;background-color:#f9fafb;">
    {footer_html}
</div>

{pixel_html}
</div>
</body>
</html>'''

    default_from, reply_to = shop_sender(
        shop_name=tenant.name if tenant else None,
        reply_to_email=reply_to_email,
    )
    email = EmailMultiAlternatives(
        subject=subject,
        body=plain_text,
        from_email=from_email or default_from,
        to=recipient_list,
        cc=cc or [],
        reply_to=reply_to,
    )
    email.attach_alternative(html, 'text/html')

    if attachments:
        for filename, content, mimetype in attachments:
            email.attach(filename, content, mimetype)

    return email.send(fail_silently=fail_silently)
