import os
from collections import OrderedDict, namedtuple

from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import activate, get_language
from shapely.geometry import mapping, shape

from c3nav.mapdata.fields import GeometryField, JSONField
from c3nav.mapdata.utils import format_geojson


class FeatureType(namedtuple('FeatureType', ('name', 'title', 'title_plural', 'geomtype', 'color'))):
    # noinspection PyUnusedLocal
    def __init__(self, *args, **kwargs):
        super().__init__()
        FEATURE_TYPES[self.name] = self

    @property
    def title_en(self):
        language = get_language()
        activate('en')
        title = str(self.title)
        activate(language)
        return title


FEATURE_TYPES = OrderedDict()
FeatureType('building', _('Building'), _('Buildings'), 'polygon', '#333333')
FeatureType('room', _('Room'), _('Rooms'), 'polygon', '#FFFFFF')
FeatureType('outside', _('Outside Area'), _('Outside Areas'), 'polygon', '#FFFFFF')
FeatureType('obstacle', _('Obstacle'), _('Obstacles'), 'polygon', '#999999')


# FeatureType('door', _('Door'), 'polygon', '#FF00FF')
# FeatureType('step', _('Step'), 'polyline', '#FF0000')
# FeatureType('elevator', _('Elevator'), 'polygon', '#99CC00')


class Feature(models.Model):
    """
    A map feature
    """
    TYPES = tuple((name, t.title) for name, t in FEATURE_TYPES.items())

    name = models.SlugField(_('feature identifier'), unique=True, max_length=50)
    package = models.ForeignKey('mapdata.Package', on_delete=models.CASCADE, related_name='features',
                                verbose_name=_('map package'))
    feature_type = models.CharField(max_length=50, choices=TYPES)
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, related_name='features',
                              verbose_name=_('level'))
    titles = JSONField()
    geometry = GeometryField()

    path_regex = r'^features/('+'|'.join(name for name, title in TYPES)+')/'

    @property
    def title(self):
        lang = get_language()
        if lang in self.titles:
            return self.titles[lang]
        return next(iter(self.titles.values())) if self.titles else self.name

    def tofilename(self):
        return 'features/%s/%s.json' % (self.feature_type, self.name)

    def get_feature_type(self):
        return FEATURE_TYPES[self.feature_type]

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = {}
        kwargs['feature_type'] = file_path.split(os.path.sep)[1]

        if 'geometry' not in data:
            raise ValueError('missing geometry.')
        try:
            kwargs['geometry'] = shape(data['geometry'])
        except:
            raise ValueError(_('Invalid GeoJSON.'))

        if 'level' not in data:
            raise ValueError('missing level.')
        kwargs['level'] = data['level']

        if 'titles' not in data:
            raise ValueError('missing titles.')
        titles = data['titles']
        if not isinstance(titles, dict):
            raise ValueError('Invalid titles format.')
        if any(not isinstance(lang, str) for lang in titles.keys()):
            raise ValueError('titles: All languages have to be strings.')
        if any(not isinstance(title, str) for title in titles.values()):
            raise ValueError('titles: All titles have to be strings.')
        if any(not title for title in titles.values()):
            raise ValueError('titles: Titles must not be empty strings.')
        kwargs['titles'] = titles
        return kwargs

    def tofile(self):
        return OrderedDict((
            ('titles', OrderedDict(sorted(self.titles.items()))),
            ('level', self.level.name),
            ('geometry', format_geojson(mapping(self.geometry)))
        ))
