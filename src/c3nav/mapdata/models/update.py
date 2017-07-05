from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _


class MapUpdate(models.Model):
    """
    A map update. created whenever mapdata is changed.
    """
    datetime = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    type = models.CharField(max_length=32)

    class Meta:
        verbose_name = _('Map update')
        verbose_name_plural = _('Map updates')
        default_related_name = 'mapupdates'
        get_latest_by = 'datetime'

    def save(self, **kwargs):
        if self.pk is not None:
            raise TypeError
