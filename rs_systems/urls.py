"""
URL configuration for rs_systems project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from . import views
from core.views import preview_email_template, test_notification, check_notification_prefs, diagnostic_view

urlpatterns = [
    path('', views.home, name='home'),
    path('health/', views.health_check, name='health_check'),  # AWS health check endpoint
    path('setup-database/', views.setup_database, name='setup_database'),

    # Test/diagnostic endpoints (for debugging)
    path('diagnostic/', diagnostic_view, name='diagnostic'),
    path('test-notification/', test_notification, name='test_notification'),
    path('check-notification-prefs/', check_notification_prefs, name='check_notification_prefs'),

    # API endpoints
    path('api/', include('apps.technician_portal.api.urls')),

    # API documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Admin and authentication
    path('admin/register-technician/', views.register_technician, name='register_technician'),
    path('admin/email-preview/<str:template_name>/', preview_email_template, name='email_preview'),
    path('admin/', admin.site.urls),

    # Customer portal (primary users)
    path('app/', include('apps.customer_portal.urls')),
    path('app/login/', views.customer_login_view, name='customer_login'),
    path('app/logout/', views.logout_view, name='customer_logout'),

    # Technician portal
    path('tech/', include('apps.technician_portal.urls')),
    path('tech/login/', views.technician_login_view, name='technician_login'),
    path('tech/logout/', views.logout_view, name='technician_logout'),

    # Rewards/referrals (accessible from both portals)
    path('referrals/', include('apps.rewards_referrals.urls')),

    # Legacy authentication URLs (redirect to appropriate portal)
    path('accounts/login/', views.login_router, name='login'),
    path('login/', views.login_router, name='login_legacy'),
    path('logout/', views.logout_view, name='logout'),
    # path('api-token-auth/', views.obtain_auth_token, name='api_token_auth'),
]

# Serve media files in development and AWS EB (when not using S3)
if settings.DEBUG or (not getattr(settings, 'USE_S3', False)):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
