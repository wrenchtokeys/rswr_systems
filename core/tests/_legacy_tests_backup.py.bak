from django.test import TestCase
from django.core.exceptions import ValidationError
from .models import Customer


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
        self.assertEqual(customer.name, 'test company')  # Should be lowercase due to save method
        self.assertEqual(customer.email, 'test@company.com')
        self.assertEqual(str(customer), 'test company')

    def test_customer_unique_name(self):
        Customer.objects.create(name='Unique Company')
        with self.assertRaises(Exception):  # Should raise IntegrityError due to unique constraint
            Customer.objects.create(name='unique company')  # Same name after lowercasing

    def test_customer_unique_email(self):
        Customer.objects.create(
            name='Company One',
            email='test@example.com'
        )
        with self.assertRaises(Exception):  # Should raise IntegrityError due to unique constraint
            Customer.objects.create(
                name='Company Two',
                email='test@example.com'
            )

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
        self.assertEqual(customers[0].name, 'alpha company')
        self.assertEqual(customers[1].name, 'beta company')
        self.assertEqual(customers[2].name, 'charlie company')