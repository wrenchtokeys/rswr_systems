"""
Logging utilities for PII masking.

These utilities help mask personally identifiable information (PII)
in log messages to prevent accidental exposure of sensitive data.
"""
import re


def mask_email(email: str) -> str:
    """
    Mask an email address for safe logging.

    Shows first 2 characters of local part and domain, masks the rest.

    Examples:
        user@example.com -> us***@ex***.com
        john.doe@company.org -> jo***@co***.org

    Args:
        email: Email address to mask

    Returns:
        Masked email address, or original string if not a valid email format
    """
    if not email or '@' not in email:
        return email or ''

    try:
        local, domain = email.rsplit('@', 1)

        # Mask local part: show first 2 chars
        if len(local) > 2:
            masked_local = local[:2] + '***'
        else:
            masked_local = local[0] + '***' if local else '***'

        # Mask domain: show first 2 chars and TLD
        if '.' in domain:
            domain_name, tld = domain.rsplit('.', 1)
            if len(domain_name) > 2:
                masked_domain = domain_name[:2] + '***.' + tld
            else:
                masked_domain = domain_name + '***.' + tld
        else:
            masked_domain = domain[:2] + '***' if len(domain) > 2 else domain

        return f"{masked_local}@{masked_domain}"
    except (ValueError, IndexError):
        return '***@***.***'


def mask_phone(phone: str) -> str:
    """
    Mask a phone number for safe logging.

    Shows last 4 digits only.

    Examples:
        +15551234567 -> ***4567
        (555) 123-4567 -> ***4567
        5551234567 -> ***4567

    Args:
        phone: Phone number to mask

    Returns:
        Masked phone number showing only last 4 digits
    """
    if not phone:
        return ''

    # Extract only digits
    digits = re.sub(r'\D', '', phone)

    if len(digits) < 4:
        return '***'

    return f"***{digits[-4:]}"


def mask_pii(text: str) -> str:
    """
    Mask common PII patterns in a text string.

    Detects and masks:
    - Email addresses
    - Phone numbers (US format)
    - Credit card numbers
    - SSN patterns

    Args:
        text: Text that may contain PII

    Returns:
        Text with PII patterns masked
    """
    if not text:
        return ''

    # Mask email addresses
    text = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        lambda m: mask_email(m.group()),
        text
    )

    # Mask US phone numbers (various formats)
    # Matches: +1-555-123-4567, (555) 123-4567, 555.123.4567, 5551234567
    text = re.sub(
        r'(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        lambda m: mask_phone(m.group()),
        text
    )

    # Mask potential credit card numbers (13-19 digits, possibly with separators)
    text = re.sub(
        r'\b(?:\d{4}[-\s]?){3,4}\d{1,4}\b',
        '****-****-****-****',
        text
    )

    # Mask SSN patterns (XXX-XX-XXXX)
    text = re.sub(
        r'\b\d{3}-\d{2}-\d{4}\b',
        '***-**-****',
        text
    )

    return text
