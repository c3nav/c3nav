from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models.base import SerializableMixin, TitledMixin


class AccessRestriction(TitledMixin, models.Model):
    """
    An access restriction, currently without finetuning
    """

    class Meta:
        verbose_name = _('Access Restriction')
        verbose_name_plural = _('Access Restrictions')
        default_related_name = 'accessrestrictions'

    @classmethod
    def qs_for_request(cls, request):
        if request.user.is_authenticated and request.user.is_superuser:
            return cls.objects.all()
        return cls.objects.none()


class AccessRestrictionMixin(SerializableMixin, models.Model):
    access_restriction = models.ForeignKey(AccessRestriction, null=True, blank=True,
                                           verbose_name=_('Access Restriction'))

    class Meta:
        abstract = True

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['access_restriction'] = self.access_restriction_id
        return result

    @classmethod
    def qs_for_request(cls, request):
        if request.user.is_authenticated and request.user.is_superuser:
            return cls.objects.all()
        return cls.objects.filter(access_restriction__isnull=True)
