from django.contrib import admin
from .models import Tenant, TenantMembership


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 1
    raw_id_fields = ['user']


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'owner', 'plan', 'is_active', 'created_at']
    list_filter = ['is_active', 'plan']
    search_fields = ['name', 'slug', 'subdomain']
    prepopulated_fields = {'slug': ('name',)}
    raw_id_fields = ['owner']
    inlines = [TenantMembershipInline]
    readonly_fields = ['created_at', 'updated_at']


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'tenant', 'role', 'is_active', 'joined_at']
    list_filter = ['role', 'is_active']
    search_fields = ['user__username', 'user__email', 'tenant__name']
    raw_id_fields = ['user', 'tenant']
