"""
Email Branding Configuration Model

This module provides the EmailBrandingConfig model for customizing
email template branding across the notification system.

Features:
- Singleton pattern (only one branding config exists)
- Logo upload with S3 storage
- Customizable color scheme (6 colors)
- Company information
- Social media integration
- Typography settings
"""

import logging

from django.db import models
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.conf import settings
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
import sys

from rs_systems.model_mixins import AutoUpdateTimestampMixin

logger = logging.getLogger(__name__)


class EmailBrandingConfig(AutoUpdateTimestampMixin, models.Model):
    """
    Singleton model for email template branding customization.

    Only one instance of this model should exist. Provides centralized
    configuration for all email templates including colors, logo, company
    info, and social media links.
    """

    # Singleton enforcement
    singleton_id = models.BooleanField(default=True, unique=True, editable=False)

    # === LOGO SETTINGS ===
    logo = models.ImageField(
        upload_to='email_branding/',
        null=True,
        blank=True,
        help_text='Company logo for email header. Will be resized to max 400px width.'
    )
    logo_width = models.PositiveIntegerField(
        default=200,
        help_text='Logo display width in pixels (max 400px)'
    )

    # === COLOR SCHEME ===
    hex_validator = RegexValidator(
        regex=r'^#[0-9A-Fa-f]{6}$',
        message='Enter a valid hex color code (e.g., #2C5282)'
    )

    primary_color = models.CharField(
        max_length=7,
        default='#2C5282',
        validators=[hex_validator],
        help_text='Primary brand color (hex code)'
    )
    secondary_color = models.CharField(
        max_length=7,
        default='#4299E1',
        validators=[hex_validator],
        help_text='Secondary accent color (hex code)'
    )
    success_color = models.CharField(
        max_length=7,
        default='#38A169',
        validators=[hex_validator],
        help_text='Success/approval color (hex code)'
    )
    danger_color = models.CharField(
        max_length=7,
        default='#E53E3E',
        validators=[hex_validator],
        help_text='Danger/error color (hex code)'
    )
    text_color = models.CharField(
        max_length=7,
        default='#2D3748',
        validators=[hex_validator],
        help_text='Main text color (hex code)'
    )
    background_color = models.CharField(
        max_length=7,
        default='#F7FAFC',
        validators=[hex_validator],
        help_text='Email background color (hex code)'
    )

    # === COMPANY INFORMATION ===
    company_name = models.CharField(
        max_length=200,
        default='RS Systems',
        help_text='Company name displayed in email footer'
    )
    company_address = models.TextField(
        blank=True,
        help_text='Company address (optional, displayed in footer)'
    )
    support_email = models.EmailField(
        blank=True,
        help_text='Support email address (optional, displayed in footer)'
    )
    support_phone = models.CharField(
        max_length=20,
        blank=True,
        help_text='Support phone number (optional, displayed in footer)'
    )
    website_url = models.URLField(
        blank=True,
        help_text='Company website URL (optional)'
    )

    # === SOCIAL MEDIA LINKS ===
    facebook_url = models.URLField(
        blank=True,
        help_text='Facebook page URL (optional)'
    )
    twitter_url = models.URLField(
        blank=True,
        help_text='Twitter/X profile URL (optional)'
    )
    linkedin_url = models.URLField(
        blank=True,
        help_text='LinkedIn company page URL (optional)'
    )

    # === TYPOGRAPHY ===
    heading_font = models.CharField(
        max_length=100,
        default='Arial, Helvetica, sans-serif',
        help_text='Font family for headings'
    )
    body_font = models.CharField(
        max_length=100,
        default='Arial, Helvetica, sans-serif',
        help_text='Font family for body text'
    )

    # === BUTTON STYLING ===
    button_border_radius = models.PositiveIntegerField(
        default=4,
        help_text='Button border radius in pixels'
    )

    # === FOOTER TEXT ===
    footer_text = models.TextField(
        blank=True,
        default='You are receiving this email because you are registered with RS Systems.',
        help_text='Custom footer text (optional)'
    )

    # === METADATA ===
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_branding_updates',
        help_text='User who last updated branding configuration'
    )

    class Meta:
        verbose_name = 'Email Branding Configuration'
        verbose_name_plural = 'Email Branding Configuration'

    def __str__(self):
        return f'Email Branding Configuration (Last updated: {self.updated_at.strftime("%Y-%m-%d %H:%M")})'

    def clean(self):
        """Validate logo width does not exceed 400px"""
        super().clean()
        if self.logo_width and self.logo_width > 400:
            raise ValidationError({'logo_width': 'Logo width cannot exceed 400px for email compatibility.'})

    def save(self, *args, **kwargs):
        """
        Override save to:
        1. Enforce singleton pattern
        2. Optimize uploaded logo
        """
        # Enforce singleton
        if not self.pk and EmailBrandingConfig.objects.exists():
            raise ValidationError('Only one EmailBrandingConfig instance is allowed.')

        # Optimize logo if uploaded
        if self.logo:
            self.logo = self._optimize_logo(self.logo)

        super().save(*args, **kwargs)

    def _optimize_logo(self, logo_field):
        """
        Optimize uploaded logo:
        - Resize to max 400px width
        - Convert to RGB if needed
        - Optimize file size
        """
        try:
            img = Image.open(logo_field)

            # Convert RGBA to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background

            # Resize if width exceeds 400px
            if img.width > 400:
                ratio = 400 / img.width
                new_height = int(img.height * ratio)
                img = img.resize((400, new_height), Image.Resampling.LANCZOS)

            # Save optimized image
            output = BytesIO()
            img.save(output, format='JPEG', quality=85, optimize=True)
            output.seek(0)

            # Return as InMemoryUploadedFile
            return InMemoryUploadedFile(
                output,
                'ImageField',
                f'{logo_field.name.split(".")[0]}_optimized.jpg',
                'image/jpeg',
                sys.getsizeof(output),
                None
            )
        except Exception as e:
            # If optimization fails, return original
            print(f'Logo optimization failed: {e}')
            return logo_field

    def get_logo_url(self):
        """
        Get absolute URL for logo (for email embedding).

        Returns:
            str: Absolute URL to logo or empty string if no logo
        """
        if self.logo:
            # In production with S3, this will be the full S3 URL
            # In development, prepend MEDIA_URL
            if hasattr(settings, 'AWS_S3_CUSTOM_DOMAIN') and settings.AWS_S3_CUSTOM_DOMAIN:
                return self.logo.url
            else:
                # Local development
                from django.contrib.sites.models import Site
                try:
                    domain = Site.objects.get_current().domain
                    protocol = 'https' if settings.USE_HTTPS else 'http'
                    return f'{protocol}://{domain}{self.logo.url}'
                except Exception:
                    logger.warning("Failed to get current site domain for logo URL; falling back to relative URL", exc_info=True)
                    return self.logo.url
        return ''

    def to_template_context(self):
        """
        Convert branding config to template context dictionary.

        Returns:
            dict: All branding settings formatted for email templates
        """
        return {
            'logo_url': self.get_logo_url(),
            'logo_width': self.logo_width,
            'primary_color': self.primary_color,
            'secondary_color': self.secondary_color,
            'success_color': self.success_color,
            'danger_color': self.danger_color,
            'text_color': self.text_color,
            'background_color': self.background_color,
            'company_name': self.company_name,
            'company_address': self.company_address,
            'support_email': self.support_email,
            'support_phone': self.support_phone,
            'website_url': self.website_url,
            'facebook_url': self.facebook_url,
            'twitter_url': self.twitter_url,
            'linkedin_url': self.linkedin_url,
            'heading_font': self.heading_font,
            'body_font': self.body_font,
            'button_border_radius': self.button_border_radius,
            'footer_text': self.footer_text,
        }

    @classmethod
    def get_instance(cls):
        """
        Get the singleton instance, creating if it doesn't exist.

        Returns:
            EmailBrandingConfig: The singleton branding configuration
        """
        instance, created = cls.objects.get_or_create(singleton_id=True)
        return instance

    def delete(self, *args, **kwargs):
        """Prevent deletion of singleton instance"""
        raise ValidationError('Email branding configuration cannot be deleted. You can only modify it.')
