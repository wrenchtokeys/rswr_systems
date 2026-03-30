"""
CODE-198: Verify db_index=True on Tenant Stripe ID fields.

These fields are used in webhook lookups (.get(stripe_customer_id=...)) and
Connect event routing (.get(stripe_connect_account_id=...)). Without indexes,
every Stripe webhook event triggers a full table scan on the tenants table.

Regression tests ensure indexes are never accidentally removed.
"""
from django.test import TestCase
from apps.tenants.models import Tenant


class TenantStripeIdIndexTests(TestCase):
    """Verify that Stripe ID fields on Tenant have db_index=True."""

    def test_stripe_customer_id_has_db_index(self):
        field = Tenant._meta.get_field('stripe_customer_id')
        self.assertTrue(
            field.db_index,
            "stripe_customer_id must have db_index=True — used in webhook lookups"
        )

    def test_stripe_subscription_id_has_db_index(self):
        field = Tenant._meta.get_field('stripe_subscription_id')
        self.assertTrue(
            field.db_index,
            "stripe_subscription_id must have db_index=True — used in webhook lookups"
        )

    def test_stripe_connect_account_id_has_db_index(self):
        field = Tenant._meta.get_field('stripe_connect_account_id')
        self.assertTrue(
            field.db_index,
            "stripe_connect_account_id must have db_index=True — used in Connect webhook routing"
        )

    def test_indexes_exist_in_database(self):
        """Verify the migration actually created the indexes in PostgreSQL."""
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'tenants_tenant'
                AND (
                    indexname LIKE '%stripe_customer_id%'
                    OR indexname LIKE '%stripe_subscription_id%'
                    OR indexname LIKE '%stripe_connect_account_id%'
                )
            """)
            index_names = [row[0] for row in cursor.fetchall()]
        self.assertTrue(
            len(index_names) >= 3,
            f"Expected 3 Stripe ID indexes in DB, found {len(index_names)}: {index_names}"
        )

    def test_webhook_lookup_uses_index(self):
        """Verify the common webhook lookup pattern works with indexed fields."""
        from django.contrib.auth.models import User
        owner = User.objects.create_user('idx_test_owner', 'idx@test.com', 'pass1234')
        tenant = Tenant.objects.create(
            name='Index Test Shop',
            slug='index-test-shop',
            owner=owner,
            stripe_customer_id='cus_test123',
            stripe_subscription_id='sub_test456',
            stripe_connect_account_id='acct_test789',
        )
        # These are the exact patterns used in webhooks.py
        self.assertEqual(
            Tenant.objects.get(stripe_customer_id='cus_test123'),
            tenant
        )
        self.assertEqual(
            Tenant.objects.get(stripe_subscription_id='sub_test456'),
            tenant
        )
        self.assertEqual(
            Tenant.objects.get(stripe_connect_account_id='acct_test789'),
            tenant
        )

    def test_empty_stripe_ids_dont_collide(self):
        """Multiple tenants with blank Stripe IDs shouldn't cause issues."""
        from django.contrib.auth.models import User
        owner1 = User.objects.create_user('idx_owner1', 'idx1@test.com', 'pass1234')
        owner2 = User.objects.create_user('idx_owner2', 'idx2@test.com', 'pass1234')
        Tenant.objects.create(name='Shop A', slug='shop-a', owner=owner1)
        Tenant.objects.create(name='Shop B', slug='shop-b', owner=owner2)
        # Both have blank stripe_customer_id — filter should return both
        self.assertEqual(
            Tenant.objects.filter(stripe_customer_id='').count(),
            2
        )
