"""
Support app models.

GuideFeedback — the "Was this helpful?" thumbs on each help guide. Tells us
which guides fail people before they email support. Phase 3 adds
SupportMessage (contact form) alongside it.
"""

from django.conf import settings
from django.db import models


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
