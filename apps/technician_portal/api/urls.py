from rest_framework import routers
from .views import TechnicianViewSet, CustomerViewSet, RepairViewSet, ReplacementViewSet

router = routers.DefaultRouter()
router.register(r'technicians', TechnicianViewSet)
router.register(r'customers', CustomerViewSet)
router.register(r'repairs', RepairViewSet)
router.register(r'replacements', ReplacementViewSet)

urlpatterns = router.urls
