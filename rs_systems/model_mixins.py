"""
Model Mixins for RS Systems

Reusable mixins for Django models.
"""


class AutoUpdateTimestampMixin:
    """
    Fix Django's auto_now + update_fields interaction.

    Django does NOT auto-include auto_now fields when save() is called with
    update_fields=[...].  This means code paths that use update_fields for
    efficiency silently leave updated_at stale — the timestamp lies about
    when the record was last modified.

    This mixin overrides save() to auto-inject 'updated_at' into
    update_fields when the caller specifies update_fields without it.
    A new list is created to avoid mutating the caller's original list.

    Usage:
        class MyModel(AutoUpdateTimestampMixin, models.Model):
            updated_at = models.DateTimeField(auto_now=True)
            ...

    IMPORTANT: Place AutoUpdateTimestampMixin BEFORE models.Model in the
    MRO so its save() wraps Django's save().

    Original fix: CODE-253 (Tenant model only)
    Generalized: CODE-254 (all 17 affected models)
    """

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'updated_at' not in update_fields:
            # Don't mutate the caller's list — create a new one
            kwargs['update_fields'] = list(update_fields) + ['updated_at']
        super().save(*args, **kwargs)
