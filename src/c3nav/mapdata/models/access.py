import pickle
import uuid
from collections import namedtuple
from datetime import timedelta
from typing import Sequence

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.db.models import CheckConstraint, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.base import SerializableMixin, TitledMixin


class AccessRestriction(TitledMixin, models.Model):
    """
    An access restriction
    """
    public = models.BooleanField(default=False, verbose_name=_('public'))

    class Meta:
        verbose_name = _('Access Restriction')
        verbose_name_plural = _('Access Restrictions')
        default_related_name = 'accessrestrictions'

    @classmethod
    def qs_for_request(cls, request):
        return cls.objects.filter(cls.q_for_request(request))

    @classmethod
    def q_for_request(cls, request):
        return Q(pk__in=AccessPermission.get_for_request(request))

    @staticmethod
    def get_all() -> set[int]:
        cache_key = 'all_access_restrictions:%s' % MapUpdate.current_cache_key()
        access_restriction_ids = cache.get(cache_key, None)
        if access_restriction_ids is None:
            access_restriction_ids = set(AccessRestriction.objects.values_list('pk', flat=True))
            cache.set(cache_key, access_restriction_ids, 300)
        return access_restriction_ids

    @staticmethod
    def get_all_public() -> set[int]:
        cache_key = 'public_access_restrictions:%s' % MapUpdate.current_cache_key()
        access_restriction_ids = cache.get(cache_key, None)
        if access_restriction_ids is None:
            access_restriction_ids = set(AccessRestriction.objects.filter(public=True)
                                         .values_list('pk', flat=True))
            cache.set(cache_key, access_restriction_ids, 300)
        return access_restriction_ids


class AccessRestrictionGroup(TitledMixin, models.Model):
    """
    An access restriction group
    """
    members = models.ManyToManyField('mapdata.AccessRestriction', verbose_name=_('Access Restrictions'), blank=True,
                                     related_name="groups")

    class Meta:
        verbose_name = _('Access Restriction Group')
        verbose_name_plural = _('Access Restriction Groups')
        default_related_name = 'accessrestrictiongroups'

    @classmethod
    def qs_for_request(cls, request, can_grant=None):
        return cls.objects.filter(cls.q_for_request(request, can_grant=can_grant))

    @classmethod
    def q_for_request(cls, request, can_grant=None):
        if request.user.is_authenticated and request.user.is_superuser:
            return Q()
        all_permissions = AccessRestriction.get_all()
        permissions = AccessPermission.get_for_request(request, can_grant=can_grant)
        # now we filter out groups where the user doesn't have a permission for all members
        filter_perms = all_permissions - permissions
        return ~Q(members__pk__in=filter_perms)

    @classmethod
    def qs_for_user(cls, user, can_grant=None):
        return cls.objects.filter(cls.q_for_user(user, can_grant=can_grant))

    @classmethod
    def q_for_user(cls, user, can_grant=None):
        if user.is_authenticated and user.is_superuser:
            return Q()
        all_permissions = AccessRestriction.get_all()
        permissions = AccessPermission.get_for_user(user, can_grant=can_grant)
        # now we filter out groups where the user doesn't have a permission for all members
        filter_perms = all_permissions - permissions
        return ~Q(members__pk__in=filter_perms)


def default_valid_until():
    return timezone.now()+timedelta(seconds=20)


AccessPermissionTokenItem = namedtuple('AccessPermissionTokenItem', ('pk', 'expire_date', 'title'))


class AccessPermissionToken(models.Model):
    token = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                               related_name='created_accesspermission_tokens',
                               verbose_name=_('author'))
    valid_until = models.DateTimeField(db_index=True, default=default_valid_until,
                                       verbose_name=_('valid until'))
    unlimited = models.BooleanField(default=False, db_index=True, verbose_name=_('unlimited'))
    redeemed = models.BooleanField(default=False, db_index=True, verbose_name=_('redeemed'))
    can_grant = models.BooleanField(default=False, db_index=True, verbose_name=_('can grant'))
    unique_key = models.CharField(max_length=32, null=True, verbose_name=_('unique key'))
    data = models.BinaryField()

    class Meta:
        verbose_name = _('Access Permission Token')
        verbose_name_plural = _('Access Permission Tokens')
        default_related_name = 'accessrestriction_tokens'

    @property
    def restrictions(self) -> Sequence[AccessPermissionTokenItem]:
        return pickle.loads(self.data)

    @restrictions.setter
    def restrictions(self, value: Sequence[AccessPermissionTokenItem]):
        self.data = pickle.dumps(value)

    class RedeemError(Exception):
        pass

    def redeem(self, /, user=None, request=None):
        if user is None and request is not None:
            if request.user.is_authenticated:
                user = request.user

        grant_to = None
        if user:
            grant_to = {"user": user}
        elif request:
            grant_to = {
                "session_token": request.session.setdefault("accesspermission_session_token", str(uuid.uuid4()))
            }

        if (grant_to is None and self.redeemed) or (self.pk and self.accesspermissions.exists() and not self.unlimited):
            raise self.RedeemError('Already redeemed.')

        if timezone.now() > self.valid_until + timedelta(minutes=5 if self.redeemed else 0):
            raise self.RedeemError('No longer valid.')

        if grant_to:
            with transaction.atomic():
                if self.author_id and self.unique_key:
                    AccessPermission.objects.filter(author_id=self.author_id, unique_key=self.unique_key).delete()
                for restriction in self.restrictions:
                    to_grant = (
                        {"access_restriction_id": restriction.pk}
                        if isinstance(restriction.pk, int)
                        else {"access_restriction_group_id": int(restriction.pk.removeprefix("g"))}
                    )
                    AccessPermission.objects.create(
                        **grant_to,
                        **to_grant,
                        author_id=self.author_id,
                        expire_date=restriction.expire_date,
                        can_grant=self.can_grant,
                        unique_key=self.unique_key,
                        token=self if self.pk else None,
                    )

        if self.pk and not self.unlimited:
            self.redeemed = True
            self.save()

    def bump(self):
        if not self.unlimited:
            self.valid_until = max(self.valid_until, default_valid_until())

    @property
    def redeem_success_message(self):
        return ngettext_lazy('Area successfully unlocked.', 'Areas successfully unlocked.', len(self.restrictions))


class AccessPermissionSSOGrant(models.Model):
    provider = models.CharField(max_length=32, verbose_name=_('SSO Backend'))
    group = models.CharField(max_length=64, verbose_name=_('SSO Group'))
    access_restriction = models.ForeignKey(AccessRestriction, on_delete=models.CASCADE, null=True, blank=True)
    access_restriction_group = models.ForeignKey(AccessRestrictionGroup, on_delete=models.CASCADE, null=True,
                                                 blank=True)

    class Meta:
        verbose_name = _('Access Permission SSO Grant')
        verbose_name_plural = _('Access Permission SSO Grants')
        default_related_name = 'accesspermission_sso_grants'
        unique_together = (
            ('provider', 'group', 'access_restriction', 'access_restriction_group')
        )
        constraints = (
            CheckConstraint(check=(~Q(access_restriction__isnull=True, access_restriction_group__isnull=True) &
                                   ~Q(access_restriction__isnull=False, access_restriction_group__isnull=False)),
                            name="sso_permission_grant_needs_restriction_or_restriction_group"),
        )


class AccessPermission(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    session_token = models.UUIDField(null=True, editable=False)
    access_restriction = models.ForeignKey(AccessRestriction, on_delete=models.CASCADE, null=True)
    access_restriction_group = models.ForeignKey(AccessRestrictionGroup, on_delete=models.CASCADE, null=True)
    expire_date = models.DateTimeField(null=True, verbose_name=_('expires'))
    can_grant = models.BooleanField(default=False, verbose_name=_('can grant'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                               related_name='authored_access_permissions', verbose_name=_('Author'))
    unique_key = models.CharField(max_length=32, null=True, verbose_name=_('unique key'))
    token = models.ForeignKey(AccessPermissionToken, null=True, on_delete=models.CASCADE,
                              verbose_name=_('Access permission token'))
    sso_grant = models.ForeignKey(AccessPermissionSSOGrant, null=True, on_delete=models.CASCADE,
                                  verbose_name=_('Access Permission SSO Grant'))

    class Meta:
        verbose_name = _('Access Permission')
        verbose_name_plural = _('Access Permissions')
        default_related_name = 'accesspermissions'
        unique_together = (
            ('author', 'unique_key')
        )
        constraints = (
            CheckConstraint(check=(~Q(access_restriction__isnull=True, access_restriction_group__isnull=True) &
                                   ~Q(access_restriction__isnull=False, access_restriction_group__isnull=False)),
                            name="permission_needs_restriction_or_restriction_group"),
            CheckConstraint(check=(~Q(user__isnull=True, session_token__isnull=True) &
                                   ~Q(user__isnull=False, session_token__isnull=False)),
                            name="permission_needs_user_or_session"),
        )

    @staticmethod
    def build_access_permission_key(*, session_token: str | None = None, user_id: int | None = None):
        if session_token:
            if user_id:
                raise ValueError
            return 'mapdata:%s:session_access_permissions:%s' % (MapUpdate.current_cache_key(), session_token)
        elif user_id:
            return 'mapdata:%s:user_access_permissions:%d' % (MapUpdate.current_cache_key(),user_id)
        raise ValueError

    @staticmethod
    def request_access_permission_key(request):
        if request.user.is_authenticated:
            return AccessPermission.build_access_permission_key(user_id=request.user.pk)
        return AccessPermission.build_access_permission_key(
            session_token=request.session.get("accesspermission_session_token", "NONE")
        )

    def access_permission_key(self):
        if self.user_id:
            return AccessPermission.build_access_permission_key(user_id=self.user_id)
        return AccessPermission.build_access_permission_key(session_token=self.session_token)

    @classmethod
    def queryset_for_user(cls, user, can_grant=None):
        # todo: look, for some reason can_grant=False is coded to do the same as can_grant=True. why?
        return user.accesspermissions.filter(
            Q(expire_date__isnull=True) | Q(expire_date__gt=timezone.now())
        ).filter(
            Q(can_grant=True) if can_grant is not None else Q()
        )

    @classmethod
    def queryset_for_session(cls, session):
        session_token = session.get("accesspermission_session_token", None)
        if not session_token:
            return AccessPermission.objects.none()
        return AccessPermission.objects.filter(session_token=session_token).filter(
            Q(expire_date__isnull=True) | Q(expire_date__gt=timezone.now())
        )

    @classmethod
    def get_for_request_with_expire_date(cls, request, can_grant=None):
        # todo: look, for some reason can_grant=False is coded to do the same as can_grant=True. why?
        if request.user.is_authenticated:
            if request.user_permissions.grant_all_access:
                return {pk: None for pk in AccessRestriction.get_all()}
            qs = cls.queryset_for_user(request.user, can_grant)
        else:
            if can_grant:
                return {}
            qs = cls.queryset_for_session(request.session)

        result = tuple(
            qs.select_related(
                'access_restriction_group'
            ).prefetch_related('access_restriction_group__members')
        )

        # collect permissions (can be multiple for one restriction)
        permissions = {}
        for permission in result:
            if permission.access_restriction_id:
                permissions.setdefault(permission.access_restriction_id, set()).add(permission.expire_date)
            if permission.access_restriction_group_id:
                for member in permission.access_restriction_group.members.all():
                    permissions.setdefault(member.pk, set()).add(permission.expire_date)

        # get latest expire date for each permission
        permissions = {
            access_restriction_id: None if None in expire_dates else max(expire_dates)
            for access_restriction_id, expire_dates in permissions.items()
        }
        return permissions

    @classmethod
    def get_for_request(cls, request, can_grant: bool = None) -> set[int]:
        # todo: look, for some reason can_grant=False is coded to do the same as can_grant=True. why?
        if not request:
            return AccessRestriction.get_all_public()

        if request.user.is_authenticated and request.user_permissions.grant_all_access:
            return AccessRestriction.get_all()

        cache_key = cls.request_access_permission_key(request)
        access_restriction_ids = cache.get(cache_key, None)
        if access_restriction_ids is None:
            permissions = cls.get_for_request_with_expire_date(request, can_grant=can_grant)

            access_restriction_ids = set(permissions.keys())

            expire_date = min((e for e in permissions.values() if e), default=timezone.now() + timedelta(seconds=120))
            cache.set(cache_key, access_restriction_ids, min(300, (expire_date - timezone.now()).total_seconds()))
        return set(access_restriction_ids) | (set() if can_grant else AccessRestriction.get_all_public())

    @classmethod
    def get_for_user_with_expire_date(cls, user, can_grant=None):
        # todo: look, for some reason can_grant=False is coded to do the same as can_grant=True. why?
        from c3nav.control.models import UserPermissions
        if UserPermissions.get_for_user(user).grant_all_access:
            return {pk: None for pk in AccessRestriction.get_all()}
        qs = cls.queryset_for_user(user, can_grant)

        result = tuple(
            qs.select_related(
                'access_restriction_group'
            ).prefetch_related('access_restriction_group__members')
        )

        # collect permissions (can be multiple for one restriction)
        permissions = {}
        for permission in result:
            if permission.access_restriction_id:
                permissions.setdefault(permission.access_restriction_id, set()).add(permission.expire_date)
            if permission.access_restriction_group_id:
                for member in permission.access_restriction_group.members.all():
                    permissions.setdefault(member.pk, set()).add(permission.expire_date)

        # get latest expire date for each permission
        permissions = {
            access_restriction_id: None if None in expire_dates else max(expire_dates)
            for access_restriction_id, expire_dates in permissions.items()
        }
        return permissions

    @classmethod
    def get_for_user(cls, user, can_grant: bool = None) -> set[int]:
        # todo: look, for some reason can_grant=False is coded to do the same as can_grant=True. why?
        from c3nav.control.models import UserPermissions
        if not user or not user.is_authenticated:
            return AccessRestriction.get_all_public()

        if UserPermissions.get_for_user(user).grant_all_access:
            return AccessRestriction.get_all()

        cache_key = cls.build_access_permission_key(user_id=user.pk)
        access_restriction_ids = cache.get(cache_key, None)
        if access_restriction_ids is None:
            permissions = cls.get_for_user_with_expire_date(user, can_grant=can_grant)

            access_restriction_ids = set(permissions.keys())

            expire_date = min((e for e in permissions.values() if e), default=timezone.now()+timedelta(seconds=120))
            cache.set(cache_key, access_restriction_ids, min(300, (expire_date-timezone.now()).total_seconds()))
        return set(access_restriction_ids) | (set() if can_grant else AccessRestriction.get_all_public())

    @classmethod
    def cache_key_for_request(cls, request, with_update=True):
        return (
            ((MapUpdate.current_cache_key()+':') if with_update else '') +
            '-'.join(str(i) for i in sorted(AccessPermission.get_for_request(request)) or '0')
        )

    @classmethod
    def etag_func(cls, request, *args, **kwargs):
        return cls.cache_key_for_request(request)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete(self.access_permission_key()))

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete(self.access_permission_key()))


class AccessRestrictionMixin(SerializableMixin, models.Model):
    access_restriction = models.ForeignKey(AccessRestriction, null=True, blank=True,
                                           verbose_name=_('Access Restriction'), on_delete=models.PROTECT)

    class Meta:
        abstract = True

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].extend([
            (_('Access Restriction'), self.access_restriction_id and self.access_restriction.title),
        ])
        return result

    @classmethod
    def q_for_request(cls, request, prefix='', allow_none=False):
        if request is None and allow_none:
            return Q()
        return (Q(**{prefix+'access_restriction__isnull': True}) |
                Q(**{prefix+'access_restriction__pk__in': AccessPermission.get_for_request(request)}))
