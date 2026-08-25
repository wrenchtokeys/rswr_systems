"""
In-app notification surfaces — the bell dropdown and both history pages.

Covers the UI_MAGIC session that put the bell and the notification history onto
the shared chassis. Six of these pin live bugs the session found:

  1. The 30-second poll rewrote the dropdown's innerHTML from a JavaScript
     template literal, interpolating notification titles and messages raw. Those
     strings carry customer, vehicle and shop text. Rows are now rendered by
     Django and arrive pre-escaped in the payload.
  2. Because the poll replaced the list wholesale, the click handlers bound at
     page load died on the first tick — after 30 seconds, clicking an unread row
     stopped marking it read. Handling is delegated now.
  3. Technician mark-all-read never invalidated its own cache key. A queryset
     .update() fires no post_save, so the CODE-234 signal did not run: the badge
     went to zero on click and bounced back to the stale count on the next poll.
  4. `timesince` renders "0 minutes ago" for anything under a minute — i.e. on
     the notification a tech is most likely to be looking at.
  5. The customer's notification history was written in Bootstrap on an app that
     has never shipped Bootstrap, so most of it rendered unstyled.
  6. The tone tables in core/templatetags live in .py files, which Tailwind's
     content globs did not scan. Those classes were being purged.
"""

import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician
from apps.technician_portal.views.notifications import _unread_cache_key
from core.models import Notification
from core.templatetags import notifications_ui


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(username):
    return User.objects.create_user(username=username, password='test', email=f'{username}@test.com')


def _make_tenant(name):
    import uuid
    slug = uuid.uuid4().hex[:10]
    owner = _make_user(f'owner_{slug}')
    return Tenant.objects.create(name=name, slug=slug, subdomain=slug, owner=owner, is_active=True)


def _make_notification(tech, **kwargs):
    ct = ContentType.objects.get_for_model(Technician)
    created_at = kwargs.pop('created_at', None)
    n = Notification.objects.create(
        recipient_type=ct,
        recipient_id=tech.id,
        title=kwargs.pop('title', 'Test Notification'),
        message=kwargs.pop('message', 'Test message'),
        category=kwargs.pop('category', 'assignment'),
        read=kwargs.pop('read', False),
        **kwargs,
    )
    if created_at is not None:
        # created_at is auto_now_add; only an update() can backdate it.
        Notification.objects.filter(pk=n.pk).update(created_at=created_at)
        n.refresh_from_db()
    return n


# ---------------------------------------------------------------------------
# Time filters
# ---------------------------------------------------------------------------

class ShortAgeTests(TestCase):
    """short_age is the bell's right column."""

    def _age(self, **kwargs):
        return notifications_ui.short_age(timezone.now() - timedelta(**kwargs))

    def test_under_a_minute_is_just_now(self):
        """The bug: timesince renders "0 minutes ago" for a fresh notification."""
        self.assertEqual(self._age(seconds=5), 'Just now')
        self.assertEqual(self._age(seconds=59), 'Just now')

    def test_minutes_hours_days_weeks(self):
        self.assertEqual(self._age(minutes=9), '9m')
        self.assertEqual(self._age(minutes=59), '59m')
        self.assertEqual(self._age(hours=1), '1h')
        self.assertEqual(self._age(hours=23), '23h')
        self.assertEqual(self._age(days=1), '1d')
        self.assertEqual(self._age(days=6), '6d')
        self.assertEqual(self._age(days=7), '1w')

    def test_none_is_empty(self):
        self.assertEqual(notifications_ui.short_age(None), '')

    def test_never_renders_a_zero_quantity(self):
        """No unit should ever be printed with a leading 0 — that was the defect."""
        for seconds in (0, 1, 30, 59, 60, 3599, 3600, 86399, 86400):
            value = self._age(seconds=seconds)
            self.assertFalse(
                re.match(r'^0[mhdwy]$', value),
                f'{seconds}s rendered as {value!r}',
            )


class DayAndClockTests(TestCase):
    def test_today_and_yesterday(self):
        now = timezone.now()
        self.assertEqual(notifications_ui.notification_day(now), 'Today')
        yesterday = timezone.localtime(now).replace(hour=12) - timedelta(days=1)
        self.assertEqual(notifications_ui.notification_day(yesterday), 'Yesterday')

    def test_within_the_week_is_a_weekday_name(self):
        when = timezone.localtime(timezone.now()).replace(hour=12) - timedelta(days=3)
        self.assertEqual(
            notifications_ui.notification_day(when),
            timezone.localtime(when).strftime('%A'),
        )

    def test_older_than_a_week_is_a_date(self):
        when = timezone.localtime(timezone.now()).replace(hour=12) - timedelta(days=30)
        rendered = notifications_ui.notification_day(when)
        self.assertIn(str(when.year), rendered)
        self.assertNotIn('ago', rendered)

    def test_clock_has_no_leading_zero(self):
        when = timezone.localtime(timezone.now()).replace(hour=9, minute=5)
        self.assertEqual(notifications_ui.notification_clock(when), '9:05 AM')

    def test_none_is_empty(self):
        self.assertEqual(notifications_ui.notification_day(None), '')
        self.assertEqual(notifications_ui.notification_clock(None), '')


class CategoryStyleTests(TestCase):
    def test_every_model_category_has_a_style(self):
        """A category with no entry would render an untinted, unlabelled row."""
        for value, _label in Notification.CATEGORY_CHOICES:
            self.assertIn(value, notifications_ui.CATEGORY_STYLES, f'{value} has no style')

    def test_unknown_category_falls_back(self):
        self.assertEqual(notifications_ui.notification_icon('not_a_category'), 'info')
        self.assertTrue(notifications_ui.notification_tint('not_a_category'))
        self.assertEqual(notifications_ui.notification_category_label('not_a_category'), 'Notification')

    def test_labels_are_short_enough_for_a_column(self):
        """CATEGORY_CHOICES' own labels ("Assignment/Reassignment") are settings copy."""
        for value in notifications_ui.CATEGORY_STYLES:
            self.assertLessEqual(len(notifications_ui.notification_category_label(value)), 12)


class TailwindPurgeGuardTests(TestCase):
    """The tone tables hold Tailwind classes as Python strings.

    tailwind.config.js scanned only templates and JS, so these were purged and a
    badge rendered shape-only. `bg-yellow-200` — the "Customer Requested" status
    pill's background — was genuinely missing from the built CSS before this
    session added './core/templatetags/*.py' to the content globs.
    """

    def _built_css(self):
        path = Path(settings.BASE_DIR) / 'static' / 'css' / 'app.css'
        if not path.exists():          # CI may not run the CSS build
            self.skipTest('static/css/app.css not built')
        return path.read_text()

    def test_notification_tints_survive_the_purge(self):
        css = self._built_css()
        for value in notifications_ui.CATEGORY_STYLES:
            for cls in notifications_ui.notification_tint(value).split():
                self.assertIn(f'.{cls}', css, f'{cls} was purged — run scripts/build_css.sh')

    def test_status_badge_tones_survive_the_purge(self):
        from core.templatetags import ui
        css = self._built_css()
        tables = [ui.SERVICE_STATUS_STYLES, ui.INVOICE_STATUS_STYLES]
        for table in tables:
            for status, (classes, _label) in table.items():
                for cls in classes.split():
                    self.assertIn(f'.{cls}', css, f'{status}: {cls} was purged')

    def test_config_scans_the_templatetags_package(self):
        config = (Path(settings.BASE_DIR) / 'tailwind.config.js').read_text()
        self.assertIn('templatetags', config)


# ---------------------------------------------------------------------------
# The rendered row and list
# ---------------------------------------------------------------------------

class NotificationRowTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant('Row Shop')
        self.user = _make_user('rowtech')
        self.tech = Technician.objects.create(user=self.user, tenant=self.tenant)

    def _render(self, notification, variant='bell'):
        return render_to_string(
            'components/notification_row.html',
            {'notification': notification, 'variant': variant},
        )

    def test_unread_gets_exactly_one_visible_marker(self):
        """It used to carry three at once: a tint, a "New" pill and a bold title."""
        html = self._render(_make_notification(self.tech, read=False))
        self.assertIn('notification-dot', html)
        self.assertNotIn('opacity-0', html)      # the dot is showing
        self.assertNotIn('>New<', html)          # no pill
        self.assertNotIn('bg-brand-50', html)    # no row tint

    def test_read_row_keeps_the_gutter(self):
        """The dot is hidden, not removed — a row must not reflow when it clears."""
        html = self._render(_make_notification(self.tech, read=True))
        self.assertIn('notification-dot', html)
        self.assertIn('opacity-0', html)

    def test_row_carries_its_id_and_read_state_for_delegation(self):
        n = _make_notification(self.tech, read=False)
        html = self._render(n)
        self.assertIn(f'data-notification-id="{n.id}"', html)
        self.assertIn('data-read="0"', html)
        self.assertIn(f'data-read="1"', self._render(_make_notification(self.tech, read=True)))

    def test_bell_variant_uses_short_age_and_page_variant_uses_a_clock(self):
        n = _make_notification(self.tech, created_at=timezone.now() - timedelta(minutes=9))
        self.assertIn('>9m<', self._render(n, 'bell').replace('\n', '').replace(' ', '').replace('>9m<', '>9m<'))
        page = self._render(n, 'page')
        self.assertRegex(page, r'\d{1,2}:\d{2} [AP]M')

    def test_titles_and_messages_are_escaped(self):
        n = _make_notification(
            self.tech,
            title='<script>alert(1)</script>',
            message='<img src=x onerror=alert(2)>',
        )
        html = self._render(n)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;script&gt;', html)


class NotificationListTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant('List Shop')
        self.user = _make_user('listtech')
        self.tech = Technician.objects.create(user=self.user, tenant=self.tenant)

    def test_day_headers_group_the_list(self):
        now = timezone.now()
        _make_notification(self.tech, title='A', created_at=now - timedelta(hours=1))
        _make_notification(self.tech, title='B', created_at=now - timedelta(hours=2))
        _make_notification(self.tech, title='C', created_at=timezone.localtime(now).replace(hour=12) - timedelta(days=1))
        qs = Notification.objects.filter(recipient_id=self.tech.id).order_by('-created_at')
        html = render_to_string('components/notification_list.html', {'notifications': qs})
        self.assertEqual(len(re.findall(r'>\s*Today\s*<', html)), 1, 'one Today header, not one per row')
        self.assertEqual(len(re.findall(r'>\s*Yesterday\s*<', html)), 1)

    def test_empty_state_copy_is_overridable(self):
        html = render_to_string(
            'components/notification_list.html',
            {'notifications': [], 'empty_title': 'Nothing here', 'empty_message': 'Later.'},
        )
        self.assertIn('Nothing here', html)
        self.assertIn('Later.', html)


# ---------------------------------------------------------------------------
# The bell template itself
# ---------------------------------------------------------------------------

class BellTemplateTests(TestCase):
    """Source-level guards against reintroducing the two defects it was built to fix."""

    def _source(self):
        return (Path(settings.BASE_DIR) / 'templates' / 'includes' / 'notification_bell.html').read_text()

    def test_no_javascript_row_builder(self):
        """Rows must come from the server, not a template literal in this file."""
        src = self._source()
        self.assertNotIn('${notification.title}', src)
        self.assertNotIn('${notification.message}', src)
        self.assertNotIn('${notification.action_url}', src)

    def test_row_clicks_are_delegated(self):
        """Binding to the rows present at load is what broke on the first poll."""
        src = self._source()
        self.assertNotIn("document.querySelectorAll('.notification-item').forEach", src)
        self.assertIn("list.addEventListener('click'", src)

    def test_mark_read_lives_in_one_place(self):
        """Three surfaces clear the same four markers; three copies would drift."""
        base = Path(settings.BASE_DIR) / 'templates'
        shared = (base / 'components' / 'notification_row_script.html').read_text()
        self.assertIn('notification-sr-state', shared)
        for name in ('includes/notification_bell.html',
                     'customer_portal/notification_history.html',
                     'technician_portal/notification_history.html'):
            source = (base / name).read_text()
            self.assertIn('notification_row_script.html', source, f'{name} does not include it')
            self.assertNotIn('function markRowRead', source, f'{name} has its own copy')

    def test_history_pages_share_their_behaviour(self):
        base = Path(settings.BASE_DIR) / 'templates'
        for name, expected in (('technician_portal/notification_history.html', '/tech/notifications'),
                               ('customer_portal/notification_history.html', '/app/notifications')):
            source = (base / name).read_text()
            self.assertIn('notification_page_script.html', source)
            self.assertIn(f'notify_base="{expected}"', source)

    def test_poll_holds_its_payload_while_the_panel_is_open(self):
        src = self._source()
        self.assertIn('if (isOpen()) pending', src)

    def test_a_held_payload_is_dropped_when_rows_are_read_locally(self):
        """The payload was fetched before the click; applying it on close would put
        the dots back on rows the reader has just cleared."""
        src = self._source()
        self.assertIn('function invalidateHeldPayload', src)
        # Both local mutations must drop it: the single-row click and mark-all-read.
        self.assertEqual(src.count('invalidateHeldPayload();'), 2)

    def test_trigger_reports_expanded_state(self):
        src = self._source()
        self.assertIn("aria-expanded", src)
        self.assertIn("setAttribute('aria-expanded'", src)

    def test_escape_closes_the_panel(self):
        self.assertIn("e.key === 'Escape'", self._source())

    def test_unprefetched_bell_does_not_claim_you_are_caught_up(self):
        """Only two views prefetch the bell; everywhere else it must stay silent."""
        html = render_to_string('includes/notification_bell.html', {'bell_role': 'tech'})
        self.assertNotIn("all caught up", html)
        self.assertIn('data-prefetched="0"', html)

    def test_prefetched_bell_renders_its_rows(self):
        tenant = _make_tenant('Bell Shop')
        tech = Technician.objects.create(user=_make_user('belltech'), tenant=tenant)
        n = _make_notification(tech, title='Assignment for Unit 4471')
        html = render_to_string('includes/notification_bell.html', {
            'bell_role': 'tech',
            'bell_prefetched': True,
            'unread_count': 1,
            'recent_notifications': [n],
        })
        self.assertIn('data-prefetched="1"', html)
        self.assertIn('Assignment for Unit 4471', html)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class UnreadCountPayloadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = _make_tenant('Payload Shop')
        self.user = _make_user('payloadtech')
        self.tech = Technician.objects.create(user=self.user, tenant=self.tenant)
        TenantMembership.objects.get_or_create(
            user=self.user, tenant=self.tenant,
            defaults={'role': 'technician', 'is_active': True},
        )
        self.client = Client(HTTP_HOST='localhost', HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.client.force_login(self.user)

    def test_payload_carries_rendered_html(self):
        _make_notification(self.tech, title='Unit 4471 assigned')
        data = self.client.get('/tech/notifications/unread-count/').json()
        self.assertTrue(data['success'])
        self.assertIn('html', data)
        self.assertIn('Unit 4471 assigned', data['html'])
        self.assertIn('notification-row', data['html'])

    def test_rendered_html_escapes_hostile_text(self):
        """This is the payload the bell drops into innerHTML."""
        _make_notification(self.tech, title='<script>alert(1)</script>',
                           message='<img src=x onerror=alert(2)>')
        html = self.client.get('/tech/notifications/unread-count/').json()['html']
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('<img src=x', html)

    def test_empty_inbox_still_returns_html(self):
        """The old poll skipped the update when the list was empty, so a list that
        had just been emptied stayed on screen."""
        data = self.client.get('/tech/notifications/unread-count/').json()
        self.assertEqual(data['count'], 0)
        self.assertIn('html', data)
        self.assertTrue(data['html'].strip())


class MarkAllReadCacheTests(TestCase):
    """The badge bounce-back."""

    def setUp(self):
        cache.clear()
        self.tenant = _make_tenant('Cache Shop')
        self.user = _make_user('cachetech')
        self.tech = Technician.objects.create(user=self.user, tenant=self.tenant)
        TenantMembership.objects.get_or_create(
            user=self.user, tenant=self.tenant,
            defaults={'role': 'technician', 'is_active': True},
        )
        self.client = Client(HTTP_HOST='localhost', HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.client.force_login(self.user)

    def test_mark_all_read_invalidates_the_cached_count(self):
        for i in range(3):
            _make_notification(self.tech, title=f'N{i}')

        first = self.client.get('/tech/notifications/unread-count/').json()
        self.assertEqual(first['count'], 3)      # now cached for 120s

        resp = self.client.post('/tech/notifications/mark-all-read/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

        # Before the fix this returned the stale 3: .update() fires no post_save,
        # so the CODE-234 invalidation signal never ran.
        after = self.client.get('/tech/notifications/unread-count/').json()
        self.assertEqual(after['count'], 0)

    def test_cache_key_helper_matches_what_the_signal_deletes(self):
        """Three callers have to agree on this string; two of them used to not."""
        request = RequestFactory().get('/')
        request.tenant = self.tenant
        self.assertEqual(
            _unread_cache_key(request, self.tech),
            f'notif_unread_count:tech:{self.tech.id}:{self.tenant.pk}',
        )


class HistoryPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = _make_tenant('History Shop')
        self.user = _make_user('historytech')
        self.tech = Technician.objects.create(user=self.user, tenant=self.tenant)
        TenantMembership.objects.get_or_create(
            user=self.user, tenant=self.tenant,
            defaults={'role': 'technician', 'is_active': True},
        )
        self.client = Client(HTTP_HOST='localhost', HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.client.force_login(self.user)
        self.unread = _make_notification(self.tech, title='Unread one', read=False)
        self.read = _make_notification(self.tech, title='Read one', read=True)

    def test_default_shows_everything(self):
        """The bell's footer says "View all notifications" and then landed on a page
        filtered to unread only, so a tech looking for this morning's assignment
        found an empty page."""
        html = self.client.get('/tech/notifications/history/').content.decode()
        self.assertIn('Unread one', html)
        self.assertIn('Read one', html)

    def test_unread_segment_filters(self):
        html = self.client.get('/tech/notifications/history/?show_read=false').content.decode()
        self.assertIn('Unread one', html)
        self.assertNotIn('Read one', html)

    def test_category_segment_filters(self):
        _make_notification(self.tech, title='A reward', category='reward')
        html = self.client.get('/tech/notifications/history/?category=reward').content.decode()
        self.assertIn('A reward', html)
        self.assertNotIn('Unread one', html)

    def test_all_segment_is_not_an_empty_href(self):
        """An empty href resolves to the current URL *including* its query string,
        which would make All a no-op from any other segment."""
        html = self.client.get('/tech/notifications/history/?category=reward').content.decode()
        match = re.search(r'<a href="([^"]*)"[^>]*>All</a>', re.sub(r'\s+', ' ', html))
        self.assertIsNotNone(match, 'All segment not found')
        self.assertTrue(match.group(1), 'All segment has an empty href')
        self.assertNotIn('category=', match.group(1))

    def test_unread_count_is_in_the_context(self):
        response = self.client.get('/tech/notifications/history/')
        self.assertEqual(response.context['unread_count'], 1)


class BootstrapRegressionTests(TestCase):
    """The customer's history page was Bootstrap on an app with no Bootstrap.

    `form-select`, `page-link`, `page-item`, `bg-light` and `btn-outline-primary`
    have no rule in style.css or app.css, so the page rendered as browser
    defaults: a bare select, a bulleted pagination list, and no unread treatment
    at all. Its technician twin was a proper Tailwind page the whole time.
    """

    BOOTSTRAP_ONLY = [
        'list-group', 'card-body', 'form-select', 'page-link', 'page-item',
        'alert-info', 'bg-light', 'btn-outline-primary', 'col-md-4',
    ]

    @staticmethod
    def _markup_only(source):
        """Strip {% comment %} blocks — this file's own notes name the classes."""
        return re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', source, flags=re.S)

    def test_neither_history_template_uses_bootstrap(self):
        base = Path(settings.BASE_DIR) / 'templates'
        for name in ('customer_portal/notification_history.html',
                     'technician_portal/notification_history.html'):
            source = self._markup_only((base / name).read_text())
            for cls in self.BOOTSTRAP_ONLY:
                self.assertNotIn(
                    f'{cls}', source,
                    f'{name} still uses the Bootstrap class {cls!r}, which this app does not ship',
                )
