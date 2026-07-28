from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission

from apps.technician_portal.models import Technician


class Command(BaseCommand):
    """Create the Technicians group and its permission set.

    Safe to run on any environment (idempotent, creates NO users).
    Historic versions of this command also created an `admin` superuser and
    demo technicians with the password '123' — that was a production
    credential hazard and has been removed. Use `createsuperuser` for admin
    accounts and the in-app Team page for technicians.
    """

    help = 'Create the Technicians group and configure its permissions'

    def handle(self, *args, **options):
        technicians_group, created = Group.objects.get_or_create(name='Technicians')

        if created:
            self.stdout.write(self.style.SUCCESS('Successfully created Technicians group'))
        else:
            self.stdout.write('Technicians group already exists')

        self.setup_technician_permissions(technicians_group)

    def setup_technician_permissions(self, technicians_group):
        """
        Configure appropriate permissions for the Technicians group.

        Technicians need access to:
        - View, add, change repairs (but not delete - preserves data integrity)
        - View customers and repair counts (read-only for data consistency)
        - View and update their notifications

        Explicitly excludes:
        - User management permissions (security boundary)
        - Delete permissions on critical models (data protection)
        - Administrative functions (maintains role separation)
        """
        try:
            from django.contrib.contenttypes.models import ContentType
            from apps.technician_portal.models import Repair, UnitRepairCount, TechnicianNotification
            from core.models import Customer

            # Clear existing permissions first to ensure clean state
            technicians_group.permissions.clear()

            # Repair model permissions - core technician workflow
            repair_content_type = ContentType.objects.get_for_model(Repair)
            repair_permissions = Permission.objects.filter(
                content_type=repair_content_type,
                codename__in=['view_repair', 'add_repair', 'change_repair']
            )
            technicians_group.permissions.add(*repair_permissions)

            # Customer model permissions - read-only access for repair context
            customer_content_type = ContentType.objects.get_for_model(Customer)
            customer_permissions = Permission.objects.filter(
                content_type=customer_content_type,
                codename='view_customer'
            )
            technicians_group.permissions.add(*customer_permissions)

            # UnitRepairCount model permissions - read-only for repair history context
            unit_repair_content_type = ContentType.objects.get_for_model(UnitRepairCount)
            unit_repair_permissions = Permission.objects.filter(
                content_type=unit_repair_content_type,
                codename='view_unitrepaircount'
            )
            technicians_group.permissions.add(*unit_repair_permissions)

            # TechnicianNotification permissions - view and change (mark as read)
            notification_content_type = ContentType.objects.get_for_model(TechnicianNotification)
            notification_permissions = Permission.objects.filter(
                content_type=notification_content_type,
                codename__in=['view_techniciannotification', 'change_techniciannotification']
            )
            technicians_group.permissions.add(*notification_permissions)

            # Technician model permissions - view and change own profile
            technician_content_type = ContentType.objects.get_for_model(Technician)
            technician_permissions = Permission.objects.filter(
                content_type=technician_content_type,
                codename__in=['view_technician', 'change_technician']
            )
            technicians_group.permissions.add(*technician_permissions)

            self.stdout.write(self.style.SUCCESS('Successfully configured Technicians group permissions'))

            # Log the permissions granted for transparency
            permission_count = technicians_group.permissions.count()
            self.stdout.write(f'Granted {permission_count} permissions to Technicians group:')
            for perm in technicians_group.permissions.all():
                self.stdout.write(f'  - {perm.codename} on {perm.content_type.model}')

        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'Warning: Could not configure all permissions: {e}')
            )
            self.stdout.write('Technicians group created but may need manual permission configuration')
