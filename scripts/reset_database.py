#!/usr/bin/env python
"""
Reset Database Script for RS Systems
This script clears all business data while preserving the admin account.
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
from apps.technician_portal.models import Technician, Repair, UnitRepairCount
from apps.customer_portal.models import Customer, CustomerUser
from apps.rewards_referrals.models import ReferralCode, RewardRedemption, RewardType

User = get_user_model()

def reset_database():
    """Clear all business data while keeping admin account."""
    
    print("WARNING: This will delete ALL business data!")
    print("The following will be DELETED:")
    print("- All repairs")
    print("- All customers (except admin)")
    print("- All technicians (except admin)")
    print("- All referral codes and rewards")
    print("- All photos")
    print("\nThe following will be KEPT:")
    print("- Admin superuser account")
    print("- System reward types (configured rewards)")
    
    response = input("\nType 'DELETE' to confirm: ")
    if response != 'DELETE':
        print("Cancelled.")
        return
    
    print("\nDeleting business data...")
    
    # Delete all repairs and related data
    Repair.objects.all().delete()
    print("✓ Deleted all repairs")
    
    # Delete unit repair counts
    UnitRepairCount.objects.all().delete()
    print("✓ Deleted repair counts")
    
    # Photos are stored as file references in Repair model, no separate model to delete
    
    # Delete rewards data (but keep RewardTypes)
    RewardRedemption.objects.all().delete()
    ReferralCode.objects.all().delete()
    print("✓ Deleted redemptions and referral codes")
    
    # Delete customers and their users
    CustomerUser.objects.all().delete()
    Customer.objects.all().delete()
    print("✓ Deleted all customers")
    
    # Delete technicians (except admin if they have a technician profile)
    admin = User.objects.filter(username='admin').first()
    if admin:
        Technician.objects.exclude(user=admin).delete()
    else:
        Technician.objects.all().delete()
    print("✓ Deleted technicians (kept admin if exists)")
    
    # Delete all non-admin users
    User.objects.exclude(username='admin').exclude(is_superuser=True).delete()
    print("✓ Deleted all non-admin users")
    
    print("\n" + "="*50)
    print("DATABASE RESET COMPLETE")
    print("="*50)
    print("✓ All business data deleted")
    print("✓ Admin account preserved")
    print("\nYou can now:")
    print("1. Login as admin")
    print("2. Create new customers")
    print("3. Create new technicians")
    print("4. Start fresh with real data")
    print("="*50)

if __name__ == '__main__':
    reset_database()