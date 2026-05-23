from django.db import models
from django.template import Template, Context
from django.utils.safestring import mark_safe

from rs_systems.model_mixins import AutoUpdateTimestampMixin


class NotificationTemplate(AutoUpdateTimestampMixin, models.Model):
    """
    Reusable notification templates with variable substitution.

    Supports:
    - Django template syntax for dynamic content
    - Multiple delivery channels (in-app, email, SMS)
    - Preview generation for testing
    - Version tracking for template changes
    """

    # Import constants from Notification model
    from core.models.notification import Notification

    # Template identification
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Internal name for the template (e.g., 'repair_approved')"
    )
    description = models.TextField(
        help_text="Description of when this template is used"
    )
    category = models.CharField(
        max_length=50,
        choices=Notification.CATEGORY_CHOICES,
        help_text="Notification category this template belongs to"
    )

    # Default priority (can be overridden when creating notification)
    default_priority = models.CharField(
        max_length=20,
        choices=Notification.PRIORITY_CHOICES,
        default=Notification.PRIORITY_MEDIUM
    )

    # Template content for different channels
    title_template = models.CharField(
        max_length=200,
        help_text="Template for notification title (Django template syntax)"
    )
    message_template = models.TextField(
        help_text="Template for in-app message (supports markdown and Django template syntax)"
    )

    # Email-specific content
    email_subject_template = models.CharField(
        max_length=200,
        blank=True,
        help_text="Email subject line template (plain text)"
    )
    email_html_template = models.TextField(
        blank=True,
        help_text="HTML email body template (full HTML with Django template syntax)"
    )
    email_text_template = models.TextField(
        blank=True,
        help_text="Plain text email body template (fallback for non-HTML clients)"
    )

    # SMS-specific content
    sms_template = models.CharField(
        max_length=160,
        blank=True,
        help_text="SMS message template (max 160 chars after rendering)"
    )

    # Action URL template (supports variables)
    action_url_template = models.CharField(
        max_length=500,
        blank=True,
        help_text="URL template for notification action (e.g., '/tech/repairs/{{ repair.id }}/')"
    )

    # Template metadata
    active = models.BooleanField(
        default=True,
        help_text="Whether this template is currently active"
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Template version for tracking changes"
    )

    # Required context variables (for documentation)
    required_context = models.JSONField(
        default=list,
        help_text="List of required context variable names (e.g., ['repair', 'customer'])"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_templates'
    )

    class Meta:
        ordering = ['category', 'name']
        verbose_name = "Notification Template"
        verbose_name_plural = "Notification Templates"

    def __str__(self):
        return f"{self.name} (v{self.version})"

    def render(self, context_dict):
        """
        Render all template fields with the provided context.

        Args:
            context_dict (dict): Context variables for template rendering

        Returns:
            dict: Rendered content for all channels
        """
        from django.template.loader import render_to_string
        from django.conf import settings

        # Inject base_url for absolute links in email templates
        if 'base_url' not in context_dict:
            context_dict['base_url'] = getattr(
                settings, 'SITE_URL', 'https://rssystems.io'
            ).rstrip('/')

        context = Context(context_dict)

        def render_template_field(content):
            """Render template content, loading from file if it's a path."""
            if not content:
                return ''
            # Check if content is a template path (ends with .html or .txt)
            content_stripped = content.strip()
            if content_stripped.endswith(('.html', '.txt')):
                # Load and render template file
                return render_to_string(content_stripped, context_dict)
            else:
                # Render as inline template syntax
                return Template(content).render(context)

        # Use autoescape=False to prevent double-escaping when the rendered
        # message is later displayed in Django templates (which auto-escape).
        # The context values (customer name, unit number, etc.) are internal
        # data from our own models, not raw user input.
        from django.template import engines
        plain_context = Context(context_dict, autoescape=False)

        return {
            'title': Template(self.title_template).render(plain_context),
            'message': Template(self.message_template).render(plain_context),
            'email_subject': Template(self.email_subject_template).render(context) if self.email_subject_template else '',
            'email_html': render_template_field(self.email_html_template),
            'email_text': render_template_field(self.email_text_template),
            'sms': Template(self.sms_template).render(context) if self.sms_template else '',
            'action_url': Template(self.action_url_template).render(context) if self.action_url_template else '',
        }

    def preview(self, sample_context):
        """
        Generate preview with sample context for testing.

        Args:
            sample_context (dict): Sample data for preview

        Returns:
            dict: Preview of rendered content
        """
        return self.render(sample_context)

    def validate_context(self, context_dict):
        """
        Validate that all required context variables are present.

        Args:
            context_dict (dict): Context to validate

        Returns:
            tuple: (is_valid, missing_variables)
        """
        missing = [var for var in self.required_context if var not in context_dict]
        return (len(missing) == 0, missing)
