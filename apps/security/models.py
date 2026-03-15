from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class LoginAttempt(models.Model):
    """Track login attempts for security monitoring"""

    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    success = models.BooleanField(default=False)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    portal = models.CharField(
        max_length=20,
        choices=[
            ('customer', 'Customer Portal'),
            ('technician', 'Technician Portal'),
            ('admin', 'Admin Portal'),
            ('unified', 'Unified Login'),
        ],
        default='unified'
    )
    failure_reason = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reason for failed login"
    )

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['username', 'timestamp']),
            models.Index(fields=['ip_address', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.username} - {self.ip_address} - {'Success' if self.success else 'Failed'}"

    @classmethod
    def log_attempt(cls, request, username, success, portal='unified', failure_reason=''):
        """Helper method to log a login attempt. Never raises — login must not
        fail because security logging is broken."""
        try:
            ip_address = cls.get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

            return cls.objects.create(
                username=username,
                ip_address=ip_address,
                user_agent=user_agent,
                success=success,
                portal=portal,
                failure_reason=failure_reason,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Failed to log login attempt for %s", username
            )
            return None

    @classmethod
    def get_client_ip(cls, request):
        """Get the real client IP, considering proxy headers"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    @classmethod
    def get_recent_failures(cls, username=None, ip_address=None, hours=24):
        """Get recent failed login attempts"""
        cutoff_time = timezone.now() - timezone.timedelta(hours=hours)
        query = cls.objects.filter(
            success=False,
            timestamp__gte=cutoff_time
        )

        if username:
            query = query.filter(username=username)
        if ip_address:
            query = query.filter(ip_address=ip_address)

        return query.count()

    @classmethod
    def check_suspicious_activity(cls, username=None, ip_address=None):
        """Check for suspicious login patterns"""
        # More than 5 failures in last hour
        recent_failures = cls.get_recent_failures(username, ip_address, hours=1)
        if recent_failures >= 5:
            return True, f"Too many recent failures: {recent_failures} in last hour"

        # More than 20 failures in last 24 hours
        daily_failures = cls.get_recent_failures(username, ip_address, hours=24)
        if daily_failures >= 20:
            return True, f"Excessive failures: {daily_failures} in last 24 hours"

        return False, ""


class SecurityAuditLog(models.Model):
    """Audit log for security-related events"""

    EVENT_TYPES = [
        ('user_created', 'User Created'),
        ('user_deleted', 'User Deleted'),
        ('password_changed', 'Password Changed'),
        ('permission_granted', 'Permission Granted'),
        ('permission_revoked', 'Permission Revoked'),
        ('suspicious_activity', 'Suspicious Activity Detected'),
        ('data_export', 'Data Exported'),
        ('settings_changed', 'Settings Changed'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_audit_logs'
    )
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    ip_address = models.GenericIPAddressField()
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['event_type', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.user} - {self.timestamp}"