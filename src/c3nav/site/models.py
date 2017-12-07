from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import I18nField


class Announcement(models.Model):
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    active_until = models.DateTimeField(null=True, verbose_name=_('active until'))
    active = models.BooleanField(default=True, verbose_name=_('active'))
    message = I18nField(_('Message'))

    class Meta:
        verbose_name = _('Announcement')
        verbose_name_plural = _('Announcements')
        default_related_name = 'announcements'
        get_latest_by = 'created'

    @classmethod
    def get_current(cls):
        try:
            return cls.objects.filter(Q(active=True) & (Q(active_until__isnull=True) |
                                                        Q(active_until__isnull=timezone.now()))).latest()
        except cls.DoesNotExist:
            return None
