from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils.functional import lazy
from django.utils.translation import ugettext_lazy as _


class UserPermissions(models.Model):
    """
    User Permissions
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True)

    review_changesets = models.BooleanField(default=False, verbose_name=_('can review changesets'))
    direct_edit = models.BooleanField(default=False, verbose_name=_('can activate direct editing'))
    max_changeset_changes = models.PositiveSmallIntegerField(default=10, verbose_name=_('max changes per changeset'))
    editor_access = models.BooleanField(default=False, verbose_name=_('can always access editor'))
    base_mapdata_access = models.BooleanField(default=False, verbose_name=_('can always access base map data'))

    control_panel = models.BooleanField(default=False, verbose_name=_('can access control panel'))
    grant_permissions = models.BooleanField(default=False, verbose_name=_('can grant control permissions'))
    manage_announcements = models.BooleanField(default=False, verbose_name=_('manage announcements'))
    grant_all_access = models.BooleanField(default=False, verbose_name=_('can grant access to everything'))
    api_secret = models.CharField(null=True, blank=True, max_length=64, verbose_name=_('API secret'))

    class Meta:
        verbose_name = _('User Permissions')
        verbose_name_plural = _('User Permissions')
        default_related_name = 'permissions'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user_id and self.user.is_superuser:
            for field in UserPermissions._meta.get_fields():
                if isinstance(field, models.BooleanField):
                    setattr(self, field.name, True)

    @staticmethod
    def get_cache_key(pk):
        return 'control:permissions:%d' % pk

    @classmethod
    def cache_key_for_request(cls):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.user_id and self.user.is_superuser:
                for field in UserPermissions._meta.get_fields():
                    if isinstance(field, models.BooleanField):
                        setattr(self, field.name, True)

    @classmethod
    def get_for_user(cls, user, force=False) -> 'UserPermissions':
        if not user.is_authenticated:
            return cls()
        cache_key = cls.get_cache_key(user.pk)
        result = None
        if not force:
            result = cache.get(cache_key, None)
            for field in cls._meta.get_fields():
                if not hasattr(result, field.attname):
                    result = None
                    break
        if result:
            return result
        try:
            result = user.permissions
        except AttributeError:
            result = cls(user=user)
        cache.set(cache_key, result, 900)
        return result

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache_key = self.get_cache_key(self.pk)
        cache.set(cache_key, self, 900)

    @property
    def can_access_base_mapdata(self):
        return False
        return settings.PUBLIC_BASE_MAPDATA or self.base_mapdata_access


get_permissions_for_user_lazy = lazy(UserPermissions.get_for_user, UserPermissions)
