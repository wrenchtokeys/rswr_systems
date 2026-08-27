"""
Fieldops N1 — assignment notifications that actually deliver.

Covers the acceptance criteria in docs/strategy/FIELD_OPS_SESSIONS.md §N1:
assigning any job (Repair or Replacement, previously assigned or not, via any
write path) sends the assigned tech the repair_assigned email and rings the
real notification bell (core.Notification); reassignment notifies both techs;
bulk reassign sends one summary per tech; opt-out is honored; no customer is
ever notified by an assignment event.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.technician_portal.models import (
    Repair, Replacement, Technician, TechnicianNotification,
)
from apps.technician_portal.services.assignments import assign_job
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer
from core.models.notification import Notification

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_tenant(name, owner_username):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    user = User.objects.create_user(
        owner_username, f'{owner_username}@test.com', 'testpass123',
        first_name='Test', last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user,
        subscription_plan=plan,
        plan='trial',
        subscription_status='trialing',
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


def tech_notifications(tech, template_name=None):
    ct = ContentType.objects.get_for_model(tech)
    qs = Notification.objects.filter(recipient_type=ct, recipient_id=tech.id)
    if template_name:
        qs = qs.filter(template__name=template_name)
    return qs


@override_settings(**TEST_SETTINGS)
class AssignmentNotificationTests(TestCase):

    def setUp(self):
        self.owner, self.tenant = make_tenant('N1 Shop', 'n1_owner')
        self.client = Client()
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        def make_tech(username, first):
            u = User.objects.create_user(
                username, f'{username}@test.com', 'testpass123',
                first_name=first, last_name='Tech',
            )
            return Technician.objects.create(
                user=u, tenant=self.tenant, is_active=True,
                can_repair=True, can_replace=True,
            )

        self.tech_a = make_tech('n1_tech_a', 'Alice')
        self.tech_b = make_tech('n1_tech_b', 'Bob')
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)

    def _reset(self):
        """Clear notification side effects produced while arranging fixtures."""
        mail.outbox = []
        Notification.objects.all().delete()
        TechnicianNotification.objects.all().delete()

    def _make_repair(self, technician, status='APPROVED', **kwargs):
        # technician is NOT NULL at the DB level — every job always holds a
        # tech; "unassigned" in the product sense means a REQUESTED job with
        # its provisional fallback tech.
        repair = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=technician,
            unit_number='101',
            queue_status=status,
            **kwargs,
        )
        return repair

    def _emails_to(self, tech):
        addr = tech.user.email
        return [m for m in mail.outbox if addr in m.to]

    # ------------------------------------------------------------------
    # Path 1: assign_repair view (REQUESTED → APPROVED). The provisional
    # tech is often the SAME tech being confirmed — the old signal saw no
    # change and stayed silent; force_notify_new fixes that.
    def test_assign_requested_repair_notifies_tech(self):
        repair = self._make_repair(self.tech_a, status='REQUESTED')
        self._reset()

        resp = self.client.post(
            f'/tech/repairs/{repair.id}/assign/',
            {'technician_id': self.tech_a.id},
        )
        self.assertEqual(resp.status_code, 302)

        repair.refresh_from_db()
        self.assertEqual(repair.technician, self.tech_a)
        self.assertEqual(repair.queue_status, 'APPROVED')

        # Bell (core.Notification), exactly once — no signal double-fire
        notifs = tech_notifications(self.tech_a, 'repair_assigned')
        self.assertEqual(notifs.count(), 1)

        # Email delivered despite email_verified=False (staff default-ON)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('New Repair Assignment', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ['n1_tech_a@test.com'])
        # Rendered from flat context — unit number must actually appear
        self.assertIn('101', mail.outbox[0].body)
        self.assertIn('Fleet Co', mail.outbox[0].body)

        # Dashboard row kept
        self.assertTrue(TechnicianNotification.objects.filter(
            technician=self.tech_a, repair=repair).exists())

    # ------------------------------------------------------------------
    # Path 2: direct save (form-edit fallback — no view helper involved)
    def test_reassigning_via_bare_save_notifies_both(self):
        repair = self._make_repair(self.tech_a, status='APPROVED')
        self._reset()

        repair.technician = self.tech_b
        repair.save()

        self.assertEqual(tech_notifications(self.tech_b, 'repair_assigned').count(), 1)
        self.assertEqual(
            tech_notifications(self.tech_a, 'repair_reassigned_away').count(), 1)
        self.assertEqual(len(self._emails_to(self.tech_b)), 1)
        self.assertEqual(len(self._emails_to(self.tech_a)), 1)

    # ------------------------------------------------------------------
    # Path 3: admin_reassign_repair — notifies new AND old tech
    def test_admin_reassign_notifies_both_techs(self):
        repair = self._make_repair(self.tech_a, status='APPROVED')
        TechnicianNotification.objects.create(
            technician=self.tech_a, repair=repair, message='old', read=False,
        )
        mail.outbox = []
        Notification.objects.all().delete()

        resp = self.client.post(
            f'/tech/repairs/{repair.id}/reassign/',
            {'technician_id': self.tech_b.id},
        )
        self.assertEqual(resp.status_code, 302)

        self.assertEqual(tech_notifications(self.tech_b, 'repair_assigned').count(), 1)
        self.assertEqual(
            tech_notifications(self.tech_a, 'repair_reassigned_away').count(), 1)
        # Both emails out (assigned + reassigned-away)
        recipients = sorted(sum((m.to for m in mail.outbox), []))
        self.assertEqual(
            recipients, ['n1_tech_a@test.com', 'n1_tech_b@test.com'])
        # Old tech's stale unread rows were marked read
        self.assertFalse(TechnicianNotification.objects.filter(
            technician=self.tech_a, repair=repair, read=False,
            message='old').exists())

    # ------------------------------------------------------------------
    # Path 4: bulk reassign — ONE summary per affected tech, not one per job
    def test_bulk_reassign_sends_single_summary_per_tech(self):
        r1 = self._make_repair(self.tech_a, status='APPROVED')
        r2 = self._make_repair(self.tech_a, status='APPROVED')
        self._reset()

        resp = self.client.post('/tech/repairs/bulk-reassign/', {
            'repair_ids': [r1.id, r2.id],
            'technician_id': self.tech_b.id,
        })
        self.assertEqual(resp.status_code, 302)

        # New tech: exactly one summary, no per-job core notifications
        self.assertEqual(
            tech_notifications(self.tech_b, 'jobs_bulk_assigned').count(), 1)
        self.assertEqual(
            tech_notifications(self.tech_b, 'repair_assigned').count(), 0)
        # Old tech: one summary
        self.assertEqual(
            tech_notifications(self.tech_a, 'jobs_bulk_reassigned_away').count(), 1)
        self.assertEqual(
            tech_notifications(self.tech_a, 'repair_reassigned_away').count(), 0)
        # One email each
        self.assertEqual(len(mail.outbox), 2)
        summary = tech_notifications(self.tech_b, 'jobs_bulk_assigned').first()
        self.assertIn('2 jobs', summary.title)
        # Per-repair dashboard rows preserved
        self.assertEqual(TechnicianNotification.objects.filter(
            technician=self.tech_b).count(), 2)

    # ------------------------------------------------------------------
    # Path 5: auto-assignment service
    def test_auto_assign_notifies_tech(self):
        from apps.tenants.services.assignment_service import auto_assign_repair
        self.tenant.assignment_strategy = 'round_robin'
        self.tenant.save()
        # Round-robin anchors on the last job it assigned — never on the one
        # in hand (CODE-278) — so lay a prior job down for tech_a first. The
        # new repair then rotates to the next eligible tech: deterministic
        # tech_b, whichever tech it happens to be holding provisionally.
        self._make_repair(self.tech_a, status='APPROVED')
        repair = self._make_repair(self.tech_a, status='APPROVED')
        self._reset()

        assigned = auto_assign_repair(repair)
        self.assertEqual(assigned, self.tech_b)
        self.assertEqual(
            tech_notifications(self.tech_b, 'repair_assigned').count(), 1)
        self.assertEqual(len(self._emails_to(self.tech_b)), 1)

    # ------------------------------------------------------------------
    # Replacement coverage (previously zero assignment signals)
    def test_replacement_assignment_notifies(self):
        replacement = Replacement.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech_a,
            unit_number='202',
            queue_status='APPROVED',
        )
        self._reset()

        replacement.technician = self.tech_b
        replacement.save()

        notifs = tech_notifications(self.tech_b, 'repair_assigned')
        self.assertEqual(notifs.count(), 1)
        # Deep link goes to the replacement detail page, not a repair URL
        self.assertIn('/tech/replacement/', notifs.first().action_url)
        emails = self._emails_to(self.tech_b)
        self.assertEqual(len(emails), 1)
        self.assertIn('REPLACEMENT', emails[0].body.upper())

    def test_replacement_requested_stays_silent_until_approved(self):
        """Customer-requested replacement: no 'assigned' while REQUESTED;
        the notification fires when the job leaves REQUESTED."""
        replacement = Replacement.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech_a,
            unit_number='303',
            queue_status='REQUESTED',
        )
        self._reset()

        # Auto-assign moves it while still REQUESTED → silent
        replacement.technician = self.tech_b
        replacement.save()
        self.assertEqual(tech_notifications(self.tech_b).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

        # Approval crosses REQUESTED → APPROVED → tech hears now
        replacement.queue_status = 'APPROVED'
        replacement.save()
        self.assertEqual(
            tech_notifications(self.tech_b, 'repair_assigned').count(), 1)
        self.assertEqual(len(self._emails_to(self.tech_b)), 1)

    # ------------------------------------------------------------------
    # Customer-request auto-accept path (rule B for repairs)
    def test_requested_repair_accept_notifies_final_tech(self):
        repair = self._make_repair(self.tech_a, status='REQUESTED')
        self._reset()

        repair.queue_status = 'APPROVED'
        repair.save()

        self.assertEqual(
            tech_notifications(self.tech_a, 'repair_assigned').count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    # ------------------------------------------------------------------
    # Preferences
    def test_email_opt_out_still_rings_bell(self):
        from core.models.notification_preferences import (
            TechnicianNotificationPreference,
        )
        prefs, _ = TechnicianNotificationPreference.objects.get_or_create(
            technician=self.tech_a)
        prefs.receive_email_notifications = False
        prefs.save()

        repair = self._make_repair(self.tech_b, status='APPROVED')
        self._reset()

        assign_job(repair, self.tech_a, assigned_by=self.owner)

        self.assertEqual(
            tech_notifications(self.tech_a, 'repair_assigned').count(), 1)
        self.assertEqual(len(self._emails_to(self.tech_a)), 0)

    # ------------------------------------------------------------------
    # Self-action suppression
    def test_actor_not_notified_about_own_assignment(self):
        repair = self._make_repair(self.tech_b, status='APPROVED')
        self._reset()

        # tech_a grabs the job themselves — the old tech still hears,
        # tech_a doesn't get an email about their own action.
        assign_job(repair, self.tech_a, assigned_by=self.tech_a.user)

        self.assertEqual(tech_notifications(self.tech_a).count(), 0)
        self.assertEqual(len(self._emails_to(self.tech_a)), 0)
        self.assertEqual(
            tech_notifications(self.tech_b, 'repair_reassigned_away').count(), 1)

    def test_self_created_job_stays_silent(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech_a,
            unit_number='404',
            queue_status='APPROVED',
        )
        repair._assignment_actor_user_id = self.tech_a.user_id
        self._reset()
        repair.save()

        self.assertEqual(tech_notifications(self.tech_a).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_completed_walkin_creation_stays_silent(self):
        self._reset()
        self._make_repair(self.tech_a, status='COMPLETED')
        self.assertEqual(
            tech_notifications(self.tech_a, 'repair_assigned').count(), 0)

    # ------------------------------------------------------------------
    # No customer ever hears about assignment events
    def test_customers_never_notified_by_assignment(self):
        from apps.customer_portal.models import CustomerUser
        cu_user = User.objects.create_user(
            'n1_customer', 'customer@fleet.test', 'testpass123')
        CustomerUser.objects.create(
            user=cu_user, customer=self.customer, is_primary_contact=True)

        repair = self._make_repair(self.tech_a, status='APPROVED')
        self._reset()

        assign_job(repair, self.tech_b, assigned_by=self.owner)

        customer_ct = ContentType.objects.get_for_model(self.customer)
        self.assertEqual(Notification.objects.filter(
            recipient_type=customer_ct).count(), 0)
        for message in mail.outbox:
            self.assertNotIn('customer@fleet.test', message.to)

    # ------------------------------------------------------------------
    # Channel plumbing
    def test_repair_assigned_channels_include_email(self):
        from core.models.notification_template import NotificationTemplate
        tpl = NotificationTemplate.objects.get(name='repair_assigned')
        self.assertEqual(tpl.channels_override, ['in_app', 'email', 'sms'])

        repair = self._make_repair(self.tech_b, status='APPROVED')
        self._reset()
        assign_job(repair, self.tech_a, assigned_by=self.owner)
        notif = tech_notifications(self.tech_a, 'repair_assigned').first()
        self.assertIn('email', notif.get_delivery_channels())
        self.assertIn('in_app', notif.get_delivery_channels())
