import pickle
import uuid
from collections import namedtuple
from datetime import timedelta
from typing import Sequence

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.base import SerializableMixin, TitledMixin


class AccessRestriction(TitledMixin, models.Model):
    """
    An access restriction
    """
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, through='AccessPermission',
                                   through_fields=('access_restriction', 'user'))
    open = models.BooleanField(default=False, verbose_name=_('open'))

    class Meta:
        verbose_name = _('Access Restriction')
        verbose_name_plural = _('Access Restrictions')
        default_related_name = 'accessrestrictions'

    @classmethod
    def qs_for_request(cls, request):
        return cls.objects.all()


def default_valid_until():
    return timezone.now()+timedelta(seconds=20)


AccessPermissionTokenItem = namedtuple('AccessPermissionTokenItem', ('pk', 'expire_date', 'title'))


class AccessPermissionToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                               related_name='created_accesspermission_tokens',
                               verbose_name=_('author'))
    valid_until = models.DateTimeField(db_index=True, default=default_valid_until,
                                       verbose_name=_('valid until'))
    unlimited = models.BooleanField(default=False, db_index=True, verbose_name=_('unlimited'))
    redeemed = models.BooleanField(default=False, db_index=True, verbose_name=_('redeemed'))
    redeemed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                    related_name='redeemed_accesspermission_tokens',
                                    verbose_name=_('redeemed by'))

    can_grant = models.BooleanField(default=False, db_index=True, verbose_name=_('can grant'))
    data = models.BinaryField()

    @property
    def restrictions(self) -> Sequence[AccessPermissionTokenItem]:
        return pickle.loads(self.data)

    @restrictions.setter
    def restrictions(self, value: Sequence[AccessPermissionTokenItem]):
        self.data = pickle.dumps(value)

    class RedeemError(Exception):
        pass

    def redeem(self, user=None):
        if self.redeemed_by_id or (user is None and self.redeemed):
            raise self.RedeemError('Already redeemed.')

        if timezone.now() > self.valid_until + timedelta(minutes=5 if self.redeemed else 0):
            raise self.RedeemError('No longer valid.')

        self.redeemed = True
        if user:
            for restriction in self.restrictions:
                obj, created = AccessPermission.objects.get_or_create(
                    user=user,
                    access_restriction_id=restriction.pk
                )
                obj.author_id = self.author_id
                obj.expire_date = restriction.expire_date
                obj.can_grant = self.can_grant
                obj.save()
            self.redeemed_by = user

        if self.pk:
            self.save()

    def bump(self):
        self.valid_until = max(self.valid_until, default_valid_until())

    @property
    def redeem_success_message(self):
        return ungettext_lazy('Area successfully unlocked.', 'Areas successfully unlocked.', len(self.restrictions))


class AccessPermission(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    access_restriction = models.ForeignKey(AccessRestriction, on_delete=models.CASCADE)
    expire_date = models.DateTimeField(null=True, verbose_name=_('expires'))
    can_grant = models.BooleanField(default=False, verbose_name=_('can grant'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                               related_name='authored_access_permissions', verbose_name=_('Author'))

    class Meta:
        verbose_name = _('Access Permission')
        verbose_name_plural = _('Access Permissions')
        default_related_name = 'accesspermissions'
        unique_together = (('user', 'access_restriction'), )

    @staticmethod
    def user_access_permission_key(user_id):
        return 'mapdata:user_access_permission:%d' % user_id

    @classmethod
    def get_for_request(cls, request):
        if not request.user.is_authenticated:
            return set()

        cache_key = cls.user_access_permission_key(request.user.pk)
        access_restriction_ids = cache.get(cache_key, None)
        if access_restriction_ids is None:
            result = tuple(request.user.accesspermissions.filter(
                Q(expire_date__isnull=True) | Q(expire_date__gt=timezone.now())
            ).values_list('access_restriction_id', 'expire_date'))
            if result:
                access_restriction_ids, expire_dates = zip(*result)
            else:
                access_restriction_ids, expire_dates = (), ()

            expire_date = min((e for e in expire_dates if e), default=timezone.now()+timedelta(seconds=120))
            cache.set(cache_key, access_restriction_ids, max(0, (expire_date-timezone.now()).total_seconds()))
        return set(access_restriction_ids)

    @classmethod
    def cache_key_for_request(cls, request, with_update=True):
        return (
            ((MapUpdate.current_cache_key()+':') if with_update else '') +
            ','.join(str(i) for i in sorted(AccessPermission.get_for_request(request)) or '0')
        )

    @classmethod
    def etag_func(cls, request, *args, **kwargs):
        return cls.cache_key_for_request(request)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete(self.user_access_permission_key(self.user_id)))

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete(self.user_access_permission_key(self.user_id)))


class AccessRestrictionMixin(SerializableMixin, models.Model):
    access_restriction = models.ForeignKey(AccessRestriction, null=True, blank=True,
                                           verbose_name=_('Access Restriction'))

    class Meta:
        abstract = True

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['access_restriction'] = self.access_restriction_id
        return result

    def details_display(self):
        result = super().details_display()
        result['display'].extend([
            (_('Access Restriction'), self.access_restriction_id and self.access_restriction.title),
        ])
        return result

    @classmethod
    def qs_for_request(cls, request, allow_none=False):
        return cls.objects.filter(cls.q_for_request(request, allow_none=allow_none))

    @classmethod
    def q_for_request(cls, request, prefix='', allow_none=False):
        if request is None and allow_none:
            return Q()
        return (Q(**{prefix+'access_restriction__isnull': True}) |
                Q(**{prefix+'access_restriction__pk__in': AccessPermission.get_for_request(request)}))
