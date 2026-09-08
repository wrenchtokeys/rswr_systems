"""
Quotes (IMPROVEMENT_SESSIONS B3): shop creates a priced quote → customer gets a
branded email → accepts on the public link or in the portal → the jobs are
created at the quoted price, locked → declined and expired quotes stay
visible and never become jobs.

Guard module: the acceptance criteria in the session doc, one test each, plus
the tenant-isolation and price-lock invariants that make the feature safe.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.billing.models import BillingConfig, TaxRate
from apps.billing.quote_models import Quote, QuoteLineItem
from apps.billing.services import quote_service
from apps.billing.services.quote_service import QuoteError
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import JobCharge, Repair, Replacement, Technician
from core.models import Customer
from tests.test_e2e_today import make_tenant

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'BASE_URL': 'https://rssystems.io',
}


def shop_client(user, tenant):
    client = Client()
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()
    return client


def line_post(lines, **header):
    """Build the POST the quote form sends. `lines` = list of dicts."""
    data = {
        'customer': header.get('customer'),
        'valid_until': header.get('valid_until', (timezone.localdate() + timedelta(days=30)).isoformat()),
        'unit_number': header.get('unit_number', ''),
        'vehicle_year': header.get('vehicle_year', ''),
        'vehicle_make': header.get('vehicle_make', ''),
        'vehicle_model': header.get('vehicle_model', ''),
        'notes': header.get('notes', ''),
        'internal_notes': '',
        'then': header.get('then', 'save'),
    }
    if header.get('charge_tax', True):
        data['charge_tax'] = '1'
    for key in ('line_type', 'line_desc', 'line_unit', 'line_qty', 'line_price', 'line_damage', 'line_glass'):
        data[key] = []
    for li in lines:
        data['line_type'].append(li.get('type', 'REPAIR'))
        data['line_desc'].append(li.get('desc', 'Windshield chip repair'))
        data['line_unit'].append(li.get('unit', ''))
        data['line_qty'].append(str(li.get('qty', 1)))
        data['line_price'].append(li.get('price', ''))
        data['line_damage'].append(li.get('damage', ''))
        data['line_glass'].append(li.get('glass', ''))
    return data


@override_settings(**TEST_SETTINGS)
class QuoteTestCase(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant('Quote Shop', 'quote_owner')
        self.tenant.services_offered = 'both'
        self.tenant.save()
        self.tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True, is_manager=True,
            can_repair=True, can_replace=True,
        )
        self.fleet = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, customer_type='FLEET', email='fleet@example.com',
        )
        self.person = Customer.objects.create(
            name='Pat Person', tenant=self.tenant, customer_type='RETAIL', email='pat@example.com',
        )
        self.client = shop_client(self.owner, self.tenant)

    # --- helpers -------------------------------------------------------------

    def make_quote(self, customer=None, lines=None, status='DRAFT', **kwargs):
        customer = customer or self.fleet
        quote = Quote.objects.create(
            tenant=self.tenant,
            quote_number=BillingConfig.allocate_quote_number(self.tenant),
            customer=customer,
            created_by=self.owner,
            status=status,
            valid_until=kwargs.pop('valid_until', timezone.localdate() + timedelta(days=30)),
            unit_number=kwargs.pop('unit_number', '' if customer.is_individual else '4127'),
            **kwargs,
        )
        for i, li in enumerate(lines or [dict(desc='Windshield chip repair', price=Decimal('50.00'))]):
            QuoteLineItem.objects.create(
                quote=quote,
                service_type=li.get('type', 'REPAIR'),
                description=li['desc'],
                quantity=li.get('qty', 1),
                unit_price=li['price'],
                amount=li['price'] * li.get('qty', 1),
                taxable=li.get('taxable', True),
                glass_position=li.get('glass', ''),
                sort_order=i,
            )
        quote_service.recalculate_totals(quote)
        return quote

    def public_url(self, quote):
        return f"/quote/{quote.id}/{quote_service.public_token(quote.id)}/"

    # --- numbering -----------------------------------------------------------

    def test_quote_numbers_are_sequential_per_tenant_and_skip_taken(self):
        self.assertEqual(BillingConfig.allocate_quote_number(self.tenant), 'Q-1001')
        self.assertEqual(BillingConfig.allocate_quote_number(self.tenant), 'Q-1002')
        config = BillingConfig.get_for_tenant(self.tenant)
        config.next_quote_number = 1001  # owner reset below existing quotes
        config.save()
        Quote.objects.create(tenant=self.tenant, quote_number='Q-1001', customer=self.fleet,
                             valid_until=timezone.localdate())
        self.assertEqual(BillingConfig.allocate_quote_number(self.tenant), 'Q-1002')
        _other_owner, other = make_tenant('Other Shop', 'other_owner')
        self.assertEqual(BillingConfig.allocate_quote_number(other), 'Q-1001')

    # --- create --------------------------------------------------------------

    def test_create_quote_from_form_uses_shop_price_for_blank_repair_line(self):
        resp = self.client.post('/quotes/new/', line_post(
            [dict(type='REPAIR', desc='Chip repair', price=''),
             dict(type='OTHER', desc='Trip charge', price='25')],
            customer=self.fleet.id, unit_number='4127',
        ))
        self.assertEqual(resp.status_code, 302)
        quote = Quote.objects.get(tenant=self.tenant)
        self.assertEqual(quote.status, 'DRAFT')
        self.assertEqual(quote.quote_number, 'Q-1001')
        repair_line = quote.line_items.get(service_type='REPAIR')
        self.assertEqual(repair_line.unit_price, Decimal('50.00'))  # tenant default tier 1
        self.assertEqual(quote.subtotal, Decimal('75.00'))
        self.assertEqual(quote.total, Decimal('75.00'))  # no tax configured
        self.assertEqual(quote.created_by, self.owner)

    def test_non_manager_cannot_quote_a_custom_repair_price(self):
        tech_user = User.objects.create_user('quote_tech', 't@test.com', 'pw', first_name='Tee')
        Technician.objects.create(user=tech_user, tenant=self.tenant, is_active=True, is_manager=False)
        from apps.tenants.models import TenantMembership
        TenantMembership.objects.create(tenant=self.tenant, user=tech_user, role='technician')
        client = shop_client(tech_user, self.tenant)
        resp = client.post('/quotes/new/', line_post(
            [dict(type='REPAIR', desc='Chip repair', price='35.00')], customer=self.fleet.id,
        ))
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertContains(resp, 'Only a manager can quote a different price')
        self.assertFalse(Quote.objects.exists())
        # Blank works — the shop price fills in.
        resp = client.post('/quotes/new/', line_post(
            [dict(type='REPAIR', desc='Chip repair', price='')], customer=self.fleet.id,
        ))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Quote.objects.get().line_items.get().unit_price, Decimal('50.00'))

    def test_quote_needs_a_job_line(self):
        resp = self.client.post('/quotes/new/', line_post(
            [dict(type='OTHER', desc='Trip charge', price='25')], customer=self.fleet.id,
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'needs at least one repair or replacement line')
        self.assertFalse(Quote.objects.exists())

    def test_individual_quote_never_stores_a_unit_number(self):
        resp = self.client.post('/quotes/new/', line_post(
            [dict(type='REPAIR', desc='Chip repair', price='')],
            customer=self.person.id, unit_number='Silver Camry',
            vehicle_year='2022', vehicle_make='Toyota', vehicle_model='Camry',
        ))
        self.assertEqual(resp.status_code, 302)
        quote = Quote.objects.get()
        self.assertEqual(quote.unit_number, '')
        self.assertEqual(quote.get_vehicle_identifier(), '2022 Toyota Camry')
        self.assertEqual(quote.vehicle_column_label, 'Vehicle')

    def test_tax_is_frozen_on_the_quote(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = True
        config.save()
        TaxRate.objects.create(tenant=self.tenant, city='Little Rock', state='AR',
                               state_rate=Decimal('10.000'), is_active=True)
        quote = self.make_quote(lines=[dict(desc='Chip repair', price=Decimal('50.00'))])
        self.assertEqual(quote.tax_amount, Decimal('5.00'))
        self.assertEqual(quote.total, Decimal('55.00'))
        untaxed = self.make_quote(lines=[dict(desc='Chip repair', price=Decimal('50.00'))], no_tax=True)
        self.assertEqual(untaxed.tax_amount, Decimal('0.00'))
        self.assertEqual(untaxed.total, Decimal('50.00'))

    # --- send ----------------------------------------------------------------

    def test_send_emails_branded_quote_with_public_link_and_marks_sent(self):
        quote = self.make_quote()
        resp = self.client.post(f'/quotes/{quote.id}/send/', {'to_email': ''})
        self.assertEqual(resp.status_code, 302)
        quote.refresh_from_db()
        self.assertEqual(quote.status, 'SENT')
        self.assertEqual(quote.sent_to_email, 'fleet@example.com')
        self.assertIsNotNone(quote.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['fleet@example.com'])
        self.assertIn('Your quote from Quote Shop', msg.subject)
        self.assertIn('$50.00', msg.subject)
        self.assertIn('Quote Shop via RS Systems', msg.from_email)
        self.assertIn(quote_service.public_url(quote), msg.body)
        html = msg.alternatives[0][0]
        self.assertIn(quote_service.public_url(quote), html)
        self.assertIn('Q-1001', html)

    def test_send_without_an_email_on_file_is_refused(self):
        self.fleet.email = None
        self.fleet.save()
        quote = self.make_quote()
        with self.assertRaises(QuoteError):
            quote_service.send_quote(quote)
        quote.refresh_from_db()
        self.assertEqual(quote.status, 'DRAFT')
        self.assertEqual(len(mail.outbox), 0)

    # --- public link ---------------------------------------------------------

    def test_public_page_renders_and_get_changes_nothing(self):
        quote = self.make_quote(status='SENT')
        resp = self.client.get(self.public_url(quote))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Q-1001')
        self.assertContains(resp, 'Accept quote')
        quote.refresh_from_db()
        self.assertEqual(quote.status, 'SENT')
        self.assertEqual(Repair.objects.count(), 0)

    def test_public_page_rejects_a_bad_token(self):
        quote = self.make_quote(status='SENT')
        resp = Client().get(f'/quote/{quote.id}/0000000000000000000000000000dead/')
        self.assertEqual(resp.status_code, 404)
        # an invoice-style token for the same id must not open a quote either
        from rs_systems.views import generate_payment_token
        resp = Client().get(f'/quote/{quote.id}/{generate_payment_token(quote.id)}/')
        self.assertEqual(resp.status_code, 404)

    def test_accepting_on_the_link_creates_approved_jobs_at_the_quoted_price(self):
        quote = self.make_quote(status='SENT', lines=[
            dict(type='REPAIR', desc='Chip repair', price=Decimal('42.00'), qty=2),
            dict(type='REPLACEMENT', desc='Windshield replacement', price=Decimal('300.00'), glass='WINDSHIELD'),
            dict(type='OTHER', desc='Trip charge', price=Decimal('25.00')),
        ])
        anon = Client()
        resp = anon.post(self.public_url(quote) + 'respond/', {'action': 'accept', 'name': 'Sam Fleet'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "you're on the schedule")

        quote.refresh_from_db()
        self.assertEqual(quote.status, 'ACCEPTED')
        self.assertEqual(quote.accepted_via, 'link')
        self.assertEqual(quote.responded_by_name, 'Sam Fleet')

        repairs = Repair.objects.filter(quote=quote).order_by('id')
        self.assertEqual(repairs.count(), 2)
        for r in repairs:
            self.assertEqual(r.queue_status, 'APPROVED')
            self.assertEqual(r.cost, Decimal('42.00'))       # not the $50 tier-1 price
            self.assertEqual(r.cost_override, Decimal('42.00'))
            self.assertEqual(r.customer, self.fleet)
            self.assertEqual(r.unit_number, '4127')
            self.assertEqual(r.tenant, self.tenant)
        repl = Replacement.objects.get(quote=quote)
        self.assertEqual(repl.cost, Decimal('300.00'))
        self.assertEqual(repl.queue_status, 'APPROVED')
        self.assertEqual(repl.glass_position, 'WINDSHIELD')

        charge = JobCharge.objects.get(tenant=self.tenant)
        self.assertEqual(charge.amount, Decimal('25.00'))
        self.assertEqual(charge.repair, repairs.first())

        # second click on the same link does not double-create
        resp = anon.post(self.public_url(quote) + 'respond/', {'action': 'accept', 'name': 'Sam Fleet'})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(Repair.objects.filter(quote=quote).count(), 2)

    def test_quoted_price_survives_progressive_pricing(self):
        """Quote says $42; by the time the work happens this would be repair #3
        on the unit at $35. The job keeps $42 — the quote locked it."""
        from apps.technician_portal.models import UnitRepairCount
        UnitRepairCount.objects.create(tenant=self.tenant, customer=self.fleet, unit_number='4127', repair_count=2)
        quote = self.make_quote(status='SENT', lines=[dict(desc='Chip repair', price=Decimal('42.00'))])
        jobs = quote_service.accept_quote(quote, via='link', actor_name='x')
        self.assertEqual(jobs[0].cost, Decimal('42.00'))

    def test_quoted_price_survives_an_account_discount(self):
        self.fleet.account_discount_percentage = Decimal('10.00')
        self.fleet.save()
        quote = self.make_quote(status='SENT', lines=[dict(desc='Chip repair', price=Decimal('45.00'))])
        jobs = quote_service.accept_quote(quote, via='link', actor_name='x')
        self.assertEqual(jobs[0].cost, Decimal('45.00'))
        self.assertEqual(jobs[0].cost_override, Decimal('50.00'))  # backed out so save() lands on 45

    def test_expired_quote_cannot_be_accepted(self):
        quote = self.make_quote(status='SENT', valid_until=timezone.localdate() - timedelta(days=1))
        self.assertTrue(quote.is_expired)
        self.assertEqual(quote.effective_status, 'EXPIRED')
        resp = Client().get(self.public_url(quote))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'This quote has expired')
        self.assertNotContains(resp, 'Accept quote')
        resp = Client().post(self.public_url(quote) + 'respond/', {'action': 'accept', 'name': 'Sam'})
        self.assertEqual(resp.status_code, 409)
        quote.refresh_from_db()
        self.assertEqual(quote.status, 'EXPIRED')
        self.assertEqual(Repair.objects.count(), 0)

    def test_declining_on_the_link_creates_nothing(self):
        quote = self.make_quote(status='SENT')
        resp = Client().post(self.public_url(quote) + 'respond/',
                             {'action': 'decline', 'name': 'Sam', 'reason': 'Too much'})
        self.assertEqual(resp.status_code, 200)
        quote.refresh_from_db()
        self.assertEqual(quote.status, 'DECLINED')
        self.assertEqual(quote.decline_reason, 'Too much')
        self.assertEqual(Repair.objects.count(), 0)
        self.assertEqual(quote.job_count, 0)

    def test_declined_and_expired_quotes_do_not_touch_job_counts_or_revenue(self):
        self.make_quote(status='DECLINED')
        self.make_quote(status='SENT', valid_until=timezone.localdate() - timedelta(days=3))
        self.assertEqual(Repair.objects.count(), 0)
        self.assertEqual(Replacement.objects.count(), 0)
        resp = self.client.get('/quotes/?status=all')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Q-1001')
        self.assertContains(resp, 'Q-1002')
        self.assertContains(resp, 'Declined')
        self.assertContains(resp, 'Expired')

    # --- shop-side actions ---------------------------------------------------

    def test_shop_can_record_an_acceptance_in_person(self):
        quote = self.make_quote()
        resp = self.client.post(f'/quotes/{quote.id}/accept/')
        self.assertEqual(resp.status_code, 302)
        quote.refresh_from_db()
        self.assertEqual(quote.status, 'ACCEPTED')
        self.assertEqual(quote.accepted_via, 'shop')
        job = Repair.objects.get(quote=quote)
        self.assertEqual(job.technician, self.tech)  # the actor keeps the job
        self.assertEqual(job.queue_status, 'APPROVED')

    def test_revise_clones_into_a_draft_that_supersedes(self):
        quote = self.make_quote(status='SENT', lines=[dict(desc='Chip repair', price=Decimal('50.00'))])
        resp = self.client.post(f'/quotes/{quote.id}/revise/')
        self.assertEqual(resp.status_code, 302)
        quote.refresh_from_db()
        clone = Quote.objects.get(supersedes=quote)
        self.assertEqual(quote.status, 'SUPERSEDED')
        self.assertEqual(clone.status, 'DRAFT')
        self.assertEqual(clone.quote_number, 'Q-1002')
        self.assertEqual(clone.line_items.count(), 1)
        self.assertEqual(clone.total, Decimal('50.00'))
        # the old version cannot be accepted any more
        resp = Client().post(self.public_url(quote) + 'respond/', {'action': 'accept', 'name': 'Sam'})
        self.assertEqual(resp.status_code, 409)

    def test_only_a_draft_can_be_deleted(self):
        draft = self.make_quote()
        sent = self.make_quote(status='SENT')
        self.assertEqual(self.client.post(f'/quotes/{sent.id}/delete/').status_code, 302)
        self.assertTrue(Quote.objects.filter(pk=sent.pk).exists())
        self.assertEqual(self.client.post(f'/quotes/{draft.id}/delete/').status_code, 302)
        self.assertFalse(Quote.objects.filter(pk=draft.pk).exists())

    def test_answered_quote_cannot_be_edited(self):
        quote = self.make_quote(status='ACCEPTED')
        resp = self.client.get(f'/quotes/{quote.id}/edit/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].endswith(f'/quotes/{quote.id}/'))

    def test_shop_pages_render(self):
        quote = self.make_quote(status='SENT')
        for url in ('/quotes/', '/quotes/new/', f'/quotes/{quote.id}/', f'/quotes/{quote.id}/edit/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
        resp = self.client.get(f'/quotes/{quote.id}/')
        self.assertContains(resp, quote_service.public_url(quote))
        resp = self.client.get('/quotes/new/?customer=%d' % self.person.id)
        self.assertContains(resp, f'<option value="{self.person.id}" selected')

    def test_job_page_links_back_to_its_quote(self):
        quote = self.make_quote(status='SENT')
        job = quote_service.accept_quote(quote, via='link', actor_name='x')[0]
        resp = self.client.get(f'/tech/repairs/{job.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'From quote {quote.quote_number}')

    # --- tenant isolation ----------------------------------------------------

    def test_another_shops_quote_is_invisible(self):
        other_owner, other = make_tenant('Other Shop', 'other_owner2')
        other_customer = Customer.objects.create(name='Theirs', tenant=other, customer_type='FLEET')
        theirs = Quote.objects.create(tenant=other, quote_number='Q-1001', customer=other_customer,
                                      valid_until=timezone.localdate())
        self.assertEqual(self.client.get(f'/quotes/{theirs.id}/').status_code, 404)
        self.assertEqual(self.client.post(f'/quotes/{theirs.id}/accept/').status_code, 404)
        resp = self.client.get('/quotes/?status=all')
        self.assertNotContains(resp, 'Theirs')
        # and a quote cannot be written against another shop's customer
        resp = self.client.post('/quotes/new/', line_post(
            [dict(type='REPAIR', desc='Chip repair', price='')], customer=other_customer.id,
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Quote.objects.filter(tenant=self.tenant).exists())

    # --- badge ---------------------------------------------------------------

    def test_status_badge_knows_quote_statuses(self):
        from core.templatetags.ui import status_badge
        self.assertEqual(status_badge('ACCEPTED', kind='quote')['classes'], 'bg-green-100 text-green-800')
        self.assertEqual(status_badge('SENT', kind='quote', variant='customer')['label'], 'Needs Your Answer')
        self.assertEqual(status_badge('EXPIRED', kind='quote')['label'], 'Expired')
        # service badges unchanged
        self.assertEqual(status_badge('PENDING', variant='customer')['label'], 'Needs Your Approval')


@override_settings(**TEST_SETTINGS)
class QuotePortalTestCase(TestCase):
    """The logged-in customer's side of the same rails."""

    def setUp(self):
        self.owner, self.tenant = make_tenant('Portal Quote Shop', 'pq_owner')
        Technician.objects.create(user=self.owner, tenant=self.tenant, is_active=True, is_manager=True)
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant, customer_type='FLEET',
                                                email='fleet@example.com')
        self.cust_user = User.objects.create_user('pq_contact', 'pq@fleetco.com', 'pw',
                                                  first_name='Pat', last_name='Contact')
        CustomerUser.objects.create(user=self.cust_user, customer=self.customer, is_primary_contact=True)
        self.client = Client()
        self.client.force_login(self.cust_user)

    def make_quote(self, status='SENT', customer=None):
        quote = Quote.objects.create(
            tenant=self.tenant, quote_number=BillingConfig.allocate_quote_number(self.tenant),
            customer=customer or self.customer, status=status, unit_number='9',
            valid_until=timezone.localdate() + timedelta(days=14),
        )
        QuoteLineItem.objects.create(quote=quote, service_type='REPAIR', description='Chip repair',
                                     unit_price=Decimal('50.00'), amount=Decimal('50.00'))
        quote_service.recalculate_totals(quote)
        return quote

    def test_list_shows_sent_quotes_but_never_drafts(self):
        sent = self.make_quote('SENT')
        draft = self.make_quote('DRAFT')
        resp = self.client.get('/app/quotes/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, sent.quote_number)
        self.assertNotContains(resp, draft.quote_number)
        self.assertContains(resp, 'waiting for your answer')
        self.assertEqual(self.client.get(f'/app/quotes/{draft.id}/').status_code, 404)

    def test_detail_and_accept_in_portal(self):
        quote = self.make_quote()
        resp = self.client.get(f'/app/quotes/{quote.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ready to go ahead?')
        resp = self.client.post(f'/app/quotes/{quote.id}/respond/', {'action': 'accept'})
        self.assertEqual(resp.status_code, 302)
        quote.refresh_from_db()
        self.assertEqual(quote.status, 'ACCEPTED')
        self.assertEqual(quote.accepted_via, 'portal')
        self.assertEqual(quote.responded_by_name, 'Pat Contact')
        job = Repair.objects.get(quote=quote)
        self.assertEqual(job.cost, Decimal('50.00'))
        self.assertEqual(job.queue_status, 'APPROVED')
        resp = self.client.get(f'/app/quotes/{quote.id}/')
        self.assertContains(resp, 'Scheduled work')
        self.assertContains(resp, f'Repair #{job.id}')

    def test_decline_in_portal(self):
        quote = self.make_quote()
        resp = self.client.post(f'/app/quotes/{quote.id}/respond/', {'action': 'decline', 'reason': 'Later'})
        self.assertEqual(resp.status_code, 302)
        quote.refresh_from_db()
        self.assertEqual(quote.status, 'DECLINED')
        self.assertEqual(Repair.objects.count(), 0)

    def test_another_customers_quote_is_invisible(self):
        other = Customer.objects.create(name='Other Fleet', tenant=self.tenant, customer_type='FLEET')
        theirs = self.make_quote(customer=other)
        self.assertEqual(self.client.get(f'/app/quotes/{theirs.id}/').status_code, 404)
        self.assertEqual(self.client.post(f'/app/quotes/{theirs.id}/respond/', {'action': 'accept'}).status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, 'SENT')

    def test_nav_links_to_quotes(self):
        resp = self.client.get('/app/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '/app/quotes/')
