"""
UX-012 regression tests: Statement of Account "Back to Invoices" navigation.

Before fix: The statement page used javascript:history.back() which is unreliable
(breaks when user navigates directly to the URL or opens in a new tab).

After fix: Proper Django {% url %} link to owner_invoice_list, customer name in nav bar.
"""
from django.test import TestCase, Client

from core.models import Customer
from tests.helpers import make_tenant


class TestStatementBackLink(TestCase):
    """Verify the statement page has proper navigation back to invoices."""

    def setUp(self):
        self.user, self.tenant = make_tenant('BackLinkShop', 'backlink_owner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='BackLink Corp', tenant=self.tenant, email='bl@test.com'
        )
        self.url = f'/owner/customers/{self.customer.id}/statement/'

    def test_back_link_points_to_invoice_list(self):
        """The 'Back to Invoices' link should point to the invoice list URL, not javascript:history.back()."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # Must NOT use javascript:history.back()
        self.assertNotIn('javascript:history.back()', content)
        # Must contain a link to the invoice list
        self.assertIn('/owner/invoices/', content)
        self.assertIn('Back to Invoices', content)

    def test_back_link_has_no_print_class(self):
        """The nav bar with back link should be hidden on print (no-print class)."""
        resp = self.client.get(self.url)
        content = resp.content.decode()
        # The nav bar container should have no-print class
        self.assertIn('no-print', content)

    def test_nav_bar_shows_customer_name(self):
        """The nav bar should display the customer name for context."""
        resp = self.client.get(self.url)
        content = resp.content.decode()
        self.assertIn('BackLink Corp', content)
        self.assertIn('Statement of Account', content)

    def test_back_link_is_valid_url(self):
        """The invoice list URL in the back link should be a working page."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        # Follow the back link — it should return 200
        invoice_resp = self.client.get('/owner/invoices/')
        self.assertEqual(invoice_resp.status_code, 200)
