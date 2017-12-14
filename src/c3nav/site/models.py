from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import I18nField


class Announcement(models.Model):
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    active_until = models.DateTimeField(null=True, verbose_name=_('active until'))
    active = models.BooleanField(default=True, verbose_name=_('active'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('author'))
    text = I18nField(_('Text'), fallback_any=True)

    class Meta:
        verbose_name = _('Announcement')
        verbose_name_plural = _('Announcements')
        default_related_name = 'announcements'
        get_latest_by = 'created'

    @classmethod
    def get_current(cls):
        result = cache.get('site:announcement', False)
        if result is not False:
            return result

        try:
            result = cls.objects.filter(Q(active=True) & (Q(active_until__isnull=True) |
                                                          Q(active_until__gt=timezone.now()))).latest()
        except cls.DoesNotExist:
            result = None

        timeout = 300
        if result and result.active_until:
            timeout = max(0, min(timeout, (result.active_until-timezone.now()).total_seconds()))
        cache.set('site:announcement', result, timeout)

        return result

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete('site:announcement')
