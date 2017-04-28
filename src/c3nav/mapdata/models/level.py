from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import CAP_STYLE, JOIN_STYLE
from shapely.ops import cascaded_union

from c3nav.mapdata.models.base import MapItem
from c3nav.mapdata.utils.geometry import assert_multilinestring, assert_multipolygon


class Level(MapItem):
    """
    A map level (-1, 0, 1, 2…)
    """
    name = models.SlugField(_('level name'), unique=True, max_length=50,
                            help_text=_('Usually just an integer (e.g. -1, 0, 1, 2)'))
    altitude = models.DecimalField(_('level altitude'), null=False, unique=True, max_digits=6, decimal_places=2)
    intermediate = models.BooleanField(_('intermediate level'))

    class Meta:
        verbose_name = _('Level')
        verbose_name_plural = _('Levels')
        default_related_name = 'levels'
        ordering = ['altitude']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @cached_property
    def public_geometries(self):
        return LevelGeometries.by_level(self, only_public=True)

    @cached_property
    def geometries(self):
        return LevelGeometries.by_level(self, only_public=False)

    def lower(self):
        return Level.objects.filter(altitude__lt=self.altitude).order_by('altitude')

    def higher(self):
        return Level.objects.filter(altitude__gt=self.altitude).order_by('altitude')

    def __str__(self):
        return self.name


class LevelGeometries():
    by_level_name = {}

    @classmethod
    def by_level(cls, level, only_public=True):
        return cls.by_level_name.setdefault((level.name, only_public), cls(level, only_public=only_public))

    def __init__(self, level, only_public=True):
        self.level = level
        self.only_public = only_public

        from c3nav.access.apply import get_public_packages
        self.public_packages = get_public_packages()

    def query(self, name):
        queryset = getattr(self.level, name)
        if not self.only_public:
            return queryset.all()
        return queryset.filter(package__in=self.public_packages)

    @cached_property
    def raw_rooms(self):
        return cascaded_union([room.geometry for room in self.query('rooms')])

    @cached_property
    def buildings(self):
        result = cascaded_union([building.geometry for building in self.query('buildings')])
        if self.level.intermediate:
            result = cascaded_union([result, self.raw_rooms])
        return result

    @cached_property
    def rooms(self):
        return self.raw_rooms.intersection(self.buildings)

    @cached_property
    def outsides(self):
        return cascaded_union([outside.geometry for outside in self.query('outsides')]).difference(self.buildings)

    @cached_property
    def mapped(self):
        return cascaded_union([self.buildings, self.outsides])

    @cached_property
    def lineobstacles(self):
        lineobstacles = []
        for obstacle in self.query('lineobstacles'):
            lineobstacles.append(obstacle.geometry.buffer(obstacle.width/2,
                                                          join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat))
        return cascaded_union(lineobstacles)

    @cached_property
    def uncropped_obstacles(self):
        obstacles = [obstacle.geometry for obstacle in self.query('obstacles').filter(crop_to_level__isnull=True)]
        return cascaded_union(obstacles).intersection(self.mapped)

    @cached_property
    def cropped_obstacles(self):
        levels_by_name = {}
        obstacles_by_crop_to_level = {}
        for obstacle in self.query('obstacles').filter(crop_to_level__isnull=False):
            level_name = obstacle.crop_to_level.name
            levels_by_name.setdefault(level_name, obstacle.crop_to_level)
            obstacles_by_crop_to_level.setdefault(level_name, []).append(obstacle.geometry)

        all_obstacles = []
        for level_name, obstacles in obstacles_by_crop_to_level.items():
            obstacles = cascaded_union(obstacles).intersection(levels_by_name[level_name].geometries.mapped)
            all_obstacles.append(obstacles)
        all_obstacles.extend(assert_multipolygon(self.lineobstacles))

        return cascaded_union(all_obstacles).intersection(self.mapped)

    @cached_property
    def obstacles(self):
        return cascaded_union([self.uncropped_obstacles, self.cropped_obstacles])

    @cached_property
    def raw_doors(self):
        return cascaded_union([door.geometry for door in self.query('doors').all()]).intersection(self.mapped)

    @cached_property
    def raw_escalators(self):
        return cascaded_union([escalator.geometry for escalator in self.query('escalators').all()])

    @cached_property
    def escalators(self):
        return self.raw_escalators.intersection(self.accessible)

    @cached_property
    def elevatorlevels(self):
        return cascaded_union([elevatorlevel.geometry for elevatorlevel in self.query('elevatorlevels').all()])

    @cached_property
    def areas(self):
        return cascaded_union([self.rooms, self.outsides, self.elevatorlevels])

    @cached_property
    def holes(self):
        return cascaded_union([holes.geometry for holes in self.query('holes').all()]).intersection(self.areas)

    @cached_property
    def accessible(self):
        return self.areas.difference(cascaded_union([self.holes, self.obstacles]))

    @cached_property
    def accessible_without_oneways(self):
        return self.accessible.difference(self.oneways_buffered)

    @cached_property
    def buildings_with_holes(self):
        return self.buildings.difference(self.holes)

    @cached_property
    def outsides_with_holes(self):
        return self.outsides.difference(self.holes)

    @cached_property
    def areas_and_doors(self):
        return cascaded_union([self.areas, self.raw_doors])

    @cached_property
    def walls(self):
        return self.buildings.difference(self.areas_and_doors)

    @cached_property
    def walls_shadow(self):
        return self.walls.buffer(0.2, join_style=JOIN_STYLE.mitre).intersection(self.buildings_with_holes)

    @cached_property
    def doors(self):
        return self.raw_doors.difference(self.areas)

    def get_levelconnectors(self, to_level=None):
        queryset = self.query('levelconnectors').prefetch_related('levels')
        if to_level is not None:
            queryset = queryset.filter(levels=to_level)
        return cascaded_union([levelconnector.geometry for levelconnector in queryset])

    @cached_property
    def levelconnectors(self):
        return cascaded_union([levelconnector.geometry for levelconnector in self.query('levelconnectors')])

    @cached_property
    def intermediate_shadows(self):
        qs = self.query('levelconnectors').prefetch_related('levels').filter(levels__altitude__lt=self.level.altitude)
        connectors = cascaded_union([levelconnector.geometry for levelconnector in qs])
        shadows = self.buildings.difference(connectors.buffer(0.4, join_style=JOIN_STYLE.mitre))
        shadows = shadows.buffer(0.3)
        return shadows

    @cached_property
    def hole_shadows(self):
        holes = self.holes.buffer(0.1, join_style=JOIN_STYLE.mitre)
        shadows = holes.difference(self.holes.buffer(-0.3, join_style=JOIN_STYLE.mitre))

        qs = self.query('levelconnectors').prefetch_related('levels').filter(levels__altitude__lt=self.level.altitude)
        connectors = cascaded_union([levelconnector.geometry for levelconnector in qs])

        shadows = shadows.difference(connectors.buffer(1.0, join_style=JOIN_STYLE.mitre))
        return shadows

    @cached_property
    def stairs(self):
        return cascaded_union([stair.geometry for stair in self.query('stairs')]).intersection(self.accessible)

    @cached_property
    def escalatorslopes(self):
        return cascaded_union([s.geometry for s in self.query('escalatorslopes')]).intersection(self.accessible)

    @cached_property
    def oneways_raw(self):
        return cascaded_union([oneway.geometry for oneway in self.query('oneways')])

    @cached_property
    def oneways(self):
        return self.oneways_raw.intersection(self.accessible)

    @cached_property
    def oneways_buffered(self):
        return self.oneways_raw.buffer(0.05, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.square)

    @cached_property
    def stair_areas(self):
        left = []
        for stair in assert_multilinestring(self.stairs):
            left.append(stair.parallel_offset(0.15, 'right', join_style=JOIN_STYLE.mitre))
        return cascaded_union(left).buffer(0.20, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)

    @cached_property
    def stuffedareas(self):
        return cascaded_union([stuffedarea.geometry for stuffedarea in self.query('stuffedareas')])
