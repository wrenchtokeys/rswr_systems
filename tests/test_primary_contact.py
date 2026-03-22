"""
Comprehensive tests for customer portal primary contact feature.

Covers:
- send_customer_invitation: is_primary_contact checkbox (checked/unchecked)
- set_primary_contact: toggle primary, only one primary at a time
- Tenant isolation: can't set primary on another tenant's customer
- Permission checks: only admins/managers can send invites or set primary
- Edge cases: no existing primary, demoting old primary, non-existent users
"""

import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician
from core.models import Customer
from apps.customer_portal.models import CustomerUser, CustomerInvitation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_SETTINGS = {
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


def make_tenant(name, username):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        }
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name='Owner', last_name='User')
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user,
        subscription_plan=plan,
        plan='trial',
        subscription_status='trialing',
    )
    TenantMembership.objects.create(user=user, tenant=tenant, role='owner')
    tech = Technician.objects.create(user=user, tenant=tenant, is_manager=True)
    return user, tenant, tech


def make_manager(tenant, username):
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name='Manager', last_name='User')
    TenantMembership.objects.create(user=user, tenant=tenant, role='manager')
    tech = Technician.objects.create(user=user, tenant=tenant, is_manager=True)
    return user, tech


def make_regular_tech(tenant, username):
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name='Tech', last_name='User')
    TenantMembership.objects.create(user=user, tenant=tenant, role='technician')
    tech = Technician.objects.create(user=user, tenant=tenant, is_manager=False)
    return user, tech


def make_customer_user(customer, username, is_primary=False):
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123')
    cu = CustomerUser.objects.create(user=user, customer=customer, is_primary_contact=is_primary)
    return user, cu


# ---------------------------------------------------------------------------
# send_customer_invitation — is_primary_contact flag
# ---------------------------------------------------------------------------

@override_settings(**TEST_SETTINGS)
class SendInvitationPrimaryFlagTests(TestCase):
    """Tests for the is_primary_contact checkbox on the send invitation form."""

    def setUp(self):
        self.owner, self.tenant, self.tech = make_tenant('Glass Co', 'inv_owner')
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)
        self.url = f'/tech/customers/{self.customer.id}/invite/'

    def _post(self, client, extra=None):
        data = {
            'email': 'contact@fleet.com',
            'first_name': 'Jane',
            'last_name': 'Fleet',
        }
        if extra:
            data.update(extra)
        return client.post(self.url, data)

    def test_invite_without_primary_flag_creates_non_primary_invitation(self):
        """Checkbox unchecked → invitation created with is_primary_contact=False."""
        c = Client()
        c.force_login(self.owner)
        r = self._post(c)
        self.assertEqual(r.status_code, 302)
        inv = CustomerInvitation.objects.get(email='contact@fleet.com')
        self.assertFalse(inv.is_primary_contact)

    def test_invite_with_primary_flag_creates_primary_invitation(self):
        """Checkbox checked → invitation created with is_primary_contact=True."""
        c = Client()
        c.force_login(self.owner)
        r = self._post(c, {'is_primary_contact': '1'})
        self.assertEqual(r.status_code, 302)
        inv = CustomerInvitation.objects.get(email='contact@fleet.com')
        self.assertTrue(inv.is_primary_contact)

    def test_manager_can_send_invite(self):
        """Managers should be able to send invitations."""
        mgr, _ = make_manager(self.tenant, 'inv_mgr')
        c = Client()
        c.force_login(mgr)
        r = self._post(c)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(CustomerInvitation.objects.filter(email='contact@fleet.com').exists())

    def test_regular_tech_cannot_send_invite(self):
        """Regular techs should be blocked from sending invitations."""
        tech_user, _ = make_regular_tech(self.tenant, 'inv_tech')
        c = Client()
        c.force_login(tech_user)
        r = self._post(c)
        # Should redirect without creating invitation
        self.assertFalse(CustomerInvitation.objects.filter(email='contact@fleet.com').exists())

    def test_unauthenticated_cannot_send_invite(self):
        """Unauthenticated POST should redirect to login."""
        c = Client()
        r = self._post(c)
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r.url.lower())
        self.assertFalse(CustomerInvitation.objects.filter(email='contact@fleet.com').exists())

    def test_invite_missing_email_does_not_create_invitation(self):
        """Missing email should not create invitation."""
        c = Client()
        c.force_login(self.owner)
        r = c.post(self.url, {'first_name': 'Jane', 'last_name': 'Fleet'})
        self.assertFalse(CustomerInvitation.objects.filter(customer=self.customer).exists())

    def test_owner_cannot_invite_to_other_tenants_customer(self):
        """Owner should not be able to invite to a customer from another tenant."""
        _, other_tenant, _ = make_tenant('Other Glass', 'other_inv_owner')
        other_customer = Customer.objects.create(name='Other Fleet', tenant=other_tenant)
        c = Client()
        c.force_login(self.owner)
        r = c.post(f'/tech/customers/{other_customer.id}/invite/', {
            'email': 'leak@other.com',
            'first_name': 'Leak',
            'last_name': 'Test',
        })
        self.assertFalse(CustomerInvitation.objects.filter(email='leak@other.com').exists())


# ---------------------------------------------------------------------------
# set_primary_contact view
# ---------------------------------------------------------------------------

@override_settings(**TEST_SETTINGS)
class SetPrimaryContactTests(TestCase):
    """Tests for the set_primary_contact toggle view."""

    def setUp(self):
        self.owner, self.tenant, self.tech = make_tenant('Toggle Glass', 'toggle_owner')
        self.customer = Customer.objects.create(name='Toggle Fleet', tenant=self.tenant)

        self.primary_user, self.primary_cu = make_customer_user(
            self.customer, 'toggle_primary', is_primary=True
        )
        self.secondary_user, self.secondary_cu = make_customer_user(
            self.customer, 'toggle_secondary', is_primary=False
        )

    def _post(self, client, cu_id):
        url = f'/tech/customers/{self.customer.id}/portal-users/{cu_id}/set-primary/'
        return client.post(url)

    def test_owner_can_set_primary(self):
        """Owner can promote a non-primary to primary."""
        c = Client()
        c.force_login(self.owner)
        r = self._post(c, self.secondary_cu.id)
        self.assertEqual(r.status_code, 302)
        self.secondary_cu.refresh_from_db()
        self.assertTrue(self.secondary_cu.is_primary_contact)

    def test_old_primary_is_demoted(self):
        """When a new primary is set, the old primary loses the flag."""
        c = Client()
        c.force_login(self.owner)
        self._post(c, self.secondary_cu.id)
        self.primary_cu.refresh_from_db()
        self.assertFalse(self.primary_cu.is_primary_contact)

    def test_only_one_primary_at_a_time(self):
        """After toggling, exactly one CustomerUser for this customer is primary."""
        c = Client()
        c.force_login(self.owner)
        self._post(c, self.secondary_cu.id)
        primary_count = CustomerUser.objects.filter(
            customer=self.customer, is_primary_contact=True
        ).count()
        self.assertEqual(primary_count, 1)

    def test_setting_already_primary_is_idempotent(self):
        """Setting the existing primary as primary again should not break anything."""
        c = Client()
        c.force_login(self.owner)
        self._post(c, self.primary_cu.id)
        self.primary_cu.refresh_from_db()
        self.assertTrue(self.primary_cu.is_primary_contact)
        primary_count = CustomerUser.objects.filter(
            customer=self.customer, is_primary_contact=True
        ).count()
        self.assertEqual(primary_count, 1)

    def test_manager_can_set_primary(self):
        """Managers should also be able to toggle primary."""
        mgr, _ = make_manager(self.tenant, 'toggle_mgr')
        c = Client()
        c.force_login(mgr)
        r = self._post(c, self.secondary_cu.id)
        self.assertEqual(r.status_code, 302)
        self.secondary_cu.refresh_from_db()
        self.assertTrue(self.secondary_cu.is_primary_contact)

    def test_regular_tech_cannot_set_primary(self):
        """Regular techs should not be able to toggle primary contact."""
        tech_user, _ = make_regular_tech(self.tenant, 'toggle_tech')
        c = Client()
        c.force_login(tech_user)
        self._post(c, self.secondary_cu.id)
        self.secondary_cu.refresh_from_db()
        # Should NOT have changed
        self.assertFalse(self.secondary_cu.is_primary_contact)

    def test_unauthenticated_cannot_set_primary(self):
        """Unauthenticated POST should redirect to login."""
        c = Client()
        r = self._post(c, self.secondary_cu.id)
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r.url.lower())

    def test_cannot_set_primary_on_other_tenants_customer(self):
        """Owner from tenant A cannot set primary on tenant B's customer users."""
        _, other_tenant, _ = make_tenant('Other Toggle', 'other_toggle_owner')
        other_customer = Customer.objects.create(name='Other Fleet', tenant=other_tenant)
        _, other_cu = make_customer_user(other_customer, 'other_toggle_cu', is_primary=False)

        c = Client()
        c.force_login(self.owner)
        url = f'/tech/customers/{other_customer.id}/portal-users/{other_cu.id}/set-primary/'
        c.post(url)
        other_cu.refresh_from_db()
        # Should NOT have been promoted
        self.assertFalse(other_cu.is_primary_contact)

    def test_multiple_customers_primaries_are_independent(self):
        """Setting primary on customer A should not affect customer B's primary."""
        customer_b = Customer.objects.create(name='Fleet B', tenant=self.tenant)
        _, cu_b = make_customer_user(customer_b, 'fleet_b_primary', is_primary=True)

        c = Client()
        c.force_login(self.owner)
        # Toggle secondary on customer A
        self._post(c, self.secondary_cu.id)

        # Customer B's primary should be untouched
        cu_b.refresh_from_db()
        self.assertTrue(cu_b.is_primary_contact)


# ---------------------------------------------------------------------------
# Invite acceptance → primary flag honoured
# ---------------------------------------------------------------------------

@override_settings(**TEST_SETTINGS)
class InviteAcceptancePrimaryFlagTests(TestCase):
    """When a user accepts an invitation, is_primary_contact on the invitation
    should be honoured when creating the CustomerUser."""

    def setUp(self):
        self.owner, self.tenant, self.tech = make_tenant('Accept Glass', 'accept_owner')
        self.customer = Customer.objects.create(name='Accept Fleet', tenant=self.tenant)

    def _make_invite(self, email, is_primary=False):
        return CustomerInvitation.objects.create(
            customer=self.customer,
            email=email,
            first_name='New',
            last_name='User',
            token=secrets.token_urlsafe(32),
            invited_by=self.owner,
            status='pending',
            expires_at=timezone.now() + timedelta(days=7),
            is_primary_contact=is_primary,
        )

    def test_accepting_primary_invite_sets_primary_flag(self):
        """Accepting an invite marked is_primary_contact=True creates a primary CustomerUser."""
        invite = self._make_invite('decision@fleet.com', is_primary=True)
        c = Client()
        r = c.post(f'/app/invite/{invite.token}/', {
            'first_name': 'Decision',
            'last_name': 'Maker',
            'email': 'decision@fleet.com',
            'password': 'securepass123',
            'password_confirm': 'securepass123',
        })
        self.assertEqual(r.status_code, 302)
        new_user = User.objects.get(email='decision@fleet.com')
        cu = CustomerUser.objects.get(user=new_user)
        self.assertTrue(cu.is_primary_contact)

    def test_accepting_non_primary_invite_does_not_set_primary(self):
        """Accepting an invite marked is_primary_contact=False creates a non-primary CustomerUser."""
        invite = self._make_invite('team@fleet.com', is_primary=False)
        c = Client()
        r = c.post(f'/app/invite/{invite.token}/', {
            'first_name': 'Team',
            'last_name': 'Member',
            'email': 'team@fleet.com',
            'password': 'securepass123',
            'password_confirm': 'securepass123',
        })
        self.assertEqual(r.status_code, 302)
        new_user = User.objects.get(email='team@fleet.com')
        cu = CustomerUser.objects.get(user=new_user)
        self.assertFalse(cu.is_primary_contact)

    def test_accepting_primary_invite_demotes_existing_primary(self):
        """If a primary already exists and new invite is marked primary, old one is demoted."""
        # Existing primary
        _, existing_cu = make_customer_user(self.customer, 'existing_primary', is_primary=True)

        invite = self._make_invite('new_decision@fleet.com', is_primary=True)
        c = Client()
        c.post(f'/app/invite/{invite.token}/', {
            'first_name': 'New',
            'last_name': 'Decision',
            'email': 'new_decision@fleet.com',
            'password': 'securepass123',
            'password_confirm': 'securepass123',
        })
        existing_cu.refresh_from_db()
        self.assertFalse(existing_cu.is_primary_contact)

        primary_count = CustomerUser.objects.filter(
            customer=self.customer, is_primary_contact=True
        ).count()
        self.assertEqual(primary_count, 1)


# ---------------------------------------------------------------------------
# Fix 1 regression: is_primary_contact on CustomerForm (create_customer view)
# ---------------------------------------------------------------------------

@override_settings(**TEST_SETTINGS)
class CreateCustomerPrimaryContactTests(TestCase):
    """Regression tests for the is_primary_contact checkbox on the customer
    creation form (create_customer view)."""

    def setUp(self):
        self.owner, self.tenant, self.tech = make_tenant('Create Glass', 'create_owner')
        self.url = '/tech/customers/create/'

    def _login(self):
        c = Client()
        c.force_login(self.owner)
        session = c.session
        session['tenant_id'] = self.tenant.id
        session.save()
        return c

    def test_form_has_is_primary_contact_field(self):
        """CustomerForm should expose is_primary_contact field."""
        from apps.technician_portal.forms import CustomerForm
        form = CustomerForm(tenant=self.tenant)
        self.assertIn('is_primary_contact', form.fields)

    def test_is_primary_contact_defaults_to_true(self):
        """is_primary_contact should default to True (first contact is usually primary)."""
        from apps.technician_portal.forms import CustomerForm
        form = CustomerForm(tenant=self.tenant)
        self.assertTrue(form.fields['is_primary_contact'].initial)

    def test_create_customer_with_primary_invitation(self):
        """Creating a customer with invitation and is_primary_contact checked
        should set is_primary_contact=True on the invitation."""
        c = self._login()
        r = c.post(self.url, {
            'name': 'Primary Fleet',
            'invite_email': 'primary@fleet.com',
            'invite_first_name': 'John',
            'invite_last_name': 'Fleet',
            'send_invitation': 'on',
            'is_primary_contact': 'on',
        })
        self.assertEqual(r.status_code, 302)
        inv = CustomerInvitation.objects.get(email='primary@fleet.com')
        self.assertTrue(inv.is_primary_contact)

    def test_create_customer_without_primary_flag(self):
        """Creating a customer with invitation but is_primary_contact unchecked
        should set is_primary_contact=False on the invitation."""
        c = self._login()
        r = c.post(self.url, {
            'name': 'Non-Primary Fleet',
            'invite_email': 'nonprimary@fleet.com',
            'invite_first_name': 'Jane',
            'invite_last_name': 'Fleet',
            'send_invitation': 'on',
            # is_primary_contact NOT submitted (unchecked)
        })
        self.assertEqual(r.status_code, 302)
        inv = CustomerInvitation.objects.get(email='nonprimary@fleet.com')
        self.assertFalse(inv.is_primary_contact)

    def test_create_customer_template_renders_primary_checkbox(self):
        """GET on create_customer should render the is_primary_contact checkbox."""
        c = self._login()
        r = c.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'is_primary_contact')
        self.assertContains(r, 'Set as primary contact')


# ---------------------------------------------------------------------------
# Fix 2 regression: default technician from customer.primary_technician
# ---------------------------------------------------------------------------

@override_settings(**TEST_SETTINGS)
class DefaultTechnicianOnRepairFormTests(TestCase):
    """Regression tests for pre-selecting the customer's primary_technician
    on the repair creation form."""

    def setUp(self):
        self.owner, self.tenant, self.tech = make_tenant('Tech Glass', 'tech_owner')
        # Make owner a staff user to see the technician dropdown
        self.owner.is_staff = True
        self.owner.save()
        self.tech2_user = User.objects.create_user(
            'tech2', 'tech2@test.com', 'testpass123',
            first_name='Second', last_name='Tech'
        )
        TenantMembership.objects.create(user=self.tech2_user, tenant=self.tenant, role='technician')
        self.tech2 = Technician.objects.create(
            user=self.tech2_user, tenant=self.tenant, is_manager=False, can_repair=True
        )
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, primary_technician=self.tech2
        )

    def _login(self):
        c = Client()
        c.force_login(self.owner)
        session = c.session
        session['tenant_id'] = self.tenant.id
        session.save()
        return c

    def test_repair_form_preselects_primary_technician(self):
        """GET /tech/repairs/create/?customer_id=X should pre-select
        the customer's primary_technician."""
        c = self._login()
        r = c.get(f'/tech/repairs/create/?customer_id={self.customer.id}')
        self.assertEqual(r.status_code, 200)
        form = r.context['form']
        self.assertEqual(form.initial.get('technician'), self.tech2.id)

    def test_repair_form_preselects_customer(self):
        """GET /tech/repairs/create/?customer_id=X should pre-select the customer."""
        c = self._login()
        r = c.get(f'/tech/repairs/create/?customer_id={self.customer.id}')
        self.assertEqual(r.status_code, 200)
        form = r.context['form']
        self.assertEqual(form.initial.get('customer'), self.customer.id)

    def test_repair_form_no_customer_id_no_initial(self):
        """GET /tech/repairs/create/ without customer_id should have no initial values."""
        c = self._login()
        r = c.get('/tech/repairs/create/')
        self.assertEqual(r.status_code, 200)
        form = r.context['form']
        self.assertFalse(form.initial.get('technician'))

    def test_repair_form_invalid_customer_id_ignored(self):
        """GET with non-existent customer_id should not crash."""
        c = self._login()
        r = c.get('/tech/repairs/create/?customer_id=99999')
        self.assertEqual(r.status_code, 200)
        form = r.context['form']
        self.assertFalse(form.initial.get('technician'))

    def test_repair_form_customer_without_primary_tech(self):
        """Customer with no primary_technician should not pre-select technician."""
        customer2 = Customer.objects.create(name='No Tech Fleet', tenant=self.tenant)
        c = self._login()
        r = c.get(f'/tech/repairs/create/?customer_id={customer2.id}')
        self.assertEqual(r.status_code, 200)
        form = r.context['form']
        self.assertEqual(form.initial.get('customer'), customer2.id)
        self.assertIsNone(form.initial.get('technician'))


# ---------------------------------------------------------------------------
# Fix 3 regression: notification preference links in email templates
# ---------------------------------------------------------------------------

class NotificationPreferenceLinksTests(TestCase):
    """Regression tests verifying email templates use correct notification
    preference URLs."""

    def test_customer_facing_templates_use_app_preferences_url(self):
        """Customer-facing email templates should link to /app/notifications/preferences/."""
        from django.template.loader import render_to_string
        customer_templates = [
            'emails/notifications/repair_approved.html',
            'emails/notifications/repair_denied.html',
            'emails/notifications/repair_completed.html',
            'emails/notifications/repair_pending_approval.html',
            'emails/notifications/repair_in_progress.html',
            'emails/notifications/repair_request_received.html',
            'emails/notifications/batch_approved.html',
            'emails/notifications/payment_received.html',
        ]
        for template_name in customer_templates:
            rendered = render_to_string(template_name, {
                'branding': type('obj', (object,), {
                    'primary_color': '#000', 'text_color': '#000',
                    'heading_font': 'Arial', 'body_font': 'Arial',
                    'warning_color': '#f00', 'button_border_radius': 4,
                    'logo_url': '', 'company_name': 'Test',
                })(),
            })
            self.assertIn('/app/notifications/preferences/', rendered,
                          f'{template_name} should link to /app/notifications/preferences/')
            self.assertNotIn('/app/settings/notifications/', rendered,
                             f'{template_name} should NOT use old /app/settings/notifications/ URL')

    def test_tech_facing_templates_use_tech_preferences_url(self):
        """Tech-facing email templates should link to /tech/notifications/preferences/."""
        from django.template.loader import render_to_string
        tech_templates = [
            'emails/notifications/repair_assigned.html',
            'emails/notifications/repair_request_submitted.html',
            'emails/notifications/repair_reassigned_away.html',
        ]
        for template_name in tech_templates:
            rendered = render_to_string(template_name, {
                'branding': type('obj', (object,), {
                    'primary_color': '#000', 'text_color': '#000',
                    'heading_font': 'Arial', 'body_font': 'Arial',
                    'warning_color': '#f00', 'button_border_radius': 4,
                    'logo_url': '', 'company_name': 'Test',
                })(),
            })
            self.assertIn('/tech/notifications/preferences/', rendered,
                          f'{template_name} should link to /tech/notifications/preferences/')
            self.assertNotIn('/tech/settings/notifications/', rendered,
                             f'{template_name} should NOT use old /tech/settings/notifications/ URL')
