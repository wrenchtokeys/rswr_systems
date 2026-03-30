"""
Regression tests for CODE-185: ReferralCode.customer_user should be OneToOneField,
not ForeignKey(unique=True).

Bug: ReferralCode.customer_user was defined as:
    customer_user = models.ForeignKey(CustomerUser, on_delete=models.CASCADE, unique=True)

This generated Django system check warning:
    rewards_referrals.ReferralCode.customer_user: (fields.W342) Setting unique=True
    on a ForeignKey has the same effect as using a OneToOneField.
    HINT: ForeignKey(unique=True) is usually better served by a OneToOneField.

The DB constraint (unique index) was added in migration 0011 but the model field
type was never updated to reflect the semantic intent — one referral code per
customer user.

Fix: Changed to models.OneToOneField(CustomerUser, on_delete=models.CASCADE).
Migration 0013 AlterField performs the rename with no data change (the unique
constraint already existed at the DB level).

AGENTS.md gotcha: "ForeignKey(unique=True) is usually better served by a
OneToOneField" — always use the appropriate field type for 1:1 relationships.
"""

from django.test import TestCase
from django.db import models

from apps.rewards_referrals.models import ReferralCode


class ReferralCodeFieldTypeTest(TestCase):
    """ReferralCode.customer_user must be a OneToOneField."""

    def test_customer_user_is_onetoonefield(self):
        """
        The customer_user field must be a OneToOneField, not a ForeignKey.

        This guards against regression where someone changes it back to
        ForeignKey(unique=True), which generates Django system check warning
        fields.W342.
        """
        field = ReferralCode._meta.get_field('customer_user')
        self.assertIsInstance(
            field,
            models.OneToOneField,
            "ReferralCode.customer_user should be a OneToOneField, not "
            f"{type(field).__name__}. See CODE-185."
        )

    def test_customer_user_is_not_foreignkey_with_unique(self):
        """
        The customer_user field must NOT be a plain ForeignKey — even with unique=True.

        A ForeignKey(unique=True) is semantically identical to a OneToOneField
        but generates Django system check warning fields.W342 and produces a
        worse developer experience (reverse accessor returns a manager instead
        of the object directly).
        """
        field = ReferralCode._meta.get_field('customer_user')
        # OneToOneField IS a subclass of ForeignKey in Django internals, so we
        # check the concrete type explicitly.
        self.assertEqual(
            type(field).__name__,
            'OneToOneField',
            "ReferralCode.customer_user must be models.OneToOneField, not "
            f"models.ForeignKey. See CODE-185."
        )

    def test_customer_user_unique_constraint_present(self):
        """
        The field must enforce uniqueness (either via OneToOneField or unique=True).
        OneToOneField always has unique=True, so this is implicitly guaranteed,
        but we make it explicit.
        """
        field = ReferralCode._meta.get_field('customer_user')
        self.assertTrue(
            field.unique,
            "ReferralCode.customer_user must have unique=True to enforce "
            "one referral code per customer. See CODE-185."
        )

    def test_reverse_accessor_returns_single_object(self):
        """
        With OneToOneField, the reverse accessor on CustomerUser returns a
        ReferralCode instance directly (or raises RelatedObjectDoesNotExist),
        NOT a manager. This is the semantic difference from ForeignKey.
        """
        from apps.customer_portal.models import CustomerUser
        # Check that the reverse relation is a OneToOneRel, not ManyToOneRel.
        # This confirms the reverse accessor behaves like a direct attribute.
        reverse_rel = CustomerUser._meta.get_field('referralcode')
        self.assertIsInstance(
            reverse_rel,
            models.OneToOneRel,
            "The reverse relation from CustomerUser to ReferralCode must be "
            "OneToOneRel (not ManyToOneRel). See CODE-185."
        )
