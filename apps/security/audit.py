"""
One writer for SecurityAuditLog.

The model existed for months with no callers. Insurance claim tracking (B5)
is the first surface sensitive enough to need it — the session doc says to
extend this log rather than invent another — so every claim mutation goes
through `log_event`. Add new event types to `SecurityAuditLog.EVENT_TYPES`
first; an unknown type is a bug, not a fallback.
"""
import logging

from apps.security.models import LoginAttempt, SecurityAuditLog

logger = logging.getLogger(__name__)

_EVENT_TYPES = {code for code, _ in SecurityAuditLog.EVENT_TYPES}


def log_event(request, event_type, description, tenant=None, **metadata):
    """Record an audit row. Never raises: an audit failure must not undo
    the action it describes, but it is logged loudly.

    `request` may be None for a change made by a service with no request
    (an auto-created claim during invoice creation); the IP is then
    recorded as unspecified.
    """
    if event_type not in _EVENT_TYPES:
        raise ValueError(f'Unknown security audit event type: {event_type}')
    user = None
    ip = '0.0.0.0'
    if request is not None:
        if getattr(request, 'user', None) is not None and request.user.is_authenticated:
            user = request.user
        ip = LoginAttempt.get_client_ip(request) or ip
        tenant = tenant or getattr(request, 'tenant', None)
    if tenant is not None:
        metadata.setdefault('tenant_id', tenant.id)
    try:
        return SecurityAuditLog.objects.create(
            user=user,
            event_type=event_type,
            ip_address=ip,
            description=description,
            metadata=metadata,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f'Security audit write failed ({event_type}): {e}')
        return None
