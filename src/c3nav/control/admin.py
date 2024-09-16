from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from c3nav.control.models import UserPermissions
from c3nav.mapdata.models.access import AccessPermissionSSOGrant


class UserPermissionsInline(admin.StackedInline):
    model = UserPermissions
    can_delete = False


class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password', 'email')}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    readonly_fields = ('last_login', 'date_joined')
    inlines = (UserPermissionsInline, )

    def get_view_on_site_url(self, obj=None):
        return None if obj is None else reverse('control.users.detail', args=[obj.pk])


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(AccessPermissionSSOGrant)
class AccessPermissionSSOGrantAdmin(admin.ModelAdmin):
    model = AccessPermissionSSOGrant
