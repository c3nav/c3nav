from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _

from c3nav.control.models import UserPermissions


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


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
