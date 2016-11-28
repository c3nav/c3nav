from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import JOIN_STYLE
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
    def rooms(self):
        return cascaded_union([room.geometry for room in self.level.rooms.all()]).intersection(self.buildings)

    @cached_property
    def outsides(self):
        return cascaded_union([outside.geometry for outside in self.level.outsides.all()]).difference(self.buildings)

    @cached_property
    def mapped(self):
        return cascaded_union([self.buildings, self.outsides])

    @cached_property
    def obstacles(self):
        return cascaded_union([obstacle.geometry for obstacle in self.level.obstacles.all()])

    @cached_property
    def raw_doors(self):
        return cascaded_union([door.geometry for door in self.level.doors.all()]).intersection(self.mapped)

    @cached_property
    def areas_and_doors(self):
        return cascaded_union([self.rooms, self.raw_doors])

    @cached_property
    def walls(self):
        return self.buildings.difference(self.rooms)

    @cached_property
    def walls_without_doors(self):
        return self.walls.difference(self.areas_and_doors)

    @cached_property
    def walls_shadow(self):
        return self.walls_without_doors.buffer(0.2, join_style=JOIN_STYLE.mitre).intersection(self.mapped)

    @cached_property
    def doors(self):
        return self.raw_doors.difference(self.rooms).difference(self.outsides)
