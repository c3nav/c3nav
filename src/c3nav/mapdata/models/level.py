from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.ops import cascaded_union

from c3nav.mapdata.models.base import MapItem


class Level(MapItem):
    """
    A map level (-1, 0, 1, 2…)
    """
    name = models.SlugField(_('level name'), unique=True, max_length=50,
                            help_text=_('Usually just an integer (e.g. -1, 0, 1, 2)'))
    altitude = models.DecimalField(_('level altitude'), null=True, max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _('Level')
        verbose_name_plural = _('Levels')
        default_related_name = 'levels'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.geometries = LevelGeometries(self)

    def tofilename(self):
        return 'levels/%s.json' % self.name

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'altitude' not in data:
            raise ValueError('missing altitude.')

        if not isinstance(data['altitude'], (int, float)):
            raise ValueError('altitude has to be int or float.')

        kwargs['altitude'] = data['altitude']

        return kwargs

    def tofile(self):
        result = super().tofile()
        result['altitude'] = float(self.altitude)
        return result


class LevelGeometries():
    def __init__(self, level):
        self.level = level

    @cached_property
    def buildings(self):
        return cascaded_union([building.geometry for building in self.level.buildings.all()])

    @cached_property
    def areas(self):
        return cascaded_union([area.geometry for area in self.level.areas.all()])
