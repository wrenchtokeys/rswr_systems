"""
Core views for RS Systems.
"""

from .email_preview import preview_email_template
from .test_notification import test_notification
from .check_prefs import check_notification_prefs
from .diagnostic import diagnostic_view

__all__ = ['preview_email_template', 'test_notification', 'check_notification_prefs', 'diagnostic_view']
