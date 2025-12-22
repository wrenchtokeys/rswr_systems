"""
Core views for RS Systems.
"""

from .email_preview import preview_email_template
from .test_notification import test_notification

__all__ = ['preview_email_template', 'test_notification']
