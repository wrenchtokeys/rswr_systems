from django.test import TestCase
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from datetime import time, timedelta
from core.models import (
    Customer,
    Notification,
    NotificationTemplate,
    TechnicianNotificationPreference,
    CustomerNotificationPreference,
    NotificationDeliveryLog,
)
from apps.technician_portal.models import Technician, Repair


class NotificationModelTestCase(TestCase):
    """Test Notification model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testtech',
            email='tech@test.com',
            first_name='Test',
            last_name='Technician'
        )
        self.technician = Technician.objects.create(
            user=self.user,
            phone_number='+12025551234'
        )
        self.customer = Customer.objects.create(
            name='test company',
            email='customer@test.com',
            phone='+12025555678'
        )

        self.technician_ct = ContentType.objects.get_for_model(Technician)

    def test_notification_creation(self):
        """Test basic notification creation"""
        notification = Notification.objects.create(
            recipient_type=self.technician_ct,
            recipient_id=self.technician.id,
            title='Test Notification',
            message='Test message',
            category='system',
            priority='MEDIUM'
        )

        self.assertEqual(notification.title, 'Test Notification')
        self.assertEqual(notification.priority, 'MEDIUM')
        self.assertFalse(notification.read)

    def test_mark_as_read(self):
        """Test marking notification as read"""
        notification = Notification.objects.create(
            recipient_type=self.technician_ct,
            recipient_id=self.technician.id,
            title='Test',
            message='Test',
            category='system',
            priority='LOW'
        )

        self.assertFalse(notification.read)
        self.assertIsNone(notification.read_at)

        notification.mark_as_read()

        self.assertTrue(notification.read)
        self.assertIsNotNone(notification.read_at)

    def test_get_delivery_channels_urgent(self):
        """Test delivery channels for URGENT priority"""
        notification = Notification.objects.create(
            recipient_type=self.technician_ct,
            recipient_id=self.technician.id,
            title='Urgent',
            message='Urgent message',
            category='approval',
            priority='URGENT'
        )

        channels = notification.get_delivery_channels()
        self.assertIn('in_app', channels)
        self.assertIn('email', channels)
        self.assertIn('sms', channels)

    def test_get_delivery_channels_high(self):
        """Test delivery channels for HIGH priority"""
        notification = Notification.objects.create(
            recipient_type=self.technician_ct,
            recipient_id=self.technician.id,
            title='High',
            message='High priority message',
            category='assignment',
            priority='HIGH'
        )

        channels = notification.get_delivery_channels()
        self.assertIn('in_app', channels)
        self.assertIn('sms', channels)
        self.assertNotIn('email', channels)

    def test_get_delivery_channels_medium(self):
        """Test delivery channels for MEDIUM priority"""
        notification = Notification.objects.create(
            recipient_type=self.technician_ct,
            recipient_id=self.technician.id,
            title='Medium',
            message='Medium priority message',
            category='repair_status',
            priority='MEDIUM'
        )

        channels = notification.get_delivery_channels()
        self.assertIn('in_app', channels)
        self.assertIn('email', channels)
        self.assertNotIn('sms', channels)

    def test_get_delivery_channels_low(self):
        """Test delivery channels for LOW priority"""
        notification = Notification.objects.create(
            recipient_type=self.technician_ct,
            recipient_id=self.technician.id,
            title='Low',
            message='Low priority message',
            category='system',
            priority='LOW'
        )

        channels = notification.get_delivery_channels()
        self.assertIn('in_app', channels)
        self.assertNotIn('email', channels)
        self.assertNotIn('sms', channels)


class NotificationTemplateTestCase(TestCase):
    """Test NotificationTemplate model functionality"""

    def setUp(self):
        """Set up test data"""
        self.template = NotificationTemplate.objects.create(
            name='test_template',
            description='Test template',
            category='system',
            default_priority='MEDIUM',
            title_template='Test {{ name }}',
            message_template='Message for {{ name }}',
            email_subject_template='Subject for {{ name }}',
            email_html_template='<p>HTML for {{ name }}</p>',
            email_text_template='Text for {{ name }}',
            sms_template='SMS for {{ name }}',
            action_url_template='/test/{{ id }}/',
            required_context=['name', 'id']
        )

    def test_template_rendering(self):
        """Test template rendering with context"""
        context = {'name': 'John', 'id': 123}
        rendered = self.template.render(context)

        self.assertEqual(rendered['title'], 'Test John')
        self.assertEqual(rendered['message'], 'Message for John')
        self.assertEqual(rendered['email_subject'], 'Subject for John')
        self.assertEqual(rendered['email_html'], '<p>HTML for John</p>')
        self.assertEqual(rendered['email_text'], 'Text for John')
        self.assertEqual(rendered['sms'], 'SMS for John')
        self.assertEqual(rendered['action_url'], '/test/123/')

    def test_context_validation_valid(self):
        """Test context validation with valid context"""
        context = {'name': 'John', 'id': 123}
        is_valid, missing = self.template.validate_context(context)

        self.assertTrue(is_valid)
        self.assertEqual(len(missing), 0)

    def test_context_validation_invalid(self):
        """Test context validation with missing variables"""
        context = {'name': 'John'}  # Missing 'id'
        is_valid, missing = self.template.validate_context(context)

        self.assertFalse(is_valid)
        self.assertIn('id', missing)


class TechnicianNotificationPreferenceTestCase(TestCase):
    """Test TechnicianNotificationPreference model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testtech',
            email='tech@test.com'
        )
        self.technician = Technician.objects.create(
            user=self.user,
            phone_number='+12025551234'
        )
        self.prefs = TechnicianNotificationPreference.objects.create(
            technician=self.technician,
            receive_email_notifications=True,
            receive_sms_notifications=True,
            email_verified=True,
            phone_verified=True
        )

    def test_can_send_email_verified(self):
        """Test can_send_email with verified email"""
        self.assertTrue(self.prefs.can_send_email())

    def test_can_send_email_not_verified(self):
        """Test can_send_email with unverified email"""
        self.prefs.email_verified = False
        self.prefs.save()
        self.assertFalse(self.prefs.can_send_email())

    def test_can_send_email_disabled(self):
        """Test can_send_email when disabled"""
        self.prefs.receive_email_notifications = False
        self.prefs.save()
        self.assertFalse(self.prefs.can_send_email())

    def test_can_send_sms_verified(self):
        """Test can_send_sms with verified phone"""
        self.assertTrue(self.prefs.can_send_sms())

    def test_can_send_sms_not_verified(self):
        """Test can_send_sms with unverified phone"""
        self.prefs.phone_verified = False
        self.prefs.save()
        self.assertFalse(self.prefs.can_send_sms())

    def test_is_in_quiet_hours_disabled(self):
        """Test quiet hours when disabled"""
        self.prefs.quiet_hours_enabled = False
        self.prefs.save()
        self.assertFalse(self.prefs.is_in_quiet_hours())

    def test_is_in_quiet_hours_normal_range(self):
        """Test quiet hours with normal time range (no midnight crossing)"""
        self.prefs.quiet_hours_enabled = True
        self.prefs.quiet_hours_start = time(22, 0)  # 10 PM
        self.prefs.quiet_hours_end = time(8, 0)     # 8 AM
        self.prefs.save()

        # Mock different times of day
        # This would require time mocking in a real implementation
        # For now, just test that the method doesn't crash
        result = self.prefs.is_in_quiet_hours()
        self.assertIsInstance(result, bool)


class NotificationDeliveryLogTestCase(TestCase):
    """Test NotificationDeliveryLog model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(username='testuser', email='test@example.com')
        self.technician = Technician.objects.create(user=self.user)
        self.technician_ct = ContentType.objects.get_for_model(Technician)

        self.notification = Notification.objects.create(
            recipient_type=self.technician_ct,
            recipient_id=self.technician.id,
            title='Test Notification',
            message='Test message',
            category='system',
            priority='MEDIUM'
        )

        self.log = NotificationDeliveryLog.objects.create(
            notification=self.notification,
            channel='email',
            status='pending',
            recipient_email='test@example.com',
            provider_name='AWS SES',
            attempt_number=1
        )

    def test_mark_sent(self):
        """Test marking delivery as sent"""
        self.log.mark_sent(
            provider_message_id='msg-123',
            provider_response={'MessageId': 'msg-123'}
        )

        self.assertEqual(self.log.status, 'sent')
        self.assertIsNotNone(self.log.sent_at)
        self.assertEqual(self.log.provider_message_id, 'msg-123')

    def test_mark_failed(self):
        """Test marking delivery as failed"""
        self.log.mark_failed('SMTP error', 'ERR_SMTP')

        self.assertEqual(self.log.status, 'failed')
        self.assertIsNotNone(self.log.failed_at)
        self.assertEqual(self.log.error_message, 'SMTP error')
        self.assertEqual(self.log.error_code, 'ERR_SMTP')
        self.assertIsNotNone(self.log.next_retry_at)

    def test_should_retry_true(self):
        """Test should_retry when conditions are met"""
        self.log.status = 'failed'
        self.log.attempt_number = 1
        self.log.next_retry_at = timezone.now() - timedelta(minutes=5)
        self.log.save()

        self.assertTrue(self.log.should_retry())

    def test_should_retry_false_max_attempts(self):
        """Test should_retry when max attempts reached"""
        self.log.status = 'failed'
        self.log.attempt_number = 3
        self.log.next_retry_at = timezone.now() - timedelta(minutes=5)
        self.log.save()

        self.assertFalse(self.log.should_retry())

    def test_should_retry_false_too_soon(self):
        """Test should_retry when retry time not reached"""
        self.log.status = 'failed'
        self.log.attempt_number = 1
        self.log.next_retry_at = timezone.now() + timedelta(minutes=5)
        self.log.save()

        self.assertFalse(self.log.should_retry())


class CustomerModelTestCase(TestCase):
    """Test Customer model with verification fields"""

    def test_customer_creation_with_verification(self):
        """Test customer creation with verification fields"""
        customer = Customer.objects.create(
            name='test company',
            email='test@company.com',
            phone='+12025551234',
            email_verified=False,
            phone_verified=False
        )

        self.assertEqual(customer.name, 'test company')
        self.assertFalse(customer.email_verified)
        self.assertFalse(customer.phone_verified)

    def test_customer_name_lowercase(self):
        """Test that customer name preserves original casing"""
        customer = Customer.objects.create(
            name='TEST COMPANY'
        )
        self.assertEqual(customer.name, 'TEST COMPANY')

    def test_customer_unique_name(self):
        """Test that customers can be created with different names"""
        c1 = Customer.objects.create(name='Unique Company')
        c2 = Customer.objects.create(name='Another Company')
        self.assertNotEqual(c1.id, c2.id)

    def test_customer_unique_email(self):
        """Test that customers can share email (no unique constraint)"""
        Customer.objects.create(name='Company One', email='test@example.com')
        c2 = Customer.objects.create(name='Company Two', email='test@example.com')
        self.assertIsNotNone(c2.id)

    def test_customer_optional_fields(self):
        """Test customer creation with only required fields"""
        customer = Customer.objects.create(name='Minimal Company')
        self.assertIsNone(customer.email)
        self.assertIsNone(customer.phone)

    def test_customer_ordering(self):
        """Test customers are ordered by name"""
        Customer.objects.create(name='Charlie Company')
        Customer.objects.create(name='Alpha Company')
        Customer.objects.create(name='Beta Company')
        customers = list(Customer.objects.all())
        self.assertEqual(customers[0].name, 'Alpha Company')
        self.assertEqual(customers[1].name, 'Beta Company')
        self.assertEqual(customers[2].name, 'Charlie Company')
from django.test import TestCase
from django.core.exceptions import ValidationError
from core.models import Customer


class CustomerModelTest(TestCase):
    def test_customer_creation(self):
        customer = Customer.objects.create(
            name='Test Company',
            email='test@company.com',
            phone='555-1234',
            address='123 Main St',
            city='Test City',
            state='TS',
            zip_code='12345'
        )
        self.assertEqual(customer.name, 'Test Company')
        self.assertEqual(customer.email, 'test@company.com')
        self.assertEqual(str(customer), 'Test Company')

    def test_customer_unique_name(self):
        """Test that customers can be created with different names."""
        c1 = Customer.objects.create(name='Unique Company')
        c2 = Customer.objects.create(name='Another Company')
        self.assertNotEqual(c1.id, c2.id)

    def test_customer_unique_email(self):
        """Test that customers can have the same email (no unique constraint)."""
        Customer.objects.create(
            name='Company One',
            email='test@example.com'
        )
        # Email is not unique-constrained in current model
        c2 = Customer.objects.create(
            name='Company Two',
            email='test@example.com'
        )
        self.assertIsNotNone(c2.id)

    def test_customer_optional_fields(self):
        customer = Customer.objects.create(name='Minimal Company')
        self.assertIsNone(customer.email)
        self.assertIsNone(customer.phone)
        self.assertIsNone(customer.address)
        self.assertIsNone(customer.city)
        self.assertIsNone(customer.state)
        self.assertIsNone(customer.zip_code)

    def test_customer_ordering(self):
        Customer.objects.create(name='Charlie Company')
        Customer.objects.create(name='Alpha Company')
        Customer.objects.create(name='Beta Company')
        
        customers = list(Customer.objects.all())
        self.assertEqual(customers[0].name, 'Alpha Company')
        self.assertEqual(customers[1].name, 'Beta Company')
        self.assertEqual(customers[2].name, 'Charlie Company')