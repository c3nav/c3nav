from collections import OrderedDict, namedtuple

from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language

from c3nav.mapdata.models.level import Level
from c3nav.mapdata.models.package import Package

from ..fields import GeometryField


class FeatureType(namedtuple('FeatureType', ('name', 'title', 'title_plural', 'geomtype', 'color'))):
    def __init__(self, *args, **kwargs):
        FEATURE_TYPES[self.name] = self


FEATURE_TYPES = OrderedDict()
FeatureType('building', _('Building'), _('Buildings'), 'polygon', '#333333')
FeatureType('room', _('Room'), _('Rooms'), 'polygon', '#CCCCCC')
FeatureType('outside', _('Outside Area'), _('Outside Areas'), 'polygon', '#EEEEEE')
FeatureType('obstacle', _('Obstacle'), _('Obstacles'), 'polygon', '#999999')


# FeatureType('door', _('Door'), 'polygon', '#FF00FF')
# FeatureType('step', _('Step'), 'polyline', '#FF0000')
# FeatureType('elevator', _('Elevator'), 'polygon', '#99CC00')


class Feature(models.Model):
    """
    A map feature
    """
    TYPES = tuple((name, t.title) for name, t in FEATURE_TYPES.items())

    name = models.SlugField(_('feature identifier'), primary_key=True, max_length=50, help_text=_('e.g. noc'))
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='features',
                                verbose_name=_('map package'))
    feature_type = models.CharField(max_length=50, choices=TYPES)
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='features',
                              verbose_name=_('level'))
    geometry = GeometryField()

    @property
    def titles(self):
        return {title.language: title.title for title in self.featuretitles.all()}

    @property
    def title(self):
        titles = self.titles
        lang = get_language()
        if lang in titles:
            return titles[lang]
        return next(iter(titles.values())) if titles else self.name


class FeatureTitle(models.Model):
    feature = models.ForeignKey('Feature', on_delete=models.CASCADE, related_name='featuretitles',
                                verbose_name=_('map package'))
    language = models.CharField(max_length=50)
    title = models.CharField(max_length=50)

    class Meta:
        unique_together = ('feature', 'language')
