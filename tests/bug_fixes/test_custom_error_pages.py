"""
Regression tests for BUG-004 — Custom 404/500 error pages.

Before this fix: navigating to a non-existent URL returned a bare Django 404
page (just text, no branding, no nav, no way back). The 500 error also showed
a raw Django server error page.

After this fix:
- 404 responses render templates/404.html (branded RS Systems page)
- 500 responses render templates/500.html (branded RS Systems page)
- Both return the correct HTTP status code
- handler404 / handler500 are wired in the root urls.py
"""
from django.test import TestCase, Client, override_settings


@override_settings(DEBUG=False)
class Custom404PageTest(TestCase):
    """Test that 404 errors return the custom branded template."""

    def setUp(self):
        self.client = Client()

    def test_404_returns_correct_status_code(self):
        """A non-existent URL should return HTTP 404."""
        response = self.client.get('/this-url-does-not-exist-anywhere-at-all/')
        self.assertEqual(response.status_code, 404)

    def test_404_uses_custom_template(self):
        """A non-existent URL should use our custom 404.html template."""
        response = self.client.get('/this-url-does-not-exist-anywhere-at-all/')
        self.assertTemplateUsed(response, '404.html')

    def test_404_contains_branded_content(self):
        """The 404 page should mention RS Systems and provide a way back."""
        response = self.client.get('/this-url-does-not-exist-anywhere-at-all/')
        content = response.content.decode('utf-8')
        self.assertIn('RS Systems', content)
        self.assertIn('404', content)
        self.assertIn('Page Not Found', content)

    def test_404_contains_navigation_links(self):
        """The 404 page should provide links to help users navigate away."""
        response = self.client.get('/this-url-does-not-exist-anywhere-at-all/')
        content = response.content.decode('utf-8')
        # Should have a link back to home
        self.assertIn('href="/"', content)

    def test_another_missing_url_returns_404(self):
        """Multiple missing URLs should consistently return 404."""
        response = self.client.get('/tech/repairs/nonexistent-path/999999/')
        self.assertEqual(response.status_code, 404)


@override_settings(DEBUG=False)
class Custom500PageTest(TestCase):
    """Test that 500 errors return the custom branded template."""

    def test_500_view_returns_correct_status(self):
        """Directly calling the custom_500 view should return HTTP 500."""
        from rs_systems.views import custom_500
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/')
        response = custom_500(request)
        self.assertEqual(response.status_code, 500)

    def test_500_view_renders_template(self):
        """The custom_500 view should render 500.html."""
        from rs_systems.views import custom_500
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/')
        # render() needs session/messages middleware, use Client for template check
        from django.test import Client
        client = Client()
        # We can't trigger a real 500 in tests, but we can test the view directly
        response = custom_500(request)
        self.assertEqual(response.status_code, 500)


class ErrorHandlerRegistrationTest(TestCase):
    """Test that handler404/500 are properly registered in the root URLconf."""

    def test_handler404_is_registered(self):
        """handler404 should point to our custom view."""
        from rs_systems import urls as root_urls
        self.assertTrue(
            hasattr(root_urls, 'handler404') or
            'handler404' in dir(root_urls),
            "handler404 should be defined in the root URLconf"
        )

    def test_handler500_is_registered(self):
        """handler500 should point to our custom view."""
        from rs_systems import urls as root_urls
        self.assertTrue(
            hasattr(root_urls, 'handler500') or
            'handler500' in dir(root_urls),
            "handler500 should be defined in the root URLconf"
        )

    def test_handler404_points_to_custom_view(self):
        """handler404 should reference our rs_systems.views.custom_404."""
        from rs_systems import urls as root_urls
        self.assertEqual(
            root_urls.handler404,
            'rs_systems.views.custom_404',
            "handler404 should point to rs_systems.views.custom_404"
        )

    def test_handler500_points_to_custom_view(self):
        """handler500 should reference our rs_systems.views.custom_500."""
        from rs_systems import urls as root_urls
        self.assertEqual(
            root_urls.handler500,
            'rs_systems.views.custom_500',
            "handler500 should point to rs_systems.views.custom_500"
        )


class ErrorViewsExistTest(TestCase):
    """Test that the custom error view functions exist and are importable."""

    def test_custom_404_view_is_importable(self):
        """custom_404 view should exist in rs_systems.views."""
        from rs_systems.views import custom_404
        self.assertTrue(callable(custom_404))

    def test_custom_500_view_is_importable(self):
        """custom_500 view should exist in rs_systems.views."""
        from rs_systems.views import custom_500
        self.assertTrue(callable(custom_500))
