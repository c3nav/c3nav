from contextlib import contextmanager
from typing import Self

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import models, transaction
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django_pydantic_field.fields import SchemaField

from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.level import Space


class UserPermissions(models.Model):
    """
    User Permissions
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True)

    review_changesets = models.BooleanField(default=False, verbose_name=_('can review changesets'))
    direct_edit = models.BooleanField(default=False, verbose_name=_('can activate direct editing'))
    max_changeset_changes = models.PositiveSmallIntegerField(default=20, verbose_name=_('max changes per changeset'))
    editor_access = models.BooleanField(default=False, verbose_name=_('can always access editor'))
    sources_access = models.BooleanField(default=False, verbose_name=_('can access sources in editor'))
    base_mapdata_access = models.BooleanField(default=False, verbose_name=_('can always access base map data'))
    manage_map_updates = models.BooleanField(default=False, verbose_name=_('manage map updates'))

    view_users = models.BooleanField(default=False, verbose_name=_('view user list in control panel'))
    grant_permissions = models.BooleanField(default=False, verbose_name=_('can grant control permissions'))
    manage_announcements = models.BooleanField(default=False, verbose_name=_('manage announcements'))
    grant_all_access = models.BooleanField(default=False, verbose_name=_('can grant access to everything'))
    grant_unlimited_access = models.BooleanField(default=False, verbose_name=_('grant unlimited access'))
    grant_space_access = models.BooleanField(default=False, verbose_name=_('can grant space access'))

    review_all_reports = models.BooleanField(default=False, verbose_name=_('can review all reports'))
    review_group_reports = models.ManyToManyField('mapdata.LocationGroup', blank=True,
                                                  limit_choices_to={'access_restriction': None},
                                                  verbose_name=_('can review reports belonging to'))

    mesh_control = models.BooleanField(default=False, verbose_name=_('can access mesh control'))

    nonpublic_themes = models.BooleanField(default=False, verbose_name=_('show non-public themes in theme selector'))
    quests: list[str] = SchemaField(schema=list[str], default=list)
    impolite_quests = models.BooleanField(default=False, verbose_name=_('dont say thanks after completing a quest'))
    passive_ap_name_scanning = models.BooleanField(default=False, verbose_name=_('passive ap name scanning'))
    can_write_load_data = models.BooleanField(default=False, verbose_name=_('write load data'))

    class Meta:
        verbose_name = _('User Permissions')
        verbose_name_plural = _('User Permissions')
        default_related_name = 'permissions'

    def __init__(self, *args, initial=False, **kwargs):
        super().__init__(*args, **kwargs)
        if initial and self.user_id and self.user.is_superuser:
            for field in UserPermissions._meta.get_fields():
                if isinstance(field, models.BooleanField):
                    setattr(self, field.name, True)

    @property
    def control_panel(self):
        return bool(
            self.view_users
            or self.grant_permissions
            or self.manage_announcements
            or self.grant_all_access
            or self.grant_unlimited_access
            or self.grant_space_access
            or AccessPermission.get_for_user(user=self.user if self.user_id else None, can_grant=True)
        )

    @staticmethod
    def get_cache_key(pk):
        return 'control:permissions:%d' % pk

    @cached_property
    def review_group_ids(self):
        if self.pk is None:
            return ()
        return tuple(self.review_group_reports.values_list('pk', flat=True))

    @cached_property
    def can_review_reports(self):
        return self.review_all_reports or self.review_group_ids

    @classmethod
    @contextmanager
    def lock(cls, pk):
        with transaction.atomic():
            User.objects.filter(pk=pk).select_for_update()
            yield

    @classmethod
    def get_for_user(cls, user, force=False) -> Self:
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
        with cls.lock(user.pk):
            result = cls.objects.filter(pk=user.pk).first()
            if not result:
                result = cls(user=user, initial=True)
            cache.set(cache_key, result, 900)
            # noinspection PyStatementEffect
            result.review_group_ids
            cache.set(cache_key, result, 900)
        return result

    def save(self, *args, **kwargs):
        with self.lock(self.user_id):
            super().save(*args, **kwargs)
            cache_key = self.get_cache_key(self.pk)
            cache.set(cache_key, self, 900)

    @property
    def can_access_base_mapdata(self):
        return settings.PUBLIC_BASE_MAPDATA or self.base_mapdata_access

    @property
    def can_manage_mesh(self):
        return settings.ENABLE_MESH and self.mesh_control


class UserSpaceAccess(models.Model):
    """
    User Authorities
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    space = models.ForeignKey(Space, on_delete=models.CASCADE)
    can_edit = models.BooleanField(_('can edit'), default=False)

    class Meta:
        verbose_name = _('user space access')
        verbose_name_plural = _('user space accesses')
        default_related_name = 'spaceaccesses'
        unique_together = (('user', 'space'))

    @staticmethod
    def get_cache_key(pk):
        return 'control:spaceaccesses:%d' % pk

    @classmethod
    def get_for_user(cls, user, force=False) -> dict[int, bool]:
        if not user.is_authenticated:
            return {}
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
        with UserPermissions.lock(user.pk):
            result = dict(cls.objects.filter(user=user).values_list('space_id', 'can_edit'))
            cache.set(cache_key, result, 900)
        return result

    def save(self, *args, **kwargs):
        with UserPermissions.lock(self.user_id):
            UserPermissions.objects.filter(user_id=self.user_id).select_for_update()
            super().save(*args, **kwargs)
            cache_key = self.get_cache_key(self.user_id)
            cache.delete(cache_key)
