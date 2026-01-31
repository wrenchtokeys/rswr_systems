#!/usr/bin/env python
"""
Admin Setup Script for RS Systems Production
This script creates or resets the admin superuser account.
"""

import os
import sys
import django
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rs_systems.settings.development')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

# Admin credentials
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')  # Change this immediately after first login!

def setup_admin():
    """Create or update admin superuser account."""
    try:
        # Check if admin exists
        admin = User.objects.filter(username=ADMIN_USERNAME).first()
        
        if admin:
            print(f"Admin user '{ADMIN_USERNAME}' already exists.")
            response = input("Reset password? (y/n): ").lower()
            if response == 'y':
                admin.set_password(ADMIN_PASSWORD)
                admin.email = ADMIN_EMAIL
                admin.is_staff = True
                admin.is_superuser = True
                admin.is_active = True
                admin.save()
                print(f"✓ Password reset for admin user '{ADMIN_USERNAME}'")
            else:
                print("No changes made.")
        else:
            # Create new admin
            admin = User.objects.create_superuser(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                password=ADMIN_PASSWORD
            )
            print(f"✓ Created admin user '{ADMIN_USERNAME}'")
        
        print("\n" + "="*50)
        print("ADMIN ACCESS CREDENTIALS")
        print("="*50)
        print(f"Username: {ADMIN_USERNAME}")
        print(f"Password: {ADMIN_PASSWORD}")
        print(f"Login URL: https://yourdomain.com/admin/")
        print("\n⚠️  IMPORTANT: Change this password after first login!")
        print("="*50)
        
    except Exception as e:
        print(f"Error setting up admin: {e}")
        sys.exit(1)

if __name__ == '__main__':
    setup_admin()