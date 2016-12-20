from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _

from c3nav.control.models import AccessOperator, AccessToken, AccessTokenInstance, AccessUser


class AccessOperatorInline(admin.StackedInline):
    model = AccessOperator
    can_delete = False


class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password', 'email')}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser',
                                       'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    readonly_fields = ('last_login', 'date_joined',)
    inlines = (AccessOperatorInline, )


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


class AccessTokenInline(admin.TabularInline):
    model = AccessToken
    show_change_link = True
    readonly_fields = ('author', 'permissions', 'description', 'creation_date', 'expires')

    def has_add_permission(self, request):
        return False


@admin.register(AccessUser)
class AccessUserAdmin(admin.ModelAdmin):
    inlines = (AccessTokenInline,)
    list_display = ('user_url', 'creation_date', 'author', 'description')
    fields = ('user_url', 'creation_date', 'author', 'description')
    readonly_fields = ('creation_date', )


class AccessTokenInstanceInline(admin.TabularInline):
    model = AccessTokenInstance
    fields = ('secret', 'creation_date', 'expires', )
    readonly_fields = ('secret', 'creation_date', 'expires', )

    def has_add_permission(self, request):
        return False


@admin.register(AccessToken)
class AccessTokenAdmin(admin.ModelAdmin):
    inlines = (AccessTokenInstanceInline,)
    list_display = ('__str__', 'user', 'permissions', 'author', 'creation_date', 'expires')
    fields = ('user', 'permissions', 'author', 'creation_date', 'expires')
    readonly_fields = ('user', 'creation_date')

    def has_add_permission(self, request):
        return False
