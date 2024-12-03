from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.base import BoundsMixin


class Source(BoundsMixin, AccessRestrictionMixin, models.Model):
    """
    A map source, images of levels that can be useful as backgrounds for the map editor
    """
    new_serialize = True

    name = models.CharField(_('Name'), unique=True, max_length=50)  # a slugfield would forbid periods

    class Meta:
        verbose_name = _('Source')
        verbose_name_plural = _('Sources')
        default_related_name = 'sources'

    @property
    def filepath(self):
        return settings.SOURCES_ROOT / self.name

    @property
    def title(self):
        return self.name
