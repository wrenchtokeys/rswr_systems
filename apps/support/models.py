"""
Support app models.

GuideFeedback — the "Was this helpful?" thumbs on each help guide. Tells us
which guides fail people before they email support.

SupportMessage — the /help/contact/ form (Phase 3). Record-first: the row is
saved before the notification email is attempted, so a mail outage can never
lose a cry for help — `emailed_ok=False` rows are the ones to sweep for in
the admin after an SES incident.
"""

from django.conf import settings
from django.db import models


class SupportMessage(models.Model):
    TOPIC_CHOICES = [
        ('question', 'How do I do something?'),
        ('problem', "Something's not working"),
        ('billing', 'Billing & my plan'),
        ('idea', 'I have an idea'),
        ('other', 'Something else'),
    ]
    STATUS_CHOICES = [
        ('new', 'New'),
        ('replied', 'Replied'),
        ('closed', 'Closed'),
    ]

    # SET_NULL + snapshots: deleting a tenant or user must never delete what
    # they told us — name/email keep the message answerable on their own.
    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='support_messages',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='support_messages',
    )
    name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(help_text='Where the reply goes')
    topic = models.CharField(max_length=20, choices=TOPIC_CHOICES, default='question')
    message = models.TextField()
    page = models.CharField(
        max_length=500, blank=True,
        help_text='Page the sender was on before opening the form',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    emailed_ok = models.BooleanField(
        default=False,
        help_text='Whether the notification email to the admins was sent',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        who = self.name or self.email
        return f'{who} ({self.get_topic_display()}) — {self.created_at:%Y-%m-%d}'


class GuideFeedback(models.Model):
    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='guide_feedback',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='guide_feedback',
    )
    slug = models.SlugField(max_length=64)
    helpful = models.BooleanField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'slug'], name='one_vote_per_user_per_guide'),
        ]

    def __str__(self):
        thumb = 'up' if self.helpful else 'down'
        return f'{self.slug}: thumbs {thumb} from {self.user_id}'
