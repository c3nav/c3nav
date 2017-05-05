from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models.base import Feature


class Source(Feature):
    """
    A map source, images of levels that can be useful as backgrounds for the map editor
    """
    name = models.SlugField(_('Name'), unique=True, max_length=50)
    bottom = models.DecimalField(_('bottom coordinate'), max_digits=6, decimal_places=2)
    left = models.DecimalField(_('left coordinate'), max_digits=6, decimal_places=2)
    top = models.DecimalField(_('top coordinate'), max_digits=6, decimal_places=2)
    right = models.DecimalField(_('right coordinate'), max_digits=6, decimal_places=2)
    image = models.BinaryField(_('image data'))  # todo migrate to better storage

    class Meta:
        verbose_name = _('Source')
        verbose_name_plural = _('Sources')
        default_related_name = 'sources'

    @classmethod
    def max_bounds(cls):
        result = cls.objects.all().aggregate(models.Min('bottom'), models.Min('left'),
                                             models.Max('top'), models.Max('right'))
        return ((float(result['bottom__min']), float(result['left__min'])),
                (float(result['top__max']), float(result['right__max'])))

    @property
    def bounds(self):
        return (float(self.bottom), float(self.left)), (float(self.top), float(self.right))
