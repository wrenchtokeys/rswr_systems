from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from drf_spectacular.utils import extend_schema, extend_schema_view
from apps.technician_portal.models import Technician, Repair, Replacement
from apps.tenants.mixins import TenantQuerysetMixin
from core.models import Customer
from .serializers import TechnicianSerializer, RepairSerializer, ReplacementSerializer, CustomerSerializer


@extend_schema_view(
    list=extend_schema(
        summary="List all technicians",
        description="Retrieve a list of all technicians in the system. Requires admin access."
    ),
    create=extend_schema(
        summary="Create a new technician",
        description="Create a new technician profile. Requires admin access."
    ),
    retrieve=extend_schema(
        summary="Get technician details",
        description="Retrieve detailed information about a specific technician."
    ),
    update=extend_schema(
        summary="Update technician",
        description="Update all fields of a technician profile."
    ),
    partial_update=extend_schema(
        summary="Partially update technician",
        description="Update specific fields of a technician profile."
    ),
    destroy=extend_schema(
        summary="Delete technician",
        description="Remove a technician from the system."
    ),
)
class TechnicianViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing technician profiles.

    Provides CRUD operations for technician management.
    Only authenticated admin users can access these endpoints.
    """
    require_tenant = False
    queryset = Technician.objects.select_related('user').all()
    serializer_class = TechnicianSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]


@extend_schema_view(
    list=extend_schema(
        summary="List all customers",
        description="Retrieve a list of all customers in the system. Requires admin access."
    ),
    create=extend_schema(
        summary="Create a new customer",
        description="Create a new customer profile. Requires admin access."
    ),
    retrieve=extend_schema(
        summary="Get customer details",
        description="Retrieve detailed information about a specific customer."
    ),
    update=extend_schema(
        summary="Update customer",
        description="Update all fields of a customer profile."
    ),
    partial_update=extend_schema(
        summary="Partially update customer",
        description="Update specific fields of a customer profile."
    ),
    destroy=extend_schema(
        summary="Delete customer",
        description="Remove a customer from the system."
    ),
)
class CustomerViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing customer profiles.

    Provides CRUD operations for customer management.
    Only authenticated admin users can access these endpoints.
    """
    require_tenant = False
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]


@extend_schema_view(
    list=extend_schema(
        summary="List all repairs",
        description="Retrieve a list of all repairs in the system. Requires admin access."
    ),
    create=extend_schema(
        summary="Create a new repair",
        description="Create a new repair record. The repair will be automatically associated with the authenticated technician."
    ),
    retrieve=extend_schema(
        summary="Get repair details",
        description="Retrieve detailed information about a specific repair."
    ),
    update=extend_schema(
        summary="Update repair",
        description="Update all fields of a repair record."
    ),
    partial_update=extend_schema(
        summary="Partially update repair",
        description="Update specific fields of a repair record."
    ),
    destroy=extend_schema(
        summary="Delete repair",
        description="Remove a repair record from the system."
    ),
)
class RepairViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing repair records.

    Provides CRUD operations for repair management.
    When creating a repair, it will be automatically associated with the authenticated technician.
    Only authenticated admin users can access these endpoints.
    """
    require_tenant = False
    queryset = Repair.objects.select_related(
        'technician__user', 'customer'
    ).prefetch_related('applied_rewards').all()
    serializer_class = RepairSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]

    def perform_create(self, serializer):
        """Associate the repair with the logged-in technician"""
        serializer.save(technician=self.request.user.technician)


@extend_schema_view(
    list=extend_schema(
        summary="List all replacements",
        description="Retrieve a list of all glass replacements in the system. Requires admin access."
    ),
    create=extend_schema(
        summary="Create a new replacement",
        description="Create a new glass replacement record. Requires admin access."
    ),
    retrieve=extend_schema(
        summary="Get replacement details",
        description="Retrieve detailed information about a specific replacement."
    ),
    update=extend_schema(
        summary="Update replacement",
        description="Update all fields of a replacement record."
    ),
    partial_update=extend_schema(
        summary="Partially update replacement",
        description="Update specific fields of a replacement record."
    ),
    destroy=extend_schema(
        summary="Delete replacement",
        description="Remove a replacement record from the system."
    ),
)
class ReplacementViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing glass replacement records.

    Provides CRUD operations for replacement management.
    Only authenticated admin users can access these endpoints.
    """
    require_tenant = False
    queryset = Replacement.objects.select_related(
        'technician__user', 'customer'
    ).all()
    serializer_class = ReplacementSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]

    def perform_create(self, serializer):
        """Associate the replacement with the logged-in technician"""
        serializer.save(technician=self.request.user.technician)
